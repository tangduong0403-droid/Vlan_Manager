from datetime import datetime
import difflib
import io
import ipaddress
import os
import re
import threading
import yaml
from contextlib import redirect_stdout
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    send_file,
)
from dotenv import load_dotenv
from netmiko import ConnectHandler

from modules.validator import validate_yaml_files
from modules.monitor import NetworkMonitor
from core.deployment_manager import DeploymentManager

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "Web"))
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.urandom(24)

INVENTORY_PATH = os.path.join(BASE_DIR, "configs", "inventory.yaml")
VLANS_PATH = os.path.join(BASE_DIR, "configs", "vlans.yaml")
PORTS_PATH = os.path.join(BASE_DIR, "configs", "ports.yaml")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

MANAGER = DeploymentManager()
SSH_LOCK = threading.Lock()
MONITOR = NetworkMonitor(BASE_DIR, MANAGER, SSH_LOCK, interval_sec=60)
LAST_CONSOLE_OUTPUT = ""
LAST_VALIDATION_ERRORS = []


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        f.flush()
    try:
        MANAGER.reload_configs()
    except Exception:
        pass


def count_backups():
    total = 0
    if os.path.exists(BACKUPS_DIR):
        for _, _, files in os.walk(BACKUPS_DIR):
            total += len([f for f in files if f.endswith((".cfg", ".rsc"))])
    return total


def get_ordered_device_names():
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    names = [str(s.get("name", "")).strip() for s in inv if s.get("name")]
    if os.path.exists(BACKUPS_DIR):
        for entry in sorted(os.listdir(BACKUPS_DIR)):
            full_p = os.path.join(BACKUPS_DIR, entry)
            if os.path.isdir(full_p) and entry not in names:
                names.append(entry)
    return names


def get_backups_grouped_by_device():
    grouped = {}
    if os.path.exists(BACKUPS_DIR):
        for root, _, files in os.walk(BACKUPS_DIR):
            if root == BACKUPS_DIR:
                continue
            dev_name = os.path.basename(root)
            cfg_files = [
                os.path.relpath(os.path.join(root, fn), BASE_DIR).replace("\\", "/")
                for fn in files
                if fn.endswith((".cfg", ".rsc"))
            ]
            cfg_files.sort(
                key=lambda p: os.path.getmtime(os.path.join(BASE_DIR, p)),
                reverse=True,
            )
            if cfg_files:
                grouped[dev_name] = cfg_files
    return grouped


def _is_protected_mgmt_ip(cidr_str, mgmt_ip_str, reserved_uplink=""):
    """Tự động nhận diện địa chỉ IP/CIDR quản trị SSH mà không cần hardcode dải mạng."""
    raw_cidr = str(cidr_str or "").strip()
    clean_mgmt_ip = str(mgmt_ip_str or "").strip()
    if not raw_cidr or not clean_mgmt_ip:
        return False

    try:
        iface_obj = ipaddress.ip_interface(raw_cidr)
        mgmt_addr = ipaddress.ip_address(clean_mgmt_ip)
        if iface_obj.ip == mgmt_addr or mgmt_addr in iface_obj.network:
            return True
    except ValueError:
        if raw_cidr.split("/")[0].strip() == clean_mgmt_ip:
            return True

    return False


def _clean_cfg_for_diff(lines):
    ignore_prefixes = (
        "Building configuration",
        "Current configuration :",
        "! Last configuration change",
        "! NVRAM config last updated",
    )
    return [
        ln.rstrip("\r\n")
        for ln in lines
        if not any(ln.strip().startswith(p) for p in ignore_prefixes)
    ]


def _summarize_config_changes(before_lines, after_lines):
    diff = list(difflib.unified_diff(before_lines, after_lines, n=1, lineterm=""))
    highlights = []
    current_section = "Cấu hình chung"

    for line in diff:
        if line.startswith(("+++", "---", "@@")):
            continue

        content = line[1:].strip()
        if not content or content == "!":
            continue

        if not line.startswith(("+", "-")):
            stripped_ctx = line.strip()
            if stripped_ctx.lower().startswith((
                "vlan ",
                "interface ",
                "router ",
                "ip route",
                "line ",
                "ip access-list",
            )):
                current_section = stripped_ctx
            continue

        action = "Thêm mới" if line.startswith("+") else "Gỡ bỏ"
        low = content.lower()

        if low.startswith("vlan "):
            current_section = content
            highlights.append(f"<strong>[VLAN]</strong> {action} <code>{content}</code>")
        elif low.startswith("name ") and current_section.lower().startswith("vlan "):
            highlights.append(f"<strong>[{current_section}]</strong> {action} tên <code>{content}</code>")
        elif low.startswith("interface "):
            current_section = content
            highlights.append(f"<strong>[Cổng / Giao diện]</strong> {action} <code>{content}</code>")
        elif low.startswith("description"):
            highlights.append(f"<strong>[{current_section}]</strong> {action} mô tả: <code>{content}</code>")
        elif "switchport access vlan" in low:
            highlights.append(f"<strong>[{current_section}]</strong> {action} VLAN Access: <code>{content}</code>")
        elif "switchport trunk allowed vlan" in low:
            highlights.append(f"<strong>[{current_section}]</strong> {action} VLAN Trunk: <code>{content}</code>")
        elif "switchport mode" in low:
            highlights.append(f"<strong>[{current_section}]</strong> {action} chế độ cổng: <code>{content}</code>")
        elif low in ("shutdown", "no shutdown"):
            highlights.append(f"<strong>[{current_section}]</strong> {action} trạng thái: <code>{content}</code>")
        elif low.startswith("ip address"):
            highlights.append(f"<strong>[{current_section}]</strong> {action} địa chỉ IP: <code>{content}</code>")
        else:
            highlights.append(f"<strong>[{current_section}]</strong> {action} dòng lệnh: <code>{content}</code>")

    seen = set()
    unique_highlights = []
    for h in highlights:
        if h not in seen:
            seen.add(h)
            unique_highlights.append(h)
    return unique_highlights[:50]


def _parse_cisco_full_config(cfg_text):
    vlans_map = {}
    interfaces = {}
    reserved_vids = {1, 1002, 1003, 1004, 1005}

    lines = cfg_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        m_vlan = re.match(r"^vlan\s+(\d+)$", stripped, re.IGNORECASE)
        if m_vlan:
            vid = int(m_vlan.group(1))
            vname = f"VLAN_{vid}"
            i += 1
            while i < len(lines) and lines[i].startswith(" "):
                sub = lines[i].strip()
                m_name = re.match(r"^name\s+(\S+)$", sub, re.IGNORECASE)
                if m_name:
                    vname = m_name.group(1)
                i += 1
            if vid not in reserved_vids:
                vlans_map[vid] = vname
            continue

        m_if = re.match(r"^interface\s+(\S+)$", stripped, re.IGNORECASE)
        if m_if:
            iface_name = m_if.group(1)
            sub_cmds = []
            i += 1
            while i < len(lines) and lines[i].startswith(" "):
                sub = lines[i].strip()
                if sub:
                    sub_cmds.append(sub)

                    m_acc = re.match(r"^switchport\s+access\s+vlan\s+(\d+)$", sub, re.IGNORECASE)
                    if m_acc:
                        vid = int(m_acc.group(1))
                        if vid not in reserved_vids and vid not in vlans_map:
                            vlans_map[vid] = f"VLAN_{vid}"

                    m_trk = re.match(
                        r"^switchport\s+trunk\s+allowed\s+vlan\s+(?:add\s+)?([0-9,-]+)$",
                        sub,
                        re.IGNORECASE,
                    )
                    if m_trk:
                        for part in m_trk.group(1).split(","):
                            part = part.strip()
                            if "-" in part:
                                a, b = part.split("-", 1)
                                if a.isdigit() and b.isdigit():
                                    for v in range(int(a), int(b) + 1):
                                        if v not in reserved_vids and v not in vlans_map:
                                            vlans_map[v] = f"VLAN_{v}"
                            elif part.isdigit():
                                v = int(part)
                                if v not in reserved_vids and v not in vlans_map:
                                    vlans_map[v] = f"VLAN_{v}"
                i += 1
            interfaces[iface_name] = sub_cmds
            continue

        i += 1

    return vlans_map, interfaces


def _parse_mikrotik_full_config(rsc_text):
    vlans_info = {}
    iface_to_ip = {}
    trunk_ifaces = []

    current_section = ""
    for raw_ln in rsc_text.splitlines():
        ln = raw_ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("/"):
            current_section = ln
            continue

        if current_section.startswith("/interface vlan") and ln.startswith("add "):
            m_vid = re.search(r"vlan-id=(\d+)", ln)
            m_name = re.search(r'name="?([^\s"]+)"?', ln)
            m_if = re.search(r'interface="?([^\s"]+)"?', ln)
            if m_vid:
                vid = int(m_vid.group(1))
                vname = m_name.group(1) if m_name else f"VLAN_{vid}"
                parent_if = m_if.group(1) if m_if else "ether1"
                vlans_info[vid] = {"name": vname, "interface": parent_if}
                if parent_if not in trunk_ifaces:
                    trunk_ifaces.append(parent_if)

        elif current_section.startswith("/ip address") and ln.startswith("add "):
            m_addr = re.search(r'address="?([0-9./]+)"?', ln)
            m_if = re.search(r'interface="?([^\s"]+)"?', ln)
            if m_addr and m_if:
                iface_to_ip[m_if.group(1)] = m_addr.group(1)

    return vlans_info, iface_to_ip, trunk_ifaces


def _sync_all_yamls_from_backup(dev_name, dev_ip, dev_type, target_cfg):
    default_names = {
        10: "Phong_Dao_Tao",
        20: "Phong_Ke_Toan",
        30: "Phong_Quan_Tri",
        40: "Phong_IT",
    }

    inv_data = load_yaml(INVENTORY_PATH)
    switches = inv_data.get("switches") or []
    target_sw = next((s for s in switches if str(s.get("name", "")).strip() == dev_name), None)
    mgmt_uplink = str((target_sw or {}).get("mgmt_uplink") or "").strip().lower()

    vlan_data = load_yaml(VLANS_PATH)
    existing_vlans = vlan_data.get("vlans") or []
    existing_by_id = {}
    for v in existing_vlans:
        try:
            existing_by_id[int(v.get("vlan_id"))] = v
        except (TypeError, ValueError):
            continue

    ports_data = load_yaml(PORTS_PATH)
    ports_list = ports_data.get("ports_config") or []

    backup_vlan_ids = set()
    backup_vlan_names = {}

    if dev_type == "cisco_ios":
        target_vlans_map, target_ifaces = _parse_cisco_full_config(target_cfg)
        backup_vlan_names.update(target_vlans_map)
        backup_vlan_ids.update(target_vlans_map.keys())

        new_access = []
        new_trunk = []
        for iface, sub_cmds in target_ifaces.items():
            if iface.lower().startswith("vlan"):
                continue
            if mgmt_uplink and iface.lower() == mgmt_uplink:
                continue
            low_cmds = [c.lower() for c in sub_cmds]
            if any("switchport mode trunk" in c for c in low_cmds):
                new_trunk.append(iface)
            elif any("switchport mode access" in c for c in low_cmds):
                vid = 1
                for c in low_cmds:
                    m = re.search(r"switchport access vlan\s+(\d+)", c)
                    if m:
                        vid = int(m.group(1))
                        break
                if vid != 1:
                    new_access.append({"interface": iface, "vlan": vid})
                    backup_vlan_ids.add(vid)

        if new_access or new_trunk:
            entry = next((e for e in ports_list if str(e.get("switch_ip", "")).strip() == dev_ip), None)
            if entry is None:
                entry = {"switch_ip": dev_ip, "access_ports": [], "trunk_ports": []}
                ports_list.append(entry)
            entry["access_ports"] = new_access
            if new_trunk:
                entry["trunk_ports"] = new_trunk
            ports_data["ports_config"] = ports_list
            save_yaml(PORTS_PATH, ports_data)

    elif dev_type == "mikrotik_routeros":
        vlans_info, iface_to_ip, trunk_ifaces = _parse_mikrotik_full_config(target_cfg)
        for vid, info in vlans_info.items():
            backup_vlan_ids.add(vid)
            clean_name = re.sub(rf"^vlan{vid}[_-]?", "", info["name"], flags=re.IGNORECASE)
            if clean_name and not clean_name.isdigit():
                backup_vlan_names[vid] = clean_name

        if trunk_ifaces:
            entry = next((e for e in ports_list if str(e.get("switch_ip", "")).strip() == dev_ip), None)
            if entry is None:
                entry = {"switch_ip": dev_ip, "access_ports": [], "trunk_ports": []}
                ports_list.append(entry)
            entry["trunk_ports"] = trunk_ifaces
            ports_data["ports_config"] = ports_list
            save_yaml(PORTS_PATH, ports_data)

    other_devices_used_vlans = set()
    for p_entry in ports_list:
        if str(p_entry.get("switch_ip", "")).strip() == dev_ip:
            continue
        for acc in p_entry.get("access_ports") or []:
            try:
                other_devices_used_vlans.add(int(acc.get("vlan")))
            except (TypeError, ValueError):
                pass

    allowed_vlans = backup_vlan_ids | other_devices_used_vlans
    if allowed_vlans:
        synced_vlans = []
        for vid in sorted(allowed_vlans):
            old_item = existing_by_id.get(vid, {})
            old_name = str(old_item.get("name") or "").strip()
            if old_name and not old_name.startswith("VLAN_"):
                vname = old_name
            elif vid in backup_vlan_names and not backup_vlan_names[vid].startswith("VLAN_"):
                vname = backup_vlan_names[vid]
            else:
                vname = default_names.get(vid, f"VLAN_{vid}")

            gw = str(old_item.get("gateway") or "").strip() or f"192.168.{vid}.1/24"
            synced_vlans.append({
                "vlan_id": vid,
                "name": vname,
                "gateway": gw,
            })
        vlan_data["vlans"] = synced_vlans
        save_yaml(VLANS_PATH, vlan_data)


def _build_cisco_rollback_commands(current_cfg, target_cfg):
    curr_vlans_map, curr_ifaces = _parse_cisco_full_config(current_cfg)
    target_vlans_map, target_ifaces = _parse_cisco_full_config(target_cfg)

    cmds = []

    if target_vlans_map:
        for vid in sorted(set(curr_vlans_map.keys()) - set(target_vlans_map.keys())):
            cmds.append(f"no vlan {vid}")

        for vid in sorted(target_vlans_map.keys()):
            vname = target_vlans_map[vid]
            cmds.append(f"vlan {vid}")
            if vname and vname != f"VLAN_{vid}":
                cmds.append(f" name {vname}")
            cmds.append("exit")

    all_ifaces = sorted(set(curr_ifaces.keys()) | set(target_ifaces.keys()))
    for iface in all_ifaces:
        if iface.lower().startswith("vlan"):
            continue
        t_cmds = target_ifaces.get(iface, [])
        is_trunk = any("switchport mode trunk" in c.lower() for c in t_cmds)

        cmds.append(f"default interface {iface}")
        cmds.append(f"interface {iface}")
        for sub in t_cmds:
            if is_trunk and sub.lower().startswith("switchport access vlan"):
                continue
            cmds.append(f" {sub}")
        if not any(x.lower() == "shutdown" for x in t_cmds):
            cmds.append(" no shutdown")
        cmds.append("exit")

    return cmds


def _get_device_conn_params(dev_dict):
    name = str(dev_dict.get("name", "")).strip()
    ip = str(dev_dict.get("ip", "")).strip()
    dev_type = str(dev_dict.get("device_type", "cisco_ios")).strip()
    prefix = str(dev_dict.get("env_prefix", name)).strip()

    username = (
        os.getenv(f"{prefix}_USERNAME")
        or os.getenv(f"{prefix}_USER")
        or dev_dict.get("username")
        or "admin"
    )
    password = (
        os.getenv(f"{prefix}_PASSWORD")
        or os.getenv(f"{prefix}_PASS")
        or dev_dict.get("password")
        or "admin123"
    )
    secret = os.getenv(f"{prefix}_SECRET") or dev_dict.get("secret") or password

    params = {
        "device_type": dev_type,
        "host": ip,
        "port": int(dev_dict.get("port", 22)),
        "username": username,
        "password": password,
        "timeout": 25,
    }
    if dev_type == "cisco_ios":
        params["secret"] = secret
    return params


def run_with_validation(action_func):
    buf = io.StringIO()
    val_errors = []
    with SSH_LOCK:
        with redirect_stdout(buf):
            can_proceed = validate_yaml_files(error_list=val_errors, strict=False)
            if can_proceed:
                try:
                    MANAGER.reload_configs()
                    action_func()
                except Exception as exc:
                    print(f"\n[LỖI KHI THỰC THI TÁC VỤ] {exc}")
    return can_proceed, val_errors, buf.getvalue()


@app.route("/")
def index():
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    vlans = load_yaml(VLANS_PATH).get("vlans", [])
    ports_cfg = load_yaml(PORTS_PATH).get("ports_config", [])

    total_access_ports = sum(len(item.get("access_ports") or []) for item in ports_cfg)

    ordered_devs = get_ordered_device_names()
    grouped_raw = get_backups_grouped_by_device()

    backup_files = []
    max_len = max((len(grouped_raw.get(d, [])) for d in ordered_devs), default=0)
    for i in range(max_len):
        for dev_name in ordered_devs:
            dev_list = grouped_raw.get(dev_name, [])
            if i < len(dev_list):
                backup_files.append(dev_list[i].replace("/", os.sep))

    snapshot = MANAGER.get_dashboard_snapshot()
    state_by_name = {s["name"]: s for s in snapshot["device_states"]}

    return render_template(
        "Web.html",
        switches=inv,
        vlans=vlans,
        ports_config=ports_cfg,
        total_devices=len(inv),
        total_vlans=len(vlans),
        total_access=total_access_ports,
        total_backups=count_backups(),
        backup_files=backup_files[:25],
        snapshot=snapshot,
        state_by_name=state_by_name,
        last_output=LAST_CONSOLE_OUTPUT,
        validation_errors=LAST_VALIDATION_ERRORS,
        active_tab=request.args.get("tab", "overview"),
    )


@app.route("/api/dashboard-state")
def api_dashboard_state():
    return jsonify(MANAGER.get_dashboard_snapshot())


@app.route("/api/monitor/status", methods=["GET"])
def api_monitor_status():
    return jsonify(MONITOR.get_state())


@app.route("/api/monitor/scan-now", methods=["POST"])
def api_monitor_scan_now():
    started = MONITOR.trigger_scan_now()
    if not started:
        return jsonify({"status": "busy", "message": "Hệ thống đang thực hiện quét, vui lòng đợi..."}), 200
    return jsonify({"status": "ok", "message": "Đã kích hoạt quét giám sát ngay."}), 200


@app.route("/api/backups/list", methods=["GET"])
def api_backups_list():
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    dev_types = {str(s.get("name", "")).strip(): str(s.get("device_type", "")).strip() for s in inv}
    return jsonify({
        "order": get_ordered_device_names(),
        "grouped": get_backups_grouped_by_device(),
        "types": dev_types,
    })


@app.route("/api/backups/diff", methods=["POST"])
def api_backups_diff():
    req = request.get_json(silent=True) or {}
    file_before = str(req.get("before", "")).strip()
    file_after = str(req.get("after", "")).strip()

    if not file_before or not file_after:
        return jsonify({"status": "error", "message": "Vui lòng chọn đủ 2 bản sao lưu trước và sau."}), 400

    abs_before = os.path.abspath(os.path.join(BASE_DIR, file_before))
    abs_after = os.path.abspath(os.path.join(BASE_DIR, file_after))
    abs_backups = os.path.abspath(BACKUPS_DIR)

    if not (abs_before.startswith(abs_backups) and abs_after.startswith(abs_backups)):
        return jsonify({"status": "error", "message": "Đường dẫn tệp không hợp lệ."}), 403

    if not (os.path.exists(abs_before) and os.path.exists(abs_after)):
        return jsonify({"status": "error", "message": "Không tìm thấy tệp sao lưu trên hệ thống."}), 404

    with open(abs_before, "r", encoding="utf-8", errors="ignore") as f1:
        raw_before = f1.readlines()
    with open(abs_after, "r", encoding="utf-8", errors="ignore") as f2:
        raw_after = f2.readlines()

    lines_before = _clean_cfg_for_diff(raw_before)
    lines_after = _clean_cfg_for_diff(raw_after)

    matcher = difflib.SequenceMatcher(None, lines_before, lines_after)
    side_by_side = []
    added_count = 0
    removed_count = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            chunk = list(zip(range(i1 + 1, i2 + 1), lines_before[i1:i2], range(j1 + 1, j2 + 1), lines_after[j1:j2]))
            if len(chunk) > 5:
                for l_no, l_txt, r_no, r_txt in chunk[:2]:
                    side_by_side.append({"type": "equal", "l_no": l_no, "l_txt": l_txt, "r_no": r_no, "r_txt": r_txt})
                side_by_side.append({"type": "skip", "count": len(chunk) - 4})
                for l_no, l_txt, r_no, r_txt in chunk[-2:]:
                    side_by_side.append({"type": "equal", "l_no": l_no, "l_txt": l_txt, "r_no": r_no, "r_txt": r_txt})
            else:
                for l_no, l_txt, r_no, r_txt in chunk:
                    side_by_side.append({"type": "equal", "l_no": l_no, "l_txt": l_txt, "r_no": r_no, "r_txt": r_txt})
        else:
            max_span = max(i2 - i1, j2 - j1)
            for k in range(max_span):
                has_l = (i1 + k) < i2
                has_r = (j1 + k) < j2
                if has_l:
                    removed_count += 1
                if has_r:
                    added_count += 1
                side_by_side.append({
                    "type": tag,
                    "l_no": (i1 + k + 1) if has_l else "",
                    "l_txt": lines_before[i1 + k] if has_l else "",
                    "r_no": (j1 + k + 1) if has_r else "",
                    "r_txt": lines_after[j1 + k] if has_r else "",
                })

    has_changes = (added_count > 0 or removed_count > 0)
    highlights = _summarize_config_changes(lines_before, lines_after) if has_changes else []

    return jsonify({
        "status": "ok",
        "has_changes": has_changes,
        "added": added_count,
        "removed": removed_count,
        "highlights": highlights,
        "rows": side_by_side if has_changes else [],
        "before_name": os.path.basename(file_before),
        "after_name": os.path.basename(file_after),
    })


@app.route("/api/backups/rollback", methods=["POST"])
def api_backups_rollback():
    req = request.get_json(silent=True) or {}
    rel_backup_path = str(req.get("backup_file", "")).strip()

    if not rel_backup_path:
        return jsonify({"status": "error", "message": "Vui lòng chọn tệp sao lưu cần khôi phục."}), 400

    abs_backup = os.path.abspath(os.path.join(BASE_DIR, rel_backup_path))
    abs_backups_dir = os.path.abspath(BACKUPS_DIR)

    if not abs_backup.startswith(abs_backups_dir) or not os.path.exists(abs_backup):
        return jsonify({"status": "error", "message": "Không tìm thấy tệp sao lưu hợp lệ."}), 404

    dev_name = os.path.basename(os.path.dirname(abs_backup))
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    target_dev = next((s for s in inv if str(s.get("name", "")).strip() == dev_name), None)

    if not target_dev:
        return jsonify({
            "status": "error",
            "message": f"Thiết bị '{dev_name}' không tồn tại trong configs/inventory.yaml hiện tại."
        }), 404

    with open(abs_backup, "r", encoding="utf-8", errors="ignore") as f:
        target_cfg = f.read()

    if not target_cfg.strip():
        return jsonify({"status": "error", "message": "Tệp sao lưu bị rỗng, từ chối khôi phục."}), 400

    ip = str(target_dev.get("ip", "")).strip()
    dev_type = str(target_dev.get("device_type", "cisco_ios")).strip()
    mgmt_uplink = str(target_dev.get("mgmt_uplink") or "").strip()
    conn_params = _get_device_conn_params(target_dev)

    with SSH_LOCK:
        try:
            conn = ConnectHandler(**conn_params)

            if dev_type == "cisco_ios":
                conn.enable()
                current_cfg = conn.send_command("show running-config")
                cmds = _build_cisco_rollback_commands(current_cfg, target_cfg)
                output = conn.send_config_set(cmds)
                output += "\n" + conn.send_command("write memory")

            elif dev_type == "mikrotik_routeros":
                vlans_info, iface_to_ip, _ = _parse_mikrotik_full_config(target_cfg)
                exec_logs = []
                if vlans_info:
                    for if_name, cidr in iface_to_ip.items():
                        if not _is_protected_mgmt_ip(cidr, ip, mgmt_uplink):
                            exec_logs.append(conn.send_command(f'/ip address remove [find interface="{if_name}"]'))
                    exec_logs.append(conn.send_command("/interface vlan remove [find]"))

                    for vid in sorted(vlans_info.keys()):
                        info = vlans_info[vid]
                        sub_name = info["name"]
                        parent_if = info["interface"]
                        exec_logs.append(
                            conn.send_command(f'/interface vlan add name="{sub_name}" vlan-id={vid} interface={parent_if}')
                        )
                        gw = iface_to_ip.get(sub_name)
                        if gw and not _is_protected_mgmt_ip(gw, ip, mgmt_uplink):
                            exec_logs.append(
                                conn.send_command(f'/ip address add address={gw} interface="{sub_name}"')
                            )
                output = "\n".join(x for x in exec_logs if x) or "Đã khôi phục cấu hình VLAN & IP Gateway trên MikroTik."
            else:
                conn.disconnect()
                return jsonify({"status": "error", "message": f"Chưa hỗ trợ rollback cho {dev_type}."}), 400

            conn.disconnect()

            _sync_all_yamls_from_backup(dev_name, ip, dev_type, target_cfg)

            chosen_filename = os.path.basename(abs_backup)
            msg = (
                f"Đã khôi phục cấu hình {dev_name} ({ip}) về đúng bản: {chosen_filename} "
                f"(đã bảo toàn toàn bộ VLAN, Cổng và IP quản trị hiện có)."
            )
            flash(msg, "success")
            return jsonify({
                "status": "ok",
                "message": msg,
                "restored_file": rel_backup_path.replace("\\", "/"),
                "device": dev_name,
                "log": output[-2500:],
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"Lỗi khi khôi phục {dev_name} ({ip}): {str(e)}"
            }), 500


@app.route("/report/download/ports")
def download_port_report():
    if MANAGER.latest_port_csv and os.path.exists(MANAGER.latest_port_csv):
        return send_file(MANAGER.latest_port_csv, as_attachment=True)
    flash("Chưa có file báo cáo sử dụng cổng. Hãy chạy phân tích trước.", "warning")
    return redirect(url_for("index", tab="port_report"))


@app.route("/device/add", methods=["POST"])
def add_device():
    inv_data = load_yaml(INVENTORY_PATH)
    switches = inv_data.setdefault("switches", [])
    new_sw = {
        "name": request.form.get("name", "").strip(),
        "ip": request.form.get("ip", "").strip(),
        "device_type": request.form.get("device_type", "cisco_ios").strip(),
        "env_prefix": request.form.get("env_prefix", "").strip(),
    }
    mgmt_uplink = request.form.get("mgmt_uplink", "").strip()
    if mgmt_uplink:
        new_sw["mgmt_uplink"] = mgmt_uplink

    switches.append(new_sw)
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_list = ports_data.setdefault("ports_config", [])
    if not any(str(p.get("switch_ip", "")).strip() == new_sw["ip"] for p in ports_list):
        ports_list.append({"switch_ip": new_sw["ip"], "access_ports": [], "trunk_ports": []})
        save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã thêm thiết bị {new_sw['name']} ({new_sw['ip']}).", "success")
    return redirect(url_for("index", tab="overview"))


@app.route("/device/edit", methods=["POST"])
def edit_device():
    old_ip = request.form.get("old_ip", "").strip()
    new_ip = request.form.get("ip", "").strip()
    inv_data = load_yaml(INVENTORY_PATH)
    for sw in inv_data.get("switches", []):
        if str(sw.get("ip", "")).strip() == old_ip:
            sw["name"] = request.form.get("name", "").strip()
            sw["ip"] = new_ip
            sw["device_type"] = request.form.get("device_type", "cisco_ios").strip()
            sw["env_prefix"] = request.form.get("env_prefix", "").strip()
            mgmt_uplink = request.form.get("mgmt_uplink", "").strip()
            if mgmt_uplink:
                sw["mgmt_uplink"] = mgmt_uplink
            elif "mgmt_uplink" in sw and request.form.get("mgmt_uplink") is not None:
                sw.pop("mgmt_uplink", None)
            break
    save_yaml(INVENTORY_PATH, inv_data)

    if old_ip != new_ip:
        ports_data = load_yaml(PORTS_PATH)
        for p in ports_data.get("ports_config", []):
            if str(p.get("switch_ip", "")).strip() == old_ip:
                p["switch_ip"] = new_ip
        save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã cập nhật thiết bị ({new_ip}).", "success")
    return redirect(url_for("index", tab="overview"))


@app.route("/device/delete/<ip>", methods=["POST"])
def delete_device(ip):
    ip = ip.strip()
    inv_data = load_yaml(INVENTORY_PATH)
    inv_data["switches"] = [s for s in inv_data.get("switches", []) if str(s.get("ip", "")).strip() != ip]
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_data["ports_config"] = [
        p for p in ports_data.get("ports_config", []) if str(p.get("switch_ip", "")).strip() != ip
    ]
    save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã xóa thiết bị {ip}.", "warning")
    return redirect(url_for("index", tab="overview"))


@app.route("/vlan/add", methods=["POST"])
def add_vlan():
    vlan_data = load_yaml(VLANS_PATH)
    vlans = vlan_data.setdefault("vlans", [])
    vid_raw = request.form.get("vlan_id", "").strip()
    vlans.append({
        "vlan_id": int(vid_raw) if vid_raw.isdigit() else vid_raw,
        "name": request.form.get("name", "").strip(),
        "gateway": request.form.get("gateway", "").strip(),
    })
    save_yaml(VLANS_PATH, vlan_data)
    flash("Đã thêm VLAN mới vào vlans.yaml.", "success")
    return redirect(url_for("index", tab="vlans"))


@app.route("/vlan/delete/<int:vlan_id>", methods=["POST"])
def delete_vlan(vlan_id):
    vlan_data = load_yaml(VLANS_PATH)
    vlan_data["vlans"] = [v for v in vlan_data.get("vlans", []) if v.get("vlan_id") != vlan_id]
    save_yaml(VLANS_PATH, vlan_data)
    flash(f"Đã xóa VLAN {vlan_id}.", "warning")
    return redirect(url_for("index", tab="vlans"))


@app.route("/port/add", methods=["POST"])
def add_port():
    sw_ip = request.form.get("switch_ip", "").strip()
    port_type = request.form.get("port_type", "access").strip().lower()
    iface = request.form.get("interface", "").strip()
    vlan_raw = request.form.get("vlan", "").strip()

    if not sw_ip or not iface:
        flash("Vui lòng chọn thiết bị và nhập tên cổng hợp lệ.", "danger")
        return redirect(url_for("index", tab="ports"))

    ports_data = load_yaml(PORTS_PATH)
    ports_list = ports_data.setdefault("ports_config", [])
    entry = next((e for e in ports_list if str(e.get("switch_ip", "")).strip() == sw_ip), None)
    if entry is None:
        entry = {"switch_ip": sw_ip, "access_ports": [], "trunk_ports": []}
        ports_list.append(entry)

    if port_type == "access":
        access_ports = entry.setdefault("access_ports", [])
        if any(str(a.get("interface", "")).strip() == iface for a in access_ports):
            flash(f"Cổng Access {iface} đã tồn tại trên {sw_ip}.", "warning")
            return redirect(url_for("index", tab="ports"))
        access_ports.append({
            "interface": iface,
            "vlan": int(vlan_raw) if vlan_raw.isdigit() else vlan_raw,
        })
    else:
        trunk_ports = entry.setdefault("trunk_ports", [])
        if any(str(t).strip() == iface for t in trunk_ports):
            flash(f"Cổng Trunk {iface} đã tồn tại trên {sw_ip}.", "warning")
            return redirect(url_for("index", tab="ports"))
        trunk_ports.append(iface)

    save_yaml(PORTS_PATH, ports_data)
    flash(f"Đã gán cổng {iface} ({port_type}) cho thiết bị {sw_ip} và lưu vào configs/ports.yaml.", "success")
    return redirect(url_for("index", tab="ports"))


@app.route("/port/delete", methods=["POST"])
def delete_port():
    sw_ip = request.form.get("switch_ip", "").strip()
    port_type = request.form.get("port_type", "access").strip().lower()
    iface = request.form.get("interface", "").strip()

    ports_data = load_yaml(PORTS_PATH)
    removed = False
    for entry in ports_data.get("ports_config", []):
        if str(entry.get("switch_ip", "")).strip() == sw_ip:
            if port_type == "access":
                old_list = entry.get("access_ports") or []
                new_list = [a for a in old_list if str(a.get("interface", "")).strip() != iface]
                if len(new_list) != len(old_list):
                    entry["access_ports"] = new_list
                    removed = True
            else:
                old_list = entry.get("trunk_ports") or []
                new_list = [t for t in old_list if str(t).strip() != iface]
                if len(new_list) != len(old_list):
                    entry["trunk_ports"] = new_list
                    removed = True
            break

    if removed:
        save_yaml(PORTS_PATH, ports_data)
        flash(f"Đã gỡ cổng {iface} ({port_type}) khỏi {sw_ip} và đồng bộ vào configs/ports.yaml.", "warning")
    else:
        flash(f"Không tìm thấy cổng {iface} ({port_type}) trên {sw_ip}.", "danger")

    return redirect(url_for("index", tab="ports"))


@app.route("/action/<cmd>", methods=["POST"])
def execute_action(cmd):
    global LAST_CONSOLE_OUTPUT, LAST_VALIDATION_ERRORS
    action_map = {
        "validate": ("1. Kiểm tra dữ liệu đầu vào", lambda: None, "automation"),
        "dry_run": ("2. Mô phỏng lệnh (Chạy thử)", lambda: MANAGER.execute_dry_run(interactive=False), "automation"),
        "backup": ("3. Sao lưu cấu hình hiện tại", MANAGER.execute_backup, "automation"),
        "deploy": ("4. Triển khai cấu hình tự động", MANAGER.execute_deploy, "automation"),
        "status": ("5. Thu thập thông tin thiết bị", MANAGER.execute_status, "facts"),
        "compliance": ("6. Kiểm tra tuân thủ cấu hình", MANAGER.execute_compliance, "automation"),
        "port_report": ("7. Xuất báo cáo sử dụng cổng (CSV)", MANAGER.execute_port_report, "port_report"),
    }
    if cmd not in action_map:
        flash("Lệnh không hợp lệ.", "danger")
        return redirect(url_for("index", tab="automation"))

    label, action_fn, target_tab = action_map[cmd]
    can_proceed, val_errors, output_log = run_with_validation(action_fn)
    LAST_CONSOLE_OUTPUT = output_log
    LAST_VALIDATION_ERRORS = val_errors

    if not can_proceed:
        flash("Lỗi cú pháp YAML nghiêm trọng (file không thể đọc). Vui lòng sửa cú pháp YAML.", "danger")
        target_tab = "automation"
    elif val_errors:
        flash(
            f"Ghi nhận {len(val_errors)} lỗi/cảnh báo cấu hình YAML (xem chi tiết bên dưới), "
            f"hệ thống vẫn tiếp tục thực hiện: {label}.",
            "warning",
        )
    else:
        flash(f"Hoàn tất tác vụ: {label}", "success")

    return redirect(url_for("index", tab=target_tab))


if __name__ == "__main__":
    MONITOR.start_background_loop()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
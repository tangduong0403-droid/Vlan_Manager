import io
import os
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

from modules.validator import validate_yaml_files
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
LAST_CONSOLE_OUTPUT = ""


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    try:
        MANAGER.reload_configs()
    except Exception:
        pass


def count_backups():
    total = 0
    if os.path.exists(BACKUPS_DIR):
        for _, _, files in os.walk(BACKUPS_DIR):
            total += len([f for f in files if f.endswith(".cfg")])
    return total


def run_with_validation(action_func):
    buf = io.StringIO()
    with redirect_stdout(buf):
        is_valid = validate_yaml_files()
        if is_valid:
            MANAGER.reload_configs()
            action_func()
    return is_valid, buf.getvalue()


@app.route("/")
def index():
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    vlans = load_yaml(VLANS_PATH).get("vlans", [])
    ports_cfg = load_yaml(PORTS_PATH).get("ports_config", [])

    total_access_ports = sum(len(item.get("access_ports") or []) for item in ports_cfg)
    backup_files = []
    if os.path.exists(BACKUPS_DIR):
        for root, _, files in os.walk(BACKUPS_DIR):
            for fn in sorted(files, reverse=True):
                if fn.endswith(".cfg"):
                    backup_files.append(os.path.relpath(os.path.join(root, fn), BASE_DIR))

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
        active_tab=request.args.get("tab", "overview"),
    )


@app.route("/api/dashboard-state")
def api_dashboard_state():
    return jsonify(MANAGER.get_dashboard_snapshot())


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
    switches.append(new_sw)
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_list = ports_data.setdefault("ports_config", [])
    if not any(p.get("switch_ip") == new_sw["ip"] for p in ports_list):
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
        if sw.get("ip") == old_ip:
            sw["name"] = request.form.get("name", "").strip()
            sw["ip"] = new_ip
            sw["device_type"] = request.form.get("device_type", "cisco_ios").strip()
            sw["env_prefix"] = request.form.get("env_prefix", "").strip()
            break
    save_yaml(INVENTORY_PATH, inv_data)

    if old_ip != new_ip:
        ports_data = load_yaml(PORTS_PATH)
        for p in ports_data.get("ports_config", []):
            if p.get("switch_ip") == old_ip:
                p["switch_ip"] = new_ip
        save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã cập nhật thiết bị ({new_ip}).", "success")
    return redirect(url_for("index", tab="overview"))


@app.route("/device/delete/<ip>", methods=["POST"])
def delete_device(ip):
    inv_data = load_yaml(INVENTORY_PATH)
    inv_data["switches"] = [s for s in inv_data.get("switches", []) if s.get("ip") != ip]
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_data["ports_config"] = [p for p in ports_data.get("ports_config", []) if p.get("switch_ip") != ip]
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
    port_type = request.form.get("port_type", "access")
    iface = request.form.get("interface", "").strip()
    vlan_raw = request.form.get("vlan", "").strip()

    ports_data = load_yaml(PORTS_PATH)
    for entry in ports_data.get("ports_config", []):
        if entry.get("switch_ip") == sw_ip:
            if port_type == "access":
                entry.setdefault("access_ports", []).append({
                    "interface": iface,
                    "vlan": int(vlan_raw) if vlan_raw.isdigit() else vlan_raw,
                })
            else:
                entry.setdefault("trunk_ports", []).append(iface)
            break
    save_yaml(PORTS_PATH, ports_data)
    flash(f"Đã gán cổng {iface} cho thiết bị {sw_ip}.", "success")
    return redirect(url_for("index", tab="ports"))


@app.route("/port/delete", methods=["POST"])
def delete_port():
    sw_ip = request.form.get("switch_ip", "").strip()
    port_type = request.form.get("port_type", "access")
    iface = request.form.get("interface", "").strip()

    ports_data = load_yaml(PORTS_PATH)
    for entry in ports_data.get("ports_config", []):
        if entry.get("switch_ip") == sw_ip:
            if port_type == "access":
                entry["access_ports"] = [a for a in (entry.get("access_ports") or []) if a.get("interface") != iface]
            else:
                entry["trunk_ports"] = [t for t in (entry.get("trunk_ports") or []) if t != iface]
            break
    save_yaml(PORTS_PATH, ports_data)
    flash(f"Đã gỡ cổng {iface} khỏi {sw_ip}.", "warning")
    return redirect(url_for("index", tab="ports"))


@app.route("/action/<cmd>", methods=["POST"])
def execute_action(cmd):
    global LAST_CONSOLE_OUTPUT
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
    is_valid, output_log = run_with_validation(action_fn)
    LAST_CONSOLE_OUTPUT = output_log

    if not is_valid:
        flash("Phát hiện lỗi trong file cấu hình YAML! Hệ thống đã chặn thực thi.", "danger")
        target_tab = "automation"
    else:
        flash(f"Hoàn tất tác vụ: {label}", "success")

    return redirect(url_for("index", tab=target_tab))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
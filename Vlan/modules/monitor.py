from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
import io
import os
import re
import threading
import time
import yaml
from netmiko import ConnectHandler


def _norm_cisco_iface(name: str) -> str:
    s = str(name).strip().lower()
    replacements = [
        ("tengigabitethernet", "te"),
        ("gigabitethernet", "gi"),
        ("fastethernet", "fa"),
        ("ethernet", "et"),
    ]
    for full, short in replacements:
        if s.startswith(full):
            return short + s[len(full):]
    return s


class NetworkMonitor:
    """
    Bộ giám sát mạng tự động (Chỉ đọc - Read-only):
    - Kiểm tra kết nối SSH tới từng thiết bị.
    - Đối soát VLAN thực tế trên thiết bị với configs/vlans.yaml.
    - Đối soát cổng Trunk & Access thực tế với configs/ports.yaml.
    - Cập nhật luôn trạng thái Online & Compliance cho DeploymentManager.
    """

    def __init__(self, base_dir: str, manager, ssh_lock: threading.Lock, interval_sec: int = 60):
        self.base_dir = base_dir
        self.manager = manager
        self.ssh_lock = ssh_lock
        self.interval_sec = interval_sec

        self._state_lock = threading.Lock()
        self._wake_event = threading.Event()
        self._started = False

        self.state = {
            "is_scanning": False,
            "last_scan_time": None,
            "next_scan_at": None,
            "interval_sec": interval_sec,
            "total_checked": 0,
            "alerts": [],
            "device_checks": [],
        }

    def get_state(self) -> dict:
        with self._state_lock:
            now_ts = time.time()
            next_at = self.state.get("next_scan_at")
            remaining = max(0, int(next_at - now_ts)) if (next_at and not self.state["is_scanning"]) else 0
            return {
                "is_scanning": self.state["is_scanning"],
                "last_scan_time": self.state["last_scan_time"],
                "seconds_until_next": remaining,
                "interval_sec": self.interval_sec,
                "total_checked": self.state["total_checked"],
                "alerts": list(self.state["alerts"]),
                "device_checks": list(self.state["device_checks"]),
            }

    def trigger_scan_now(self) -> bool:
        with self._state_lock:
            if self.state["is_scanning"]:
                return False
        self._wake_event.set()
        return True

    def start_background_loop(self):
        if self._started:
            return
        self._started = True
        t = threading.Thread(target=self._run_loop, name="NetworkAutoMonitor", daemon=True)
        t.start()

    def _run_loop(self):
        time.sleep(3)
        while True:
            self.run_single_scan()
            with self._state_lock:
                self.state["next_scan_at"] = time.time() + self.interval_sec
            self._wake_event.wait(timeout=self.interval_sec)
            self._wake_event.clear()

    def _load_yaml(self, rel_path: str) -> dict:
        full_path = os.path.join(self.base_dir, rel_path)
        if not os.path.exists(full_path):
            return {}
        with open(full_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _build_conn_params(self, dev: dict) -> dict:
        name = str(dev.get("name", "")).strip()
        ip = str(dev.get("ip", "")).strip()
        dev_type = str(dev.get("device_type", "cisco_ios")).strip()
        prefix = str(dev.get("env_prefix", name)).strip()

        username = (
            os.getenv(f"{prefix}_USERNAME")
            or os.getenv(f"{prefix}_USER")
            or dev.get("username")
            or "admin"
        )
        password = (
            os.getenv(f"{prefix}_PASSWORD")
            or os.getenv(f"{prefix}_PASS")
            or dev.get("password")
            or "admin123"
        )
        secret = os.getenv(f"{prefix}_SECRET") or dev.get("secret") or password

        params = {
            "device_type": dev_type,
            "host": ip,
            "port": int(dev.get("port", 22)),
            "username": username,
            "password": password,
            "timeout": 15,
        }
        if dev_type == "cisco_ios":
            params["secret"] = secret
        return params

    def _check_single_device(self, dev: dict, expected_vlan_ids: set, port_entry: dict) -> dict:
        name = str(dev.get("name", "")).strip()
        ip = str(dev.get("ip", "")).strip()
        dev_type = str(dev.get("device_type", "cisco_ios")).strip()
        expected_trunks = port_entry.get("trunk_ports") or []
        expected_access = port_entry.get("access_ports") or []

        result = {
            "name": name,
            "ip": ip,
            "device_type": dev_type,
            "ssh_ok": False,
            "vlan_ok": False,
            "trunk_ok": False,
            "issues": [],
        }

        try:
            conn = ConnectHandler(**self._build_conn_params(dev))
            result["ssh_ok"] = True

            if dev_type == "cisco_ios":
                conn.enable()
                vlan_out = conn.send_command("show vlan brief")
                trunk_out = conn.send_command("show interfaces trunk")
                run_out = conn.send_command("show running-config | section ^interface")
                conn.disconnect()

                active_vlans = set()
                for line in vlan_out.splitlines():
                    m = re.match(r"^(\d+)\s+\S+", line.strip())
                    if m:
                        active_vlans.add(int(m.group(1)))

                missing_vlans = sorted(expected_vlan_ids - active_vlans)
                if missing_vlans:
                    result["issues"].append(f"Thiếu VLAN {missing_vlans} trên thiết bị.")
                else:
                    result["vlan_ok"] = True

                active_trunks_norm = set()
                for line in trunk_out.splitlines():
                    parts = line.strip().split()
                    if parts and re.match(r"^(Et|Fa|Gi|Te)\d+(/\d+)+$", parts[0], re.IGNORECASE):
                        active_trunks_norm.add(_norm_cisco_iface(parts[0]))

                iface_blocks = {}
                cur_if = None
                for ln in run_out.splitlines():
                    s = ln.strip()
                    if s.lower().startswith("interface "):
                        cur_if = _norm_cisco_iface(s.split(None, 1)[1])
                        iface_blocks[cur_if] = []
                    elif cur_if and ln.startswith(" "):
                        iface_blocks[cur_if].append(s.lower())

                missing_trunks = []
                for t_port in expected_trunks:
                    nt = _norm_cisco_iface(t_port)
                    in_trunk_table = nt in active_trunks_norm
                    has_trunk_cfg = any("switchport mode trunk" in c for c in iface_blocks.get(nt, []))
                    if not (in_trunk_table or has_trunk_cfg):
                        missing_trunks.append(str(t_port))

                wrong_access = []
                for acc in expected_access:
                    if not isinstance(acc, dict):
                        continue
                    a_if = str(acc.get("interface", "")).strip()
                    a_vid = acc.get("vlan")
                    na = _norm_cisco_iface(a_if)
                    cmds = iface_blocks.get(na, [])
                    if f"switchport access vlan {a_vid}" not in cmds:
                        wrong_access.append(f"{a_if} (kỳ vọng VLAN {a_vid})")

                if missing_trunks:
                    result["issues"].append(f"Cổng Trunk chưa đúng chuẩn: {', '.join(missing_trunks)}.")
                if wrong_access:
                    result["issues"].append(f"Cổng Access sai VLAN: {', '.join(wrong_access)}.")
                if not missing_trunks and not wrong_access:
                    result["trunk_ok"] = True

            elif dev_type == "mikrotik_routeros":
                vlan_print = conn.send_command("/interface vlan print detail without-paging")
                conn.disconnect()

                active_vlans = set(int(x) for x in re.findall(r"vlan-id=(\d+)", vlan_print))
                missing_vlans = sorted(expected_vlan_ids - active_vlans)
                if missing_vlans:
                    result["issues"].append(f"Router thiếu sub-interface VLAN {missing_vlans}.")
                else:
                    result["vlan_ok"] = True

                missing_trunks = []
                for t_port in expected_trunks:
                    if f"interface={t_port}" not in vlan_print and f'interface="{t_port}"' not in vlan_print:
                        missing_trunks.append(str(t_port))

                if missing_trunks:
                    result["issues"].append(f"Chưa gắn VLAN lên cổng Trunk: {', '.join(missing_trunks)}.")
                else:
                    result["trunk_ok"] = True
            else:
                conn.disconnect()
                result["vlan_ok"] = True
                result["trunk_ok"] = True

        except Exception as e:
            result["issues"].append(f"Mất kết nối SSH ({ip}): {str(e).splitlines()[0]}")

        return result

    def run_single_scan(self):
        if not self.ssh_lock.acquire(blocking=False):
            return

        try:
            with self._state_lock:
                self.state["is_scanning"] = True

            inv_data = self._load_yaml(os.path.join("configs", "inventory.yaml"))
            vlan_data = self._load_yaml(os.path.join("configs", "vlans.yaml"))
            port_data = self._load_yaml(os.path.join("configs", "ports.yaml"))

            switches = [s for s in (inv_data.get("switches") or []) if isinstance(s, dict)]
            expected_vlan_ids = {
                int(v["vlan_id"])
                for v in (vlan_data.get("vlans") or [])
                if isinstance(v, dict) and str(v.get("vlan_id", "")).isdigit()
            }
            ports_by_ip = {
                str(p.get("switch_ip", "")).strip(): p
                for p in (port_data.get("ports_config") or [])
                if isinstance(p, dict)
            }

            device_checks = []
            if switches:
                with ThreadPoolExecutor(max_workers=min(8, len(switches))) as pool:
                    futures = [
                        pool.submit(
                            self._check_single_device,
                            sw,
                            expected_vlan_ids,
                            ports_by_ip.get(str(sw.get("ip", "")).strip(), {}),
                        )
                        for sw in switches
                    ]
                    device_checks = [f.result() for f in futures]

            try:
                with redirect_stdout(io.StringIO()):
                    self.manager.reload_configs()
                    self.manager.execute_status()
                    self.manager.execute_compliance()
            except Exception:
                pass

            alerts = []
            for item in device_checks:
                for iss in item["issues"]:
                    alerts.append(f"[{item['name']} - {item['ip']}] {iss}")

            with self._state_lock:
                self.state["is_scanning"] = False
                self.state["last_scan_time"] = datetime.now().strftime("%H:%M:%S")
                self.state["total_checked"] = len(device_checks)
                self.state["alerts"] = alerts
                self.state["device_checks"] = device_checks
        finally:
            self.ssh_lock.release()
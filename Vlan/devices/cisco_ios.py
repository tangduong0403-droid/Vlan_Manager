import re
from core.network_device import NetworkDevice

PHYSICAL_PORT_RE = re.compile(
    r"^(Ethernet|FastEthernet|GigabitEthernet|TenGigabitEthernet|Et|Fa|Gi|Te)\d+(/\d+)+$",
    re.IGNORECASE,
)


class CiscoIOSDevice(NetworkDevice):
    def build_commands(self, jinja_env, vlans: list, port_cfg: dict) -> list:
        template = jinja_env.get_template("vlan.j2")
        raw = template.render(device_type="cisco_ios", vlans=vlans, port_cfg=port_cfg)
        return [line for line in raw.splitlines() if line.strip()]

    def deploy(self, commands: list):
        self.connection.send_config_set(commands)

    def save_config(self) -> str:
        self.connection.save_config()
        return "SUCCESS"

    def get_running_config(self) -> str:
        return self.connection.send_command("show running-config")

    def check_compliance(self, rules: dict, port_cfg: dict) -> dict:
        report = {}
        run_cfg = self.connection.send_command("show running-config")
        vlan_brief = self.connection.send_command("show vlan brief")

        if rules.get("require_ssh"):
            report["SSH Enabled"] = "PASS" if ("transport input ssh" in run_cfg or "ip ssh version" in run_cfg) else "FAIL"
        if rules.get("forbid_telnet"):
            report["Telnet Disabled"] = "PASS" if ("transport input ssh" in run_cfg and "telnet" not in run_cfg) else "FAIL"

        for vid in rules.get("required_vlans", []):
            report[f"VLAN {vid}"] = "PASS" if f"\n{vid} " in f"\n{vlan_brief}" else "FAIL"

        approved = rules.get("approved_trunk_vlans", "10,20,30,40")
        expected_trunks = port_cfg.get("trunk_ports", []) if port_cfg else []
        trunks_ok = (
            all(f"interface {t}" in run_cfg for t in expected_trunks)
            and ("switchport mode trunk" in run_cfg)
            and (f"switchport trunk allowed vlan {approved}" in run_cfg)
        )
        report["Trunk Policy"] = "PASS" if trunks_ok else "FAIL"

        forbidden_pwds = rules.get("forbidden_passwords", [])
        weak_found = any(f"password 0 {p}" in run_cfg or f"password {p}" in run_cfg for p in forbidden_pwds)
        report["No Default Password"] = "FAIL" if weak_found else "PASS"

        return report

    @staticmethod
    def _normalize_iface(name: str) -> str:
        n = name.strip().lower()
        replacements = [
            ("gigabitethernet", "gi"),
            ("fastethernet", "fa"),
            ("tengigabitethernet", "te"),
            ("ethernet", "et"),
        ]
        for full, short in replacements:
            if n.startswith(full):
                return short + n[len(full):]
        return n

    def _parse_physical_interfaces(self) -> list:
        """Lấy danh sách cổng vật lý thực tế từ show interfaces status (hoặc fallback show ip interface brief)."""
        ports = []
        status_out = self.connection.send_command("show interfaces status")

        if status_out and "Invalid input" not in status_out:
            for line in status_out.splitlines():
                m = re.match(
                    r"^((?:Et|Fa|Gi|Te)\d+/\d+(?:/\d+)?)\s+.*?\s+(connected|notconnect|disabled|err-disabled|sfpAbsent)\s+(\S+)",
                    line.strip(),
                    re.IGNORECASE,
                )
                if m:
                    iface, state, vlan_col = m.group(1), m.group(2).lower(), m.group(3)
                    ports.append({
                        "interface": iface,
                        "status": "UP" if state == "connected" else "DOWN",
                        "raw_state": state,
                        "vlan_col": vlan_col,
                    })

        if not ports:
            brief_out = self.connection.send_command("show ip interface brief")
            for line in brief_out.splitlines():
                m = re.match(
                    r"^(\S+)\s+(\S+)\s+\S+\s+\S+\s+(administratively down|up|down)\s+(up|down)",
                    line.strip(),
                    re.IGNORECASE,
                )
                if m and PHYSICAL_PORT_RE.match(m.group(1)):
                    iface, st, proto = m.group(1), m.group(3).lower(), m.group(4).lower()
                    is_up = st == "up" and proto == "up"
                    ports.append({
                        "interface": iface,
                        "status": "UP" if is_up else "DOWN",
                        "raw_state": f"{st}/{proto}",
                        "vlan_col": "-",
                    })
        return ports

    def collect_facts(self) -> dict:
        ver_out = self.connection.send_command("show version")
        cpu_out = self.connection.send_command("show processes cpu | include CPU")
        mem_out = self.connection.send_command("show processes memory sorted | include Processor")
        route_out = self.connection.send_command("show ip route")
        arp_out = self.connection.send_command("show ip arp")
        mac_out = self.connection.send_command("show mac address-table dynamic")

        ver_match = re.search(r"Version\s+([^,\s]+)", ver_out)
        os_version = f"Cisco IOS {ver_match.group(1)}" if ver_match else "Cisco IOS (Unknown)"

        up_match = re.search(r"uptime is\s+([^\r\n]+)", ver_out, re.IGNORECASE)
        uptime = up_match.group(1).strip() if up_match else "N/A"

        cpu_match = re.search(
            r"five seconds:\s*([^;]+);\s*one minute:\s*([^;]+);\s*five minutes:\s*(\S+)",
            cpu_out,
            re.IGNORECASE,
        )
        cpu_usage = (
            f"5s: {cpu_match.group(1).strip()} | 1m: {cpu_match.group(2).strip()} | 5m: {cpu_match.group(3).strip()}"
            if cpu_match
            else (cpu_out.strip().splitlines()[0] if cpu_out.strip() else "N/A")
        )

        mem_match = re.search(r"Total:\s*(\d+)\s+Used:\s*(\d+)\s+Free:\s*(\d+)", mem_out, re.IGNORECASE)
        if mem_match:
            total_b, used_b, _ = map(int, mem_match.groups())
            pct = round((used_b / total_b) * 100, 1) if total_b > 0 else 0.0
            ram_usage = f"{pct}% ({used_b // (1024 * 1024)}/{total_b // (1024 * 1024)} MB)"
        else:
            ram_usage = "N/A"

        ports = self._parse_physical_interfaces()
        up_count = sum(1 for p in ports if p["status"] == "UP")

        route_lines = [
            ln.strip() for ln in route_out.splitlines()
            if re.match(r"^[CLSRDBOi*]\s", ln.strip())
        ]
        arp_lines = [ln.strip() for ln in arp_out.splitlines() if ln.strip().startswith("Internet")]
        mac_lines = [
            ln.strip() for ln in mac_out.splitlines()
            if re.search(r"[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}", ln)
        ]

        return {
            "device": self.name,
            "ip": self.ip,
            "device_type": self.device_type,
            "online": True,
            "os_version": os_version,
            "uptime": uptime,
            "cpu": cpu_usage,
            "ram": ram_usage,
            "ports_summary": f"{up_count}/{len(ports)} UP",
            "ports": ports,
            "routes_count": len(route_lines),
            "arp_count": len(arp_lines),
            "mac_count": len(mac_lines),
            "routes_preview": "\n".join(route_lines[:10]) or "Không có bản ghi định tuyến",
            "arp_preview": "\n".join(arp_lines[:10]) or "Không có bản ghi ARP",
            "mac_preview": "\n".join(mac_lines[:10]) or "Không có bản ghi MAC động",
        }

    def collect_port_utilization(self, port_cfg: dict) -> dict:
        ports = self._parse_physical_interfaces()
        access_map = {
            self._normalize_iface(a["interface"]): a["vlan"]
            for a in (port_cfg.get("access_ports") or [])
        } if port_cfg else {}
        trunk_set = {
            self._normalize_iface(t)
            for t in (port_cfg.get("trunk_ports") or [])
        } if port_cfg else set()

        # Tìm thêm các cổng có học địa chỉ MAC động hoặc có đặt IP (ví dụ cổng Uplink nối Cloud0)
        mac_out = self.connection.send_command("show mac address-table dynamic")
        ip_out = self.connection.send_command("show ip interface brief")
        active_traffic_ifaces = set()

        for line in mac_out.splitlines():
            m = re.search(r"\b((?:Et|Fa|Gi|Te)\d+/\d+(?:/\d+)?)\b", line, re.IGNORECASE)
            if m:
                active_traffic_ifaces.add(self._normalize_iface(m.group(1)))

        for line in ip_out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and PHYSICAL_PORT_RE.match(parts[0]) and parts[1].lower() != "unassigned":
                active_traffic_ifaces.add(self._normalize_iface(parts[0]))

        used_ports = []
        free_ports = []
        details = []

        for p in ports:
            norm = self._normalize_iface(p["interface"])
            if norm in access_map:
                role = f"Access (VLAN {access_map[norm]})"
                is_used = True
            elif norm in trunk_set:
                role = "Trunk (802.1Q)"
                is_used = True
            elif p["status"] == "UP" and norm in active_traffic_ifaces:
                role = "Uplink / Active"
                is_used = True
            else:
                role = "Unused"
                is_used = False

            if is_used:
                used_ports.append(p["interface"])
            else:
                free_ports.append(p["interface"])

            details.append({
                "interface": p["interface"],
                "status": p["status"],
                "role": role,
                "in_use": is_used,
            })

        total = len(ports)
        used = len(used_ports)
        free = len(free_ports)
        util_pct = round((used / total) * 100, 1) if total > 0 else 0.0

        return {
            "Device": self.name,
            "IP": self.ip,
            "Device Type": self.device_type,
            "Status": "ONLINE",
            "Total Ports": total,
            "Used Ports": used,
            "Free Ports": free,
            "Utilization (%)": util_pct,
            "Access Ports": len(access_map),
            "Trunk Ports": len(trunk_set),
            "Used Port List": ", ".join(used_ports) if used_ports else "None",
            "Free Port List": ", ".join(free_ports) if free_ports else "None",
            "Details": details,
        }
import re
from core.network_device import NetworkDevice


class MikroTikDevice(NetworkDevice):
    def build_commands(self, jinja_env, vlans: list, port_cfg: dict) -> list:
        template = jinja_env.get_template("vlan.j2")
        raw = template.render(device_type="mikrotik_routeros", vlans=vlans, port_cfg=port_cfg)
        return [line for line in raw.splitlines() if line.strip()]

    def deploy(self, commands: list):
        for cmd in commands:
            if not cmd.startswith("#"):
                self.connection.send_command(cmd)

    def save_config(self) -> str:
        return "AUTO (RouterOS)"

    def get_running_config(self) -> str:
        return self.connection.send_command("/export")

    def check_compliance(self, rules: dict, port_cfg: dict) -> dict:
        report = {}
        services = self.connection.send_command("/ip service print")
        vlans_out = self.connection.send_command("/interface vlan print")

        if rules.get("require_ssh"):
            ssh_ok = any(
                "ssh" in line and not line.strip().startswith(("X", "0 X", "1 X", "2 X", "3 X", "4 X", "5 X"))
                for line in services.splitlines()
            )
            report["SSH Enabled"] = "PASS" if ssh_ok else "FAIL"

        if rules.get("forbid_telnet"):
            telnet_disabled = any("telnet" in line and "X" in line.split()[:2] for line in services.splitlines())
            report["Telnet Disabled"] = "PASS" if telnet_disabled else "FAIL"

        for vid in rules.get("required_vlans", []):
            report[f"VLAN {vid}"] = "PASS" if (f" {vid} " in vlans_out or f"vlan-id={vid}" in vlans_out) else "FAIL"

        trunk_if = port_cfg.get("trunk_ports", ["ether1"])[0] if port_cfg else "ether1"
        report["Trunk Policy"] = "PASS" if trunk_if in vlans_out else "FAIL"
        report["No Default Password"] = "FAIL" if self._password in rules.get("forbidden_passwords", []) else "PASS"
        return report

    @staticmethod
    def _to_mb(value_str: str, unit_str: str) -> float:
        val = float(value_str)
        u = unit_str.lower()
        if u.startswith("g"):
            return val * 1024.0
        if u.startswith("k"):
            return val / 1024.0
        return val

    def _parse_physical_interfaces(self) -> list:
        out = self.connection.send_command("/interface ethernet print terse")
        ports = []
        for line in out.splitlines():
            s = line.strip()
            name_match = re.search(r"name=([^\s]+)", s)
            if not name_match:
                continue
            iface = name_match.group(1)
            flag_match = re.match(r"^\d+\s+([A-Z]+)\s+name=", s)
            flags = flag_match.group(1) if flag_match else ""
            is_up = "R" in flags and "X" not in flags
            ports.append({
                "interface": iface,
                "status": "UP" if is_up else "DOWN",
                "raw_state": flags or "DOWN",
                "vlan_col": "-",
            })
        return ports

    def collect_facts(self) -> dict:
        res_out = self.connection.send_command("/system resource print")
        route_out = self.connection.send_command("/ip route print terse")
        arp_out = self.connection.send_command("/ip arp print terse")
        mac_out = self.connection.send_command("/interface bridge host print terse")

        ver_m = re.search(r"version:\s*([^\r\n]+)", res_out, re.IGNORECASE)
        up_m = re.search(r"uptime:\s*([^\r\n]+)", res_out, re.IGNORECASE)
        cpu_m = re.search(r"cpu-load:\s*([^\r\n]+)", res_out, re.IGNORECASE)
        tot_m = re.search(r"total-memory:\s*([\d.]+)\s*([KMGT]?i?B)", res_out, re.IGNORECASE)
        free_m = re.search(r"free-memory:\s*([\d.]+)\s*([KMGT]?i?B)", res_out, re.IGNORECASE)

        os_version = f"RouterOS {ver_m.group(1).strip()}" if ver_m else "MikroTik RouterOS"
        uptime = up_m.group(1).strip() if up_m else "N/A"
        cpu_usage = cpu_m.group(1).strip() if cpu_m else "N/A"

        if tot_m and free_m:
            total_mb = self._to_mb(tot_m.group(1), tot_m.group(2))
            free_mb = self._to_mb(free_m.group(1), free_m.group(2))
            used_mb = max(total_mb - free_mb, 0.0)
            pct = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
            ram_usage = f"{pct}% ({used_mb:.1f}/{total_mb:.1f} MB)"
        else:
            ram_usage = "N/A"

        ports = self._parse_physical_interfaces()
        up_count = sum(1 for p in ports if p["status"] == "UP")

        route_lines = [ln.strip() for ln in route_out.splitlines() if "dst-address=" in ln]
        arp_lines = [ln.strip() for ln in arp_out.splitlines() if re.match(r"^\d+\s+", ln.strip())]
        mac_lines = [ln.strip() for ln in mac_out.splitlines() if re.match(r"^\d+\s+", ln.strip())]

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
            "mac_preview": "\n".join(mac_lines[:10]) or "Router L3 (Không dùng Bridge MAC)",
        }

    def collect_port_utilization(self, port_cfg: dict) -> dict:
        ports = self._parse_physical_interfaces()
        trunk_set = {t.strip().lower() for t in (port_cfg.get("trunk_ports") or [])} if port_cfg else set()

        ip_out = self.connection.send_command("/ip address print terse")
        ip_ifaces = {
            m.group(1).lower()
            for m in re.finditer(r"interface=([^\s]+)", ip_out)
        }

        used_ports = []
        free_ports = []
        details = []

        for p in ports:
            iface_l = p["interface"].lower()
            if iface_l in trunk_set:
                role = "Trunk (802.1Q / Sub-if)"
                is_used = True
            elif p["status"] == "UP" and iface_l in ip_ifaces:
                role = "Active L3 Port"
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
            "Access Ports": 0,
            "Trunk Ports": len(trunk_set),
            "Used Port List": ", ".join(used_ports) if used_ports else "None",
            "Free Port List": ", ".join(free_ports) if free_ports else "None",
            "Details": details,
        }
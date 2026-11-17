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
            ssh_ok = any("ssh" in line and not line.strip().startswith(("X", "0 X", "1 X", "2 X", "3 X", "4 X", "5 X")) for line in services.splitlines())
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
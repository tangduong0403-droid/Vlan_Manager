from core.network_device import NetworkDevice


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

        # Kiểm tra đúng các cổng trunk_ports của từng switch (SW1: e0/0, e0/2; SW2: e0/0, e0/1; SW3: e0/0)
        approved = rules.get("approved_trunk_vlans", "10,20,30,40")
        expected_trunks = port_cfg.get("trunk_ports", []) if port_cfg else []
        trunks_ok = all(f"interface {t}" in run_cfg for t in expected_trunks) and ("switchport mode trunk" in run_cfg) and (f"switchport trunk allowed vlan {approved}" in run_cfg)
        report["Trunk Policy"] = "PASS" if trunks_ok else "FAIL"

        forbidden_pwds = rules.get("forbidden_passwords", [])
        weak_found = any(f"password 0 {p}" in run_cfg or f"password {p}" in run_cfg for p in forbidden_pwds)
        report["No Default Password"] = "FAIL" if weak_found else "PASS"

        return report
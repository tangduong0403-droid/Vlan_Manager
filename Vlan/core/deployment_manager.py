from datetime import datetime
from pathlib import Path
from time import perf_counter

import yaml
from jinja2 import Environment, FileSystemLoader

from core.connection_manager import ConnectionManager
from modules.backup import BackupManager
from modules.collector import DeviceCollector
from modules.compliance import ComplianceChecker
from modules.deployer import Deployer
from modules.diff import DiffManager
from modules.reporter import ReportManager
from modules.rollback import RollbackManager


class DeploymentManager:
    def __init__(self):
        self.project_dir = Path(__file__).resolve().parents[1]
        self.operation_history = []
        self.latest_facts = {}
        self.latest_port_reports = []
        self.latest_port_summary = {
            "total_ports": 0,
            "used_ports": 0,
            "free_ports": 0,
            "utilization_pct": 0.0,
        }
        self.latest_compliance = {}
        self.latest_compliance_rate = None
        self.latest_port_csv = None
        self.reload_configs()

    def reload_configs(self):
        config_dir = self.project_dir / "configs"

        inventory = self._load_yaml(config_dir / "inventory.yaml")
        vlan_config = self._load_yaml(config_dir / "vlans.yaml")
        ports_config = self._load_yaml(config_dir / "ports.yaml")
        compliance_config = self._load_yaml(config_dir / "compliance_rules.yaml")

        device_configs = inventory.get("switches")
        vlans = vlan_config.get("vlans")
        port_configs = ports_config.get("ports_config")
        rules = compliance_config.get("rules")

        if not isinstance(device_configs, list) or not device_configs:
            raise ValueError("configs/inventory.yaml must define a non-empty 'switches' list.")
        if any(
            not isinstance(config, dict)
            or not all(key in config for key in ("name", "ip", "device_type"))
            for config in device_configs
        ):
            raise ValueError("Each inventory switch must define name, ip, and device_type.")
        if not isinstance(vlans, list):
            raise ValueError("configs/vlans.yaml must define a 'vlans' list.")
        if not isinstance(port_configs, list):
            raise ValueError("configs/ports.yaml must define a 'ports_config' list.")
        if any(
            not isinstance(config, dict) or not isinstance(config.get("switch_ip"), str)
            for config in port_configs
        ):
            raise ValueError("Each port configuration must define a string 'switch_ip'.")
        if not isinstance(rules, dict):
            raise ValueError("configs/compliance_rules.yaml must define a 'rules' mapping.")

        device_names = [config["name"] for config in device_configs]
        if len(device_names) != len(set(device_names)):
            raise ValueError("Device names in configs/inventory.yaml must be unique.")

        self.devices = [ConnectionManager.create_device(config) for config in device_configs]
        self.vlans = vlans
        self.ports_by_ip = {config["switch_ip"]: config for config in port_configs}
        self.compliance_rules = rules

        template_dir = self.project_dir / "templates"
        self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        backup_dir = str(self.project_dir / "backups")
        self.backup_manager = BackupManager(self.devices, backup_dir=backup_dir)
        self.rollback_manager = RollbackManager(self.devices, backup_dir=backup_dir)
        self.diff_manager = DiffManager(self.devices, backup_dir=backup_dir)
        self.compliance_checker = ComplianceChecker(
            self.devices, self.compliance_rules, self.ports_by_ip
        )
        self.collector = DeviceCollector(self.devices, self.ports_by_ip)
        self.deployer = Deployer(
            self.devices,
            self.vlans,
            self.ports_by_ip,
            self.jinja_env,
            self.backup_manager,
            self.rollback_manager,
        )
        self.report_manager = ReportManager(
            report_dir=str(self.project_dir / "reports")
        )

        old_records = getattr(self, "_report_records", {})
        self._report_records = {}
        for device in self.devices:
            if device.name in old_records:
                rec = old_records[device.name]
                rec["IP"] = device.ip
                rec["Device Type"] = device.device_type
                self._report_records[device.name] = rec
            else:
                self._report_records[device.name] = {
                    "Device": device.name,
                    "IP": device.ip,
                    "Device Type": device.device_type,
                    "SSH Status": "NOT CHECKED",
                    "Deploy Status": "NOT RUN",
                    "Dry-run Status": "NOT RUN",
                    "Backup Status": "NOT RUN",
                    "Compliance Status": "NOT RUN",
                    "Last Operation": "N/A",
                    "Last Updated": "",
                    "Operation Duration (s)": "",
                    "Error": "",
                }

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping.")
        return data

    @staticmethod
    def _clean_error(error) -> str:
        if error is None or error == "None":
            return ""
        return str(error)

    def _record_operation(self, device_name: str, operation: str, duration: float, **updates):
        record = self._report_records[device_name]
        record.update(updates)
        record["Last Operation"] = operation
        record["Last Updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
        record["Operation Duration (s)"] = f"{duration:.3f}"

    def _add_history(self, operation: str, status: str, summary: str, duration: float):
        self.operation_history.insert(0, {
            "time": datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
            "operation": operation,
            "status": status,
            "summary": summary,
            "duration": f"{duration:.2f}s",
        })
        self.operation_history = self.operation_history[:30]

    def execute_deploy(self):
        started = perf_counter()
        results = self.deployer.deploy_concurrent()
        duration = perf_counter() - started

        ok_cnt = 0
        for result in results:
            if result["Status"] == "SUCCESS":
                ok_cnt += 1
            self._record_operation(
                result["Device"],
                "Deploy",
                duration,
                **{
                    "SSH Status": result["SSH"],
                    "Deploy Status": result["Status"],
                    "Error": self._clean_error(result["Error"]),
                },
            )
        status = "SUCCESS" if ok_cnt == len(results) else "PARTIAL"
        self._add_history("Deploy Configuration", status, f"{ok_cnt}/{len(results)} thiết bị thành công", duration)
        return results

    def execute_backup(self):
        started = perf_counter()
        results = self.backup_manager.backup_all()
        duration = perf_counter() - started

        ok_cnt = 0
        for result in results:
            if result["Status"] == "SUCCESS":
                ok_cnt += 1
            self._record_operation(
                result["Device"],
                "Backup",
                duration,
                **{
                    "Backup Status": result["Status"],
                    "Error": self._clean_error(result["Error"]),
                },
            )
        status = "SUCCESS" if ok_cnt == len(results) else "PARTIAL"
        self._add_history("Backup Configuration", status, f"{ok_cnt}/{len(results)} bản sao lưu thành công", duration)
        return results

    def execute_diff(self):
        return self.diff_manager.compare_interactive()

    def execute_rollback(self):
        return self.rollback_manager.rollback_interactive()

    def execute_dry_run(self, interactive: bool = True):
        started = perf_counter()
        confirmed = self.deployer.dry_run(interactive=interactive)
        duration = perf_counter() - started

        if not confirmed:
            for device in self.devices:
                self._record_operation(
                    device.name,
                    "Dry-run",
                    duration,
                    **{"Dry-run Status": "PREVIEWED" if not interactive else "CANCELLED"},
                )
            self._add_history("Dry-run Preview", "SUCCESS", f"Sinh lệnh mô phỏng cho {len(self.devices)} thiết bị", duration)
            return []

        results = self.execute_deploy()
        for result in results:
            self._report_records[result["Device"]]["Dry-run Status"] = "CONFIRMED"
        return results

    def execute_compliance(self):
        started = perf_counter()
        results = self.compliance_checker.check_all()
        duration = perf_counter() - started

        self.latest_compliance = results
        pass_cnt = sum(1 for r in results.values() if r.get("Overall") == "PASS")
        total = len(results)
        self.latest_compliance_rate = round((pass_cnt / total) * 100, 1) if total > 0 else 0.0

        for device_name, result in results.items():
            self._record_operation(
                device_name,
                "Compliance",
                duration,
                **{
                    "SSH Status": result["SSH"],
                    "Compliance Status": result["Overall"],
                    "Error": self._clean_error(result["Error"]),
                },
            )
        status = "PASS" if pass_cnt == total else "FAIL"
        self._add_history(
            "Compliance Checking",
            status,
            f"Đạt chuẩn {pass_cnt}/{total} ({self.latest_compliance_rate}%)",
            duration,
        )
        return results

    def execute_status(self):
        print("\n================ NETWORK DEVICE STATUS & FACTS ================")
        started = perf_counter()
        facts_list = self.collector.collect_all_facts()
        duration = perf_counter() - started

        online_cnt = 0
        for item in facts_list:
            self.latest_facts[item["device"]] = item
            is_online = item["online"]
            if is_online:
                online_cnt += 1

            ssh_status = "SUCCESS" if is_online else "FAILED"
            state_label = "ONLINE" if is_online else "OFFLINE"
            print(f"\n[{item['device']}] {item['ip']} ({item['device_type']}) -> {state_label}")
            if is_online:
                print(f"  - OS Version : {item['os_version']}")
                print(f"  - Uptime     : {item['uptime']}")
                print(f"  - CPU / RAM  : {item['cpu']}  |  RAM: {item['ram']}")
                print(f"  - Ports      : {item['ports_summary']}")
                print(
                    f"  - Tables     : Routes={item['routes_count']} | "
                    f"ARP={item['arp_count']} | MAC={item['mac_count']}"
                )
            else:
                print(f"  - SSH Error  : {item.get('error', 'Unreachable')}")

            self._record_operation(
                item["device"],
                "Status & Facts",
                duration,
                **{
                    "SSH Status": ssh_status,
                    "Error": item.get("error", ""),
                },
            )

        self.report_manager.export_device_facts(facts_list)
        print("===============================================================")
        status = "SUCCESS" if online_cnt == len(facts_list) else "PARTIAL"
        self._add_history(
            "Collect Device Facts",
            status,
            f"{online_cnt}/{len(facts_list)} thiết bị ONLINE",
            duration,
        )
        return facts_list

    def execute_port_report(self):
        print("\n=================== PORT UTILIZATION REPORT ===================")
        started = perf_counter()
        port_reports, summary = self.collector.collect_port_utilization()
        duration = perf_counter() - started

        self.latest_port_reports = port_reports
        self.latest_port_summary = summary

        print(
            f"{'Thiết bị':<8} | {'IP':<15} | {'Trạng thái':<8} | {'Tổng':>4} | "
            f"{'Dùng':>4} | {'Trống':>5} | {'Tỷ lệ':>6} | {'Cổng trống'}"
        )
        print("-" * 88)
        for r in port_reports:
            print(
                f"{r['Device']:<8} | {r['IP']:<15} | {r['Status']:<8} | "
                f"{r['Total Ports']:>4} | {r['Used Ports']:>4} | {r['Free Ports']:>5} | "
                f"{r['Utilization (%)']:>5.1f}% | {r['Free Port List']}"
            )
            self._record_operation(
                r["Device"],
                "Port Report",
                duration,
                **{
                    "SSH Status": "SUCCESS" if r["Status"] == "ONLINE" else "FAILED",
                    "Error": r.get("Error", ""),
                },
            )

        print("-" * 88)
        print(
            f"TỔNG CAMPUS: {summary['used_ports']}/{summary['total_ports']} cổng đang dùng | "
            f"Còn trống: {summary['free_ports']} cổng | Tỷ lệ sử dụng: {summary['utilization_pct']}%"
        )
        self.latest_port_csv = self.report_manager.export_port_utilization(port_reports, summary)
        print("===============================================================")

        self._add_history(
            "Port Utilization Report",
            "SUCCESS",
            f"Sử dụng {summary['used_ports']}/{summary['total_ports']} cổng ({summary['utilization_pct']}%)",
            duration,
        )
        return port_reports, summary

    def execute_report(self):
        records = [record.copy() for record in self._report_records.values()]
        summary_path = self.report_manager.export_summary(records)
        if not self.latest_port_reports:
            self.execute_port_report()
        else:
            self.latest_port_csv = self.report_manager.export_port_utilization(
                self.latest_port_reports, self.latest_port_summary
            )
        return summary_path

    def get_dashboard_snapshot(self) -> dict:
        device_states = []
        online_count = 0
        for dev in self.devices:
            facts = self.latest_facts.get(dev.name)
            rec = self._report_records.get(dev.name, {})
            if facts:
                is_online = facts.get("online", False)
            else:
                is_online = rec.get("SSH Status") == "SUCCESS"
            if is_online:
                online_count += 1
            device_states.append({
                "name": dev.name,
                "ip": dev.ip,
                "device_type": dev.device_type,
                "online": is_online,
                "checked": (facts is not None) or (rec.get("SSH Status") != "NOT CHECKED"),
                "compliance": rec.get("Compliance Status", "NOT RUN"),
                "facts": facts,
            })

        return {
            "total_devices": len(self.devices),
            "online_devices": online_count,
            "offline_devices": len(self.devices) - online_count,
            "compliance_rate": self.latest_compliance_rate,
            "port_summary": self.latest_port_summary,
            "port_reports": self.latest_port_reports,
            "device_states": device_states,
            "operation_history": self.operation_history,
            "latest_port_csv": self.latest_port_csv,
        }
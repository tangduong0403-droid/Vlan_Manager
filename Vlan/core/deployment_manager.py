from datetime import datetime
from pathlib import Path
from time import perf_counter

import yaml
from jinja2 import Environment, FileSystemLoader

from core.connection_manager import ConnectionManager
from modules.backup import BackupManager
from modules.compliance import ComplianceChecker
from modules.deployer import Deployer
from modules.diff import DiffManager
from modules.reporter import ReportManager
from modules.rollback import RollbackManager


class DeploymentManager:
    def __init__(self):
        self.project_dir = Path(__file__).resolve().parents[1]
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

        self._report_records = {
            device.name: {
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
            for device in self.devices
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

    def execute_deploy(self):
        started = perf_counter()
        results = self.deployer.deploy_concurrent()
        duration = perf_counter() - started

        for result in results:
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
        return results

    def execute_backup(self):
        started = perf_counter()
        results = self.backup_manager.backup_all()
        duration = perf_counter() - started

        for result in results:
            self._record_operation(
                result["Device"],
                "Backup",
                duration,
                **{
                    "Backup Status": result["Status"],
                    "Error": self._clean_error(result["Error"]),
                },
            )
        return results

    def execute_diff(self):
        return self.diff_manager.compare_interactive()

    def execute_rollback(self):
        return self.rollback_manager.rollback_interactive()

    def execute_dry_run(self):
        started = perf_counter()
        confirmed = self.deployer.dry_run()
        duration = perf_counter() - started

        if not confirmed:
            for device in self.devices:
                self._record_operation(
                    device.name,
                    "Dry-run",
                    duration,
                    **{"Dry-run Status": "CANCELLED"},
                )
            return []

        results = self.execute_deploy()
        for result in results:
            self._report_records[result["Device"]]["Dry-run Status"] = "CONFIRMED"
        return results

    def execute_compliance(self):
        started = perf_counter()
        results = self.compliance_checker.check_all()
        duration = perf_counter() - started

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
        return results

    def execute_status(self):
        print("\n========== NETWORK DEVICE STATUS ==========")
        started = perf_counter()
        statuses = []

        for device in self.devices:
            ok, error = ConnectionManager.connect_with_retry(device)
            status = "SUCCESS" if ok else "FAILED"
            statuses.append(
                {
                    "Device": device.name,
                    "IP": device.ip,
                    "Device Type": device.device_type,
                    "SSH": status,
                    "Error": "" if ok else error,
                }
            )
            print(
                f"[{device.name}] {device.ip} ({device.device_type}) "
                f"SSH: {status}"
                + (f" ({error})" if not ok else "")
            )
            if ok:
                ConnectionManager.disconnect(device)

        duration = perf_counter() - started
        for result in statuses:
            self._record_operation(
                result["Device"],
                "Status",
                duration,
                **{
                    "SSH Status": result["SSH"],
                    "Error": result["Error"],
                },
            )
        print("============================================")
        return statuses

    def execute_report(self):
        records = [record.copy() for record in self._report_records.values()]
        return self.report_manager.export_summary(records)

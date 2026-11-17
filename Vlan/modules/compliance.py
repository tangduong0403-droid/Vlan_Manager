from core.connection_manager import ConnectionManager


class ComplianceChecker:
    def __init__(self, devices: list, rules: dict, ports_by_ip: dict):
        self.devices = devices
        self.rules = rules
        self.ports_by_ip = ports_by_ip

    def check_all(self) -> dict:
        print("\n========== COMPLIANCE CHECKING ==========")
        print(f"{'Thiết bị':<10} | {'Tiêu chí':<22} | {'Kết quả':<10}")
        print("-" * 48)

        summary = {}
        violations = []

        for dev in self.devices:
            ok, err = ConnectionManager.connect_with_retry(dev)
            if not ok:
                print(f"{dev.name:<10} | {'SSH Connection':<22} | {'FAIL':<10}")
                summary[dev.name] = {"SSH": "FAILED", "Overall": "FAIL (Unreachable)", "Error": err}
                violations.append(f"{dev.name}: Không thể kết nối SSH để kiểm tra")
                continue

            try:
                port_cfg = self.ports_by_ip.get(dev.ip, {})
                checks = dev.check_compliance(self.rules, port_cfg)
                all_pass = True
                for criterion, status in checks.items():
                    print(f"{dev.name:<10} | {criterion:<22} | {status:<10}")
                    if status == "FAIL":
                        all_pass = False
                        violations.append(f"{dev.name} vi phạm tiêu chuẩn: {criterion}")
                summary[dev.name] = {
                    "SSH": "SUCCESS",
                    "Overall": "PASS" if all_pass else "FAIL",
                    "Error": "None"
                }
            except Exception as e:
                summary[dev.name] = {"SSH": "SUCCESS", "Overall": "ERROR", "Error": str(e)}
            finally:
                ConnectionManager.disconnect(dev)
            print("-" * 48)

        if not violations:
            print("Tổng kết: Toàn bộ hệ thống ĐẠT chuẩn Compliance!")
        else:
            print("Báo cáo vi phạm phát hiện được:")
            for v in violations:
                print(f" - {v}")
        print("=========================================")
        return summary
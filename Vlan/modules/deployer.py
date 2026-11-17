from concurrent.futures import ThreadPoolExecutor, as_completed
from core.connection_manager import ConnectionManager


class Deployer:
    def __init__(self, devices: list, vlans: list, ports_by_ip: dict, jinja_env, backup_mgr, rollback_mgr):
        self.devices = devices
        self.vlans = vlans
        self.ports_by_ip = ports_by_ip
        self.jinja_env = jinja_env
        self.backup_mgr = backup_mgr
        self.rollback_mgr = rollback_mgr

    def _deploy_single(self, dev) -> dict:
        logs = [f"[{dev.name} - {dev.ip}]"]
        result = {"Device": dev.name, "SSH": "FAILED", "Status": "FAILED", "Error": "None", "Logs": logs}

        ok, err = ConnectionManager.connect_with_retry(dev)
        if not ok:
            logs.append(f"SSH Connection: FAILED ({err})")
            result["Error"] = err
            return result

        logs.append("SSH Connection: SUCCESS")
        result["SSH"] = "SUCCESS"

        pre_backup_path = self.backup_mgr.backup_single_connected(dev, tag="pre_deploy")

        try:
            port_cfg = self.ports_by_ip.get(dev.ip, {})
            commands = dev.build_commands(self.jinja_env, self.vlans, port_cfg)
            dev.deploy(commands)
            for v in self.vlans:
                logs.append(f"Deploy VLAN {v['vlan_id']} ({v['name']}): SUCCESS")
            save_msg = dev.save_config()
            logs.append(f"Save Configuration: {save_msg}")
            result["Status"] = "SUCCESS"
        except Exception as e:
            err_msg = str(e)
            logs.append(f"Deploy Error: FAILED ({err_msg})")
            result["Error"] = err_msg
            if pre_backup_path:
                logs.append("Triggering Auto-Rollback to pre-deploy snapshot...")
                rb_ok = self.rollback_mgr.rollback_connected(dev, pre_backup_path)
                logs.append("Auto-Rollback: SUCCESS" if rb_ok else "Auto-Rollback: FAILED")
        finally:
            ConnectionManager.disconnect(dev)

        return result

    def deploy_concurrent(self) -> list:
        print("\n========== CONCURRENT DEPLOY CONFIGURATION ==========")
        results = []
        with ThreadPoolExecutor(max_workers=len(self.devices)) as executor:
            future_map = {executor.submit(self._deploy_single, dev): dev for dev in self.devices}
            for future in as_completed(future_map):
                res = future.result()
                for line in res["Logs"]:
                    print(line)
                print()
                results.append(res)

        success_cnt = sum(1 for r in results if r["Status"] == "SUCCESS")
        failed_cnt = len(results) - success_cnt
        print("======================================================")
        print(f"Total Devices: {len(results)} | Successful: {success_cnt} | Failed: {failed_cnt}")
        print("======================================================")
        return results

    def dry_run(self) -> bool:
        print("\n========== DRY-RUN MODE (PREVIEW COMMANDS) ==========")
        for dev in self.devices:
            print(f"Device: {dev.name} ({dev.ip}) [{dev.device_type}]")
            print("Planned commands:")
            port_cfg = self.ports_by_ip.get(dev.ip, {})
            commands = dev.build_commands(self.jinja_env, self.vlans, port_cfg)
            for cmd in commands:
                print(f"  {cmd}")
            print("-" * 45)
        print("DRY-RUN COMPLETED. No configuration was applied.")
        ans = input("Bạn có muốn triển khai thật các lệnh này ngay bây giờ không? (y/n): ").strip().lower()
        return ans == "y"
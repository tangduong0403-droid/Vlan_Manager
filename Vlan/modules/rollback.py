import os
from core.connection_manager import ConnectionManager


class RollbackManager:
    def __init__(self, devices: list, backup_dir: str = "backups"):
        self.devices = devices
        self.backup_dir = backup_dir

    def _parse_commands(self, filepath: str) -> list:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        cmds = []
        for line in lines:
            s = line.rstrip()
            if not s or s.startswith(("!", "#", "Building configuration", "Current configuration", "version ")) or s == "end":
                continue
            cmds.append(s)
        return cmds

    def rollback_connected(self, dev, filepath: str) -> bool:
        try:
            commands = self._parse_commands(filepath)
            dev.deploy(commands)
            dev.save_config()
            return True
        except Exception:
            return False

    def rollback_interactive(self):
        print("\n========== ROLLBACK CONFIGURATION ==========")
        for idx, dev in enumerate(self.devices, 1):
            print(f"[{idx}] {dev.name} ({dev.ip})")
        choice = input("Chọn thiết bị cần khôi phục: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(self.devices)):
            print("Lựa chọn không hợp lệ.")
            return

        dev = self.devices[int(choice) - 1]
        dev_folder = os.path.join(self.backup_dir, dev.name)
        files = sorted([f for f in os.listdir(dev_folder) if f.endswith(".cfg")]) if os.path.exists(dev_folder) else []
        if not files:
            print(f"Không tìm thấy bản backup nào cho {dev.name}.")
            return

        print(f"\nDevice: {dev.name}")
        print("Available backups:")
        for idx, f in enumerate(files, 1):
            print(f"[{idx}] {f}")

        try:
            f_idx = int(input("Select backup: ").strip()) - 1
            filepath = os.path.join(dev_folder, files[f_idx])
        except (ValueError, IndexError):
            print("Lựa chọn file không hợp lệ.")
            return

        if input("Confirm rollback? (y/n): ").strip().lower() != "y":
            print("Đã hủy thao tác Rollback.")
            return

        print("Restoring configuration...")
        ok, err = ConnectionManager.connect_with_retry(dev)
        if not ok:
            print(f"Rollback: FAILED (SSH Error: {err})")
            return

        success = self.rollback_connected(dev, filepath)
        ConnectionManager.disconnect(dev)
        print("Rollback: SUCCESS" if success else "Rollback: FAILED")
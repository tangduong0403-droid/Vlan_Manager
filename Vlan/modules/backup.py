import os
from datetime import datetime
from core.connection_manager import ConnectionManager


class BackupManager:
    def __init__(self, devices: list, backup_dir: str = "backups"):
        self.devices = devices
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)

    def backup_single_connected(self, dev, tag: str = "") -> str | None:
        try:
            dev_folder = os.path.join(self.backup_dir, dev.name)
            os.makedirs(dev_folder, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            suffix = f"_{tag}" if tag else ""
            filename = f"{ts}{suffix}.cfg"
            filepath = os.path.join(dev_folder, filename)

            cfg_text = dev.get_running_config()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(cfg_text)
            return filepath
        except Exception:
            return None

    def backup_all(self) -> list:
        print("\n========== BACKUP CONFIGURATION ==========")
        records = []
        for dev in self.devices:
            ok, err = ConnectionManager.connect_with_retry(dev)
            if not ok:
                print(f"[{dev.name}] Backup FAILED (SSH Error: {err})")
                records.append({"Device": dev.name, "Status": "FAILED", "File": "N/A", "Error": err})
                continue

            filepath = self.backup_single_connected(dev)
            ConnectionManager.disconnect(dev)

            if filepath:
                fname = os.path.basename(filepath)
                print(f"[{dev.name}] Backup SUCCESS -> {filepath}")
                records.append({"Device": dev.name, "Status": "SUCCESS", "File": fname, "Error": "None"})
            else:
                print(f"[{dev.name}] Backup FAILED (Lỗi đọc/ghi cấu hình)")
                records.append({"Device": dev.name, "Status": "FAILED", "File": "N/A", "Error": "Read/Write error"})
        print("==========================================")
        return records
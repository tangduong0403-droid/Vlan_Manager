import os
import difflib


class DiffManager:
    def __init__(self, devices: list, backup_dir: str = "backups"):
        self.devices = devices
        self.backup_dir = backup_dir

    def compare_interactive(self):
        print("\n========== COMPARE CONFIGURATION (DIFF) ==========")
        for idx, dev in enumerate(self.devices, 1):
            print(f"[{idx}] {dev.name} ({dev.ip})")
        choice = input("Chọn thiết bị: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(self.devices)):
            print("Lựa chọn không hợp lệ.")
            return

        dev = self.devices[int(choice) - 1]
        dev_folder = os.path.join(self.backup_dir, dev.name)
        if not os.path.exists(dev_folder):
            print(f"Chưa có thư mục backup cho {dev.name}.")
            return

        files = sorted([f for f in os.listdir(dev_folder) if f.endswith(".cfg")])
        if len(files) < 2:
            print(f"Cần ít nhất 2 file backup để so sánh (hiện có {len(files)}).")
            return

        print(f"\nDanh sách bản backup của {dev.name}:")
        for idx, f in enumerate(files, 1):
            print(f"[{idx}] {f}")

        try:
            i1 = int(input("Chọn bản backup cũ (1): ").strip()) - 1
            i2 = int(input("Chọn bản backup mới (2): ").strip()) - 1
            p1 = os.path.join(dev_folder, files[i1])
            p2 = os.path.join(dev_folder, files[i2])
        except (ValueError, IndexError):
            print("Lựa chọn file không hợp lệ.")
            return

        with open(p1, "r", encoding="utf-8") as f1, open(p2, "r", encoding="utf-8") as f2:
            diff_lines = list(difflib.unified_diff(f1.readlines(), f2.readlines(), fromfile=files[i1], tofile=files[i2], n=2))

        print(f"\n--- Kết quả Diff ({files[i1]} -> {files[i2]}) ---")
        if not diff_lines:
            print("Hai bản cấu hình hoàn toàn giống nhau.")
        else:
            for line in diff_lines:
                print(line.rstrip())
        print("==================================================")
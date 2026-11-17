import os
import csv
from datetime import datetime


class ReportManager:
    def __init__(self, report_dir: str = "reports"):
        self.report_dir = report_dir
        os.makedirs(self.report_dir, exist_ok=True)

    def export_summary(self, records: list):
        print("\n========== EXPORT SUMMARY REPORT ==========")
        if not records:
            print("Chưa có dữ liệu để xuất báo cáo.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.report_dir, f"network_automation_report_{timestamp}.csv")
        fieldnames = list(records[0].keys())

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        print(f"Đã xuất báo cáo tổng hợp thành công: {filepath}")
        print("===========================================")
import os
import csv
from datetime import datetime


class ReportManager:
    def __init__(self, report_dir: str = "reports"):
        self.report_dir = report_dir
        os.makedirs(self.report_dir, exist_ok=True)

    def export_summary(self, records: list) -> str | None:
        print("\n========== EXPORT SUMMARY REPORT ==========")
        if not records:
            print("Chưa có dữ liệu để xuất báo cáo.")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.report_dir, f"network_automation_report_{timestamp}.csv")
        fieldnames = list(records[0].keys())

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        print(f"Đã xuất báo cáo tổng hợp tác vụ: {filepath}")
        print("===========================================")
        return filepath

    def export_port_utilization(self, port_reports: list, campus_summary: dict) -> str | None:
        if not port_reports:
            print("Chưa có dữ liệu sử dụng cổng để xuất báo cáo.")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.report_dir, f"port_utilization_report_{timestamp}.csv")
        fieldnames = [
            "Device",
            "IP",
            "Device Type",
            "Status",
            "Total Ports",
            "Used Ports",
            "Free Ports",
            "Utilization (%)",
            "Access Ports",
            "Trunk Ports",
            "Used Port List",
            "Free Port List",
            "Collected At",
            "Error",
        ]

        rows = [{k: item.get(k, "") for k in fieldnames} for item in port_reports]
        rows.append({
            "Device": "TOTAL (CAMPUS)",
            "IP": "-",
            "Device Type": "Multi-Vendor",
            "Status": f"{sum(1 for r in port_reports if r['Status'] == 'ONLINE')}/{len(port_reports)} ONLINE",
            "Total Ports": campus_summary.get("total_ports", 0),
            "Used Ports": campus_summary.get("used_ports", 0),
            "Free Ports": campus_summary.get("free_ports", 0),
            "Utilization (%)": campus_summary.get("utilization_pct", 0.0),
            "Access Ports": sum(r.get("Access Ports", 0) for r in port_reports),
            "Trunk Ports": sum(r.get("Trunk Ports", 0) for r in port_reports),
            "Used Port List": "-",
            "Free Port List": "-",
            "Collected At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Error": "",
        })

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        print(f"[REPORTER] Đã xuất báo cáo sử dụng cổng (CSV): {filepath}")
        return filepath

    def export_device_facts(self, facts_list: list) -> str | None:
        if not facts_list:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(self.report_dir, f"device_facts_{timestamp}.csv")
        fieldnames = [
            "Device",
            "IP",
            "Device Type",
            "Online",
            "OS Version",
            "Uptime",
            "CPU",
            "RAM",
            "Ports Summary",
            "Routes Count",
            "ARP Entries",
            "MAC Entries",
            "Collected At",
            "Error",
        ]

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in facts_list:
                writer.writerow({
                    "Device": item.get("device"),
                    "IP": item.get("ip"),
                    "Device Type": item.get("device_type"),
                    "Online": "ONLINE" if item.get("online") else "OFFLINE",
                    "OS Version": item.get("os_version"),
                    "Uptime": item.get("uptime"),
                    "CPU": item.get("cpu"),
                    "RAM": item.get("ram"),
                    "Ports Summary": item.get("ports_summary"),
                    "Routes Count": item.get("routes_count"),
                    "ARP Entries": item.get("arp_count"),
                    "MAC Entries": item.get("mac_count"),
                    "Collected At": item.get("collected_at"),
                    "Error": item.get("error", ""),
                })

        print(f"[REPORTER] Đã xuất bảng thông tin thiết bị (CSV): {filepath}")
        return filepath
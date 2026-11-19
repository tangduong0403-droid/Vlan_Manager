from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from core.connection_manager import ConnectionManager


class DeviceCollector:
    def __init__(self, devices: list, ports_by_ip: dict):
        self.devices = devices
        self.ports_by_ip = ports_by_ip

    def _collect_facts_single(self, dev) -> dict:
        ok, err = ConnectionManager.connect_with_retry(dev)
        if not ok:
            return {
                "device": dev.name,
                "ip": dev.ip,
                "device_type": dev.device_type,
                "online": False,
                "os_version": "N/A",
                "uptime": "N/A",
                "cpu": "N/A",
                "ram": "N/A",
                "ports_summary": "0/0 UP",
                "ports": [],
                "routes_count": 0,
                "arp_count": 0,
                "mac_count": 0,
                "routes_preview": "",
                "arp_preview": "",
                "mac_preview": "",
                "error": err,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        try:
            facts = dev.collect_facts()
            facts["error"] = ""
            facts["collected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return facts
        except Exception as e:
            return {
                "device": dev.name,
                "ip": dev.ip,
                "device_type": dev.device_type,
                "online": True,
                "os_version": "Error",
                "uptime": "N/A",
                "cpu": "N/A",
                "ram": "N/A",
                "ports_summary": "N/A",
                "ports": [],
                "routes_count": 0,
                "arp_count": 0,
                "mac_count": 0,
                "routes_preview": "",
                "arp_preview": "",
                "mac_preview": "",
                "error": str(e),
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        finally:
            ConnectionManager.disconnect(dev)

    def _collect_ports_single(self, dev) -> dict:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ok, err = ConnectionManager.connect_with_retry(dev)
        if not ok:
            return {
                "Device": dev.name,
                "IP": dev.ip,
                "Device Type": dev.device_type,
                "Status": "OFFLINE",
                "Total Ports": 0,
                "Used Ports": 0,
                "Free Ports": 0,
                "Utilization (%)": 0.0,
                "Access Ports": 0,
                "Trunk Ports": 0,
                "Used Port List": "N/A",
                "Free Port List": "N/A",
                "Details": [],
                "Error": err,
                "Collected At": ts,
            }
        try:
            port_cfg = self.ports_by_ip.get(dev.ip, {})
            report = dev.collect_port_utilization(port_cfg)
            report["Error"] = ""
            report["Collected At"] = ts
            return report
        except Exception as e:
            return {
                "Device": dev.name,
                "IP": dev.ip,
                "Device Type": dev.device_type,
                "Status": "ERROR",
                "Total Ports": 0,
                "Used Ports": 0,
                "Free Ports": 0,
                "Utilization (%)": 0.0,
                "Access Ports": 0,
                "Trunk Ports": 0,
                "Used Port List": "N/A",
                "Free Port List": "N/A",
                "Details": [],
                "Error": str(e),
                "Collected At": ts,
            }
        finally:
            ConnectionManager.disconnect(dev)

    def collect_all_facts(self) -> list:
        order = {d.name: idx for idx, d in enumerate(self.devices)}
        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.devices))) as executor:
            futures = [executor.submit(self._collect_facts_single, dev) for dev in self.devices]
            for fut in as_completed(futures):
                results.append(fut.result())
        results.sort(key=lambda x: order.get(x["device"], 999))
        return results

    def collect_port_utilization(self) -> tuple[list, dict]:
        order = {d.name: idx for idx, d in enumerate(self.devices)}
        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.devices))) as executor:
            futures = [executor.submit(self._collect_ports_single, dev) for dev in self.devices]
            for fut in as_completed(futures):
                results.append(fut.result())
        results.sort(key=lambda x: order.get(x["Device"], 999))

        total_ports = sum(r["Total Ports"] for r in results)
        used_ports = sum(r["Used Ports"] for r in results)
        free_ports = sum(r["Free Ports"] for r in results)
        overall_pct = round((used_ports / total_ports) * 100, 1) if total_ports > 0 else 0.0

        summary = {
            "total_ports": total_ports,
            "used_ports": used_ports,
            "free_ports": free_ports,
            "utilization_pct": overall_pct,
        }
        return results, summary
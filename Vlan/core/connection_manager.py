import os
import time
from netmiko import ConnectHandler
from devices.cisco_ios import CiscoIOSDevice
from devices.mikrotik import MikroTikDevice


class ConnectionManager:
    @staticmethod
    def create_device(dev_cfg: dict):
        prefix = dev_cfg.get("env_prefix", dev_cfg["name"].upper())
        username = os.getenv(f"{prefix}_USERNAME", dev_cfg.get("username", "admin"))
        password = os.getenv(f"{prefix}_PASSWORD", dev_cfg.get("password", "admin123"))
        secret = os.getenv(f"{prefix}_SECRET", "")

        dtype = dev_cfg["device_type"].lower()
        if dtype == "cisco_ios":
            return CiscoIOSDevice(
                name=dev_cfg["name"],
                ip=dev_cfg["ip"],
                device_type=dtype,
                username=username,
                password=password,
                secret=secret
            )
        elif dtype == "mikrotik_routeros":
            return MikroTikDevice(
                name=dev_cfg["name"],
                ip=dev_cfg["ip"],
                device_type=dtype,
                username=username,
                password=password,
                secret=secret
            )
        raise ValueError(f"Chưa hỗ trợ device_type: {dtype}")

    @staticmethod
    def connect_with_retry(device, retries: int = 2, delay: int = 2) -> tuple[bool, str]:
        last_err = ""
        for attempt in range(1, retries + 1):
            try:
                conn = ConnectHandler(**device.get_connection_params())
                if device.device_type == "cisco_ios" and device.secret:
                    conn.enable()
                device.connection = conn
                return True, "SUCCESS"
            except Exception as e:
                last_err = str(e)
                if attempt < retries:
                    time.sleep(delay)
        device.connection = None
        return False, last_err

    @staticmethod
    def disconnect(device):
        if device.connection:
            try:
                device.connection.disconnect()
            except Exception:
                pass
            finally:
                device.connection = None
import os
import time
import logging
import paramiko
from netmiko import ConnectHandler
from devices.cisco_ios import CiscoIOSDevice
from devices.mikrotik import MikroTikDevice

logging.getLogger("paramiko").setLevel(logging.CRITICAL)

paramiko.Transport._preferred_kex = tuple(
    dict.fromkeys(
        paramiko.Transport._preferred_kex
        + (
            "diffie-hellman-group14-sha1",
            "diffie-hellman-group-exchange-sha1",
            "diffie-hellman-group1-sha1",
        )
    )
)


class ConnectionManager:
    @staticmethod
    def create_device(dev_cfg: dict):
        prefix = dev_cfg.get("env_prefix", dev_cfg["name"].upper()).strip()
        username = (
            os.getenv(f"{prefix}_USERNAME")
            or os.getenv(f"{prefix}_USER")
            or ""
        ).strip()
        password = (
            os.getenv(f"{prefix}_PASSWORD")
            or os.getenv(f"{prefix}_PASS")
            or ""
        ).strip()
        secret = (os.getenv(f"{prefix}_SECRET") or password).strip()

        missing_vars = []
        if not username:
            missing_vars.append(f"{prefix}_USERNAME")
        if not password:
            missing_vars.append(f"{prefix}_PASSWORD")

        if missing_vars:
            raise ValueError(
                f"Thiếu biến môi trường xác thực cho thiết bị '{dev_cfg['name']}': "
                f"{', '.join(missing_vars)}. Vui lòng khai báo trong tệp .env."
            )

        dtype = dev_cfg["device_type"].lower()
        if dtype == "cisco_ios":
            return CiscoIOSDevice(
                name=dev_cfg["name"],
                ip=dev_cfg["ip"],
                device_type=dtype,
                username=username,
                password=password,
                secret=secret,
            )
        elif dtype == "mikrotik_routeros":
            return MikroTikDevice(
                name=dev_cfg["name"],
                ip=dev_cfg["ip"],
                device_type=dtype,
                username=username,
                password=password,
                secret=secret,
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
                last_err = str(e).splitlines()[0] if str(e) else "Unknown SSH Error"
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
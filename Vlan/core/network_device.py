from abc import ABC, abstractmethod


class NetworkDevice(ABC):
    def __init__(self, name: str, ip: str, device_type: str, username: str, password: str, secret: str = ""):
        self._name = name
        self._ip = ip
        self._device_type = device_type
        self._username = username
        self._password = password
        self._secret = secret
        self._connection = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def device_type(self) -> str:
        return self._device_type

    @property
    def vendor(self) -> str:
        return "cisco" if "cisco" in self._device_type else "mikrotik"

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str):
        if not value or not value.strip():
            raise ValueError("Username không được để trống.")
        self._username = value.strip()

    @property
    def password(self) -> str:
        return "******"

    @password.setter
    def password(self, value: str):
        if value is None:
            raise ValueError("Password không hợp lệ.")
        self._password = value

    @property
    def secret(self) -> str:
        return "******" if self._secret else ""

    @secret.setter
    def secret(self, value: str):
        self._secret = value or ""

    @property
    def connection(self):
        return self._connection

    @connection.setter
    def connection(self, conn):
        self._connection = conn

    def get_connection_params(self) -> dict:
        params = {
            "device_type": self._device_type,
            "host": self._ip,
            "username": self._username,
            "password": self._password,
            "timeout": 10,
            "conn_timeout": 10,
        }
        if self._secret:
            params["secret"] = self._secret
        return params

    @abstractmethod
    def build_commands(self, jinja_env, vlans: list, port_cfg: dict) -> list:
        pass

    @abstractmethod
    def deploy(self, commands: list):
        pass

    @abstractmethod
    def save_config(self) -> str:
        pass

    @abstractmethod
    def get_running_config(self) -> str:
        pass

    @abstractmethod
    def check_compliance(self, rules: dict, port_cfg: dict) -> dict:
        pass
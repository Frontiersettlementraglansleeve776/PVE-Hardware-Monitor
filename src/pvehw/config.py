"""Configuration management for PVE Hardware Monitor."""
import os
import json
from dataclasses import dataclass, asdict, field
from typing import Optional, List
from pathlib import Path


DEFAULT_CONFIG_DIR = Path("/opt/pve-hwmonitor")
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_PORT = 9099
DEFAULT_CERT_FILE = DEFAULT_CONFIG_DIR / "cert.pem"
DEFAULT_KEY_FILE = DEFAULT_CONFIG_DIR / "key.pem"


@dataclass
class TLSConfig:
    enabled: bool = False
    cert_file: str = str(DEFAULT_CERT_FILE)
    key_file: str = str(DEFAULT_KEY_FILE)
    auto_generate: bool = True


@dataclass
class SecurityConfig:
    token: Optional[str] = None
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    rate_limit: int = 10
    rate_window: float = 1.0
    audit_log: bool = False
    audit_file: str = str(DEFAULT_CONFIG_DIR / "audit.log")


@dataclass
class APIConfig:
    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"
    tls: TLSConfig = field(default_factory=TLSConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


@dataclass
class SensorPaths:
    ec_path: str = "/sys/kernel/debug/ec/ec0/io"
    boost_path: Optional[str] = None
    bat_path: Optional[str] = None
    hw_coretemp: Optional[str] = None
    hw_nvme: Optional[str] = None
    hw_pch: Optional[str] = None


@dataclass
class SensorConfig:
    has_ec: bool = False
    ec_fan_regs: list = field(default_factory=list)
    has_boost: bool = False
    has_ipmi: bool = False
    ipmi_interface: str = "open"
    ipmi_has_fans: bool = False
    ipmi_has_temps: bool = False
    ipmi_has_power: bool = False
    ipmi_has_psu: bool = False
    ipmi_has_voltage: bool = False
    paths: SensorPaths = field(default_factory=SensorPaths)


@dataclass
class Thresholds:
    cpu_warn: float = 80.0
    cpu_crit: float = 90.0
    nvme_warn: float = 55.0
    nvme_crit: float = 70.0
    battery_warn: float = 20.0
    battery_crit: float = 10.0
    fan_min_rpm: int = 500


@dataclass
class AlertConfig:
    enabled: bool = True
    thresholds: Thresholds = field(default_factory=Thresholds)


@dataclass
class NodeConfig:
    name: str = "local"
    host: str = "localhost"
    port: int = 9099
    token: Optional[str] = None
    enabled: bool = True


@dataclass
class ClusterConfig:
    enabled: bool = False
    poll_interval: float = 3.0
    nodes: list[NodeConfig] = field(default_factory=list)


@dataclass
class CacheConfig:
    ipmi_cache_ttl: float = 2.0
    ipmi_cache_file: str = str(DEFAULT_CONFIG_DIR / "ipmi_cache.json")


@dataclass
class HistoryConfig:
    enabled: bool = True
    max_points: int = 100
    retention_minutes: int = 60


@dataclass
class AppConfig:
    api: APIConfig = field(default_factory=APIConfig)
    sensor: SensorConfig = field(default_factory=SensorConfig)
    alert: AlertConfig = field(default_factory=AlertConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    system_model: str = ""
    bios_ver: str = ""
    sdr_cache: str = str(DEFAULT_CONFIG_DIR / "sdr.cache")


def _default_config() -> AppConfig:
    config = AppConfig()
    config.api.security.token = os.environ.get("PVE_HWM_TOKEN")
    return config


def load_config(path: Optional[Path] = None) -> AppConfig:
    path = path or DEFAULT_CONFIG_FILE
    if not path.exists():
        return _default_config()
    try:
        with open(path) as f:
            data = json.load(f)
        return _dict_to_config(data)
    except (json.JSONDecodeError, KeyError):
        return _default_config()


def _dict_to_config(data: dict) -> AppConfig:
    config = AppConfig()
    if "api" in data:
        api_data = data["api"]
        config.api.port = api_data.get("port", DEFAULT_PORT)
        config.api.host = api_data.get("host", "0.0.0.0")
        if "tls" in api_data:
            config.api.tls.enabled = api_data["tls"].get("enabled", False)
            config.api.tls.cert_file = api_data["tls"].get("cert_file", str(DEFAULT_CERT_FILE))
            config.api.tls.key_file = api_data["tls"].get("key_file", str(DEFAULT_KEY_FILE))
        if "security" in api_data:
            sec = api_data["security"]
            config.api.security.token = sec.get("token")
            config.api.security.cors_origins = sec.get("cors_origins", ["*"])
            config.api.security.rate_limit = sec.get("rate_limit", 10)
            config.api.security.rate_window = sec.get("rate_window", 1.0)
            config.api.security.audit_log = sec.get("audit_log", False)
    if "sensor" in data:
        sen = data["sensor"]
        config.sensor.has_ec = sen.get("has_ec", False)
        config.sensor.ec_fan_regs = sen.get("ec_fan_regs", [])
        config.sensor.has_boost = sen.get("has_boost", False)
        config.sensor.has_ipmi = sen.get("has_ipmi", False)
        config.sensor.ipmi_interface = sen.get("ipmi_interface", "open")
        config.sensor.ipmi_has_fans = sen.get("ipmi_has_fans", False)
        config.sensor.ipmi_has_temps = sen.get("ipmi_has_temps", False)
        config.sensor.ipmi_has_power = sen.get("ipmi_has_power", False)
        config.sensor.ipmi_has_psu = sen.get("ipmi_has_psu", False)
        config.sensor.ipmi_has_voltage = sen.get("ipmi_has_voltage", False)
        if "paths" in sen:
            config.sensor.paths.ec_path = sen["paths"].get("ec_path", "/sys/kernel/debug/ec/ec0/io")
            config.sensor.paths.boost_path = sen["paths"].get("boost_path")
            config.sensor.paths.bat_path = sen["paths"].get("bat_path")
            config.sensor.paths.hw_coretemp = sen["paths"].get("hw_coretemp")
            config.sensor.paths.hw_nvme = sen["paths"].get("hw_nvme")
            config.sensor.paths.hw_pch = sen["paths"].get("hw_pch")
    if "alert" in data:
        alert = data["alert"]
        config.alert.enabled = alert.get("enabled", True)
        if "thresholds" in alert:
            t = alert["thresholds"]
            config.alert.thresholds.cpu_warn = t.get("cpu_warn", 80.0)
            config.alert.thresholds.cpu_crit = t.get("cpu_crit", 90.0)
            config.alert.thresholds.nvme_warn = t.get("nvme_warn", 55.0)
            config.alert.thresholds.nvme_crit = t.get("nvme_crit", 70.0)
            config.alert.thresholds.battery_warn = t.get("battery_warn", 20.0)
            config.alert.thresholds.battery_crit = t.get("battery_crit", 10.0)
            config.alert.thresholds.fan_min_rpm = t.get("fan_min_rpm", 500)
    if "cluster" in data:
        cl = data["cluster"]
        config.cluster.enabled = cl.get("enabled", False)
        config.cluster.poll_interval = cl.get("poll_interval", 3.0)
        config.cluster.nodes = [NodeConfig(**n) for n in cl.get("nodes", [])]
    if "cache" in data:
        c = data["cache"]
        config.cache.ipmi_cache_ttl = c.get("ipmi_cache_ttl", 2.0)
        config.cache.ipmi_cache_file = c.get("ipmi_cache_file", str(DEFAULT_CONFIG_DIR / "ipmi_cache.json"))
    if "history" in data:
        h = data["history"]
        config.history.enabled = h.get("enabled", True)
        config.history.max_points = h.get("max_points", 100)
        config.history.retention_minutes = h.get("retention_minutes", 60)
    config.system_model = data.get("system_model", "")
    config.bios_ver = data.get("bios_ver", "")
    config.sdr_cache = data.get("sdr_cache", str(DEFAULT_CONFIG_DIR / "sdr.cache"))
    return config


def save_config(config: AppConfig, path: Optional[Path] = None) -> None:
    path = path or DEFAULT_CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(_config_to_dict(config), f, indent=2)


def _config_to_dict(config: AppConfig) -> dict:
    return {
        "api": {
            "port": config.api.port,
            "host": config.api.host,
            "tls": asdict(config.api.tls),
            "security": {
                "token": config.api.security.token,
                "cors_origins": config.api.security.cors_origins,
                "rate_limit": config.api.security.rate_limit,
                "rate_window": config.api.security.rate_window,
                "audit_log": config.api.security.audit_log,
                "audit_file": config.api.security.audit_file,
            },
        },
        "sensor": {
            "has_ec": config.sensor.has_ec,
            "ec_fan_regs": config.sensor.ec_fan_regs,
            "has_boost": config.sensor.has_boost,
            "has_ipmi": config.sensor.has_ipmi,
            "ipmi_interface": config.sensor.ipmi_interface,
            "ipmi_has_fans": config.sensor.ipmi_has_fans,
            "ipmi_has_temps": config.sensor.ipmi_has_temps,
            "ipmi_has_power": config.sensor.ipmi_has_power,
            "ipmi_has_psu": config.sensor.ipmi_has_psu,
            "ipmi_has_voltage": config.sensor.ipmi_has_voltage,
            "paths": asdict(config.sensor.paths),
        },
        "alert": {
            "enabled": config.alert.enabled,
            "thresholds": asdict(config.alert.thresholds),
        },
        "cluster": {
            "enabled": config.cluster.enabled,
            "poll_interval": config.cluster.poll_interval,
            "nodes": [asdict(n) for n in config.cluster.nodes],
        },
        "cache": asdict(config.cache),
        "history": asdict(config.history),
        "system_model": config.system_model,
        "bios_ver": config.bios_ver,
        "sdr_cache": config.sdr_cache,
    }

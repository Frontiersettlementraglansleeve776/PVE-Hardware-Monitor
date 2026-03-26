"""PVE Hardware Monitor - Real-time hardware monitoring for Proxmox VE."""
__version__ = "2.0.0"

from .types import (
    HardwareStatus,
    TemperatureSensor,
    FanSensor,
    NVMeSensor,
    BatteryInfo,
    SystemInfo,
    IPMIInfo,
    IPMIPower,
    Alert,
    NodeInfo,
)
from .config import AppConfig, load_config, save_config, AlertConfig, Thresholds, NodeConfig
from .sensors import (
    BaseSensor,
    SensorRegistry,
    HwmonTempSensor,
    NvmeSensor,
    HwmonFanSensor,
    ECSensor,
    BatterySensor,
    SystemSensor,
    IPMISensor,
)
from .api import HardwareMonitor, RequestHandler
from .cluster import ClusterMonitor, TLSManager

__all__ = [
    "__version__",
    "HardwareStatus",
    "TemperatureSensor",
    "FanSensor",
    "NVMeSensor",
    "BatteryInfo",
    "SystemInfo",
    "IPMIInfo",
    "IPMIPower",
    "Alert",
    "NodeInfo",
    "AppConfig",
    "load_config",
    "save_config",
    "AlertConfig",
    "Thresholds",
    "NodeConfig",
    "BaseSensor",
    "SensorRegistry",
    "HwmonTempSensor",
    "NvmeSensor",
    "HwmonFanSensor",
    "ECSensor",
    "BatterySensor",
    "SystemSensor",
    "IPMISensor",
    "HardwareMonitor",
    "RequestHandler",
    "ClusterMonitor",
    "TLSManager",
]

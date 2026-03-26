"""Sensors package for PVE Hardware Monitor."""
from .base import BaseSensor, SensorRegistry
from .hwmon import HwmonTempSensor, NvmeSensor, HwmonFanSensor, find_hwmon_by_name, get_all_hwmon_devices
from .ec import ECSensor, ECTempSensor, ECFanSensor
from .battery import BatterySensor
from .system import SystemSensor
from .ipmi import IPMISensor, IPMICache

__all__ = [
    "BaseSensor",
    "SensorRegistry",
    "HwmonTempSensor",
    "NvmeSensor",
    "HwmonFanSensor",
    "find_hwmon_by_name",
    "get_all_hwmon_devices",
    "ECSensor",
    "ECTempSensor",
    "ECFanSensor",
    "BatterySensor",
    "SystemSensor",
    "IPMISensor",
    "IPMICache",
]

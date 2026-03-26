"""Hardware monitor (hwmon) sensor implementations."""
import os
import glob
from typing import Optional

from ..types import TemperatureSensor, FanSensor, NVMeSensor, FanSource
from .base import BaseSensor


SAFE_READ_PREFIXES = ("/sys/", "/proc/", "/opt/pve-hwmonitor/", "/dev/")


def _safe_read_path(path: str) -> bool:
    """Check if path is safe to read."""
    if not path:
        return False
    try:
        real = os.path.realpath(path)
        return any(real.startswith(p) for p in SAFE_READ_PREFIXES)
    except (OSError, ValueError):
        return False


def rf(path: str) -> Optional[str]:
    """Read file, return stripped string or None."""
    if not _safe_read_path(path):
        return None
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError, PermissionError):
        return None


def ri(path: str) -> Optional[int]:
    """Read file as int or None."""
    v = rf(path)
    if v and v.lstrip("-").isdigit():
        return int(v)
    return None


def rf_safe(path: str) -> Optional[str]:
    """Read file without path validation (for verified paths)."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError, PermissionError):
        return None


def ri_safe(path: str) -> Optional[int]:
    """Read file as int without path validation."""
    v = rf_safe(path)
    if v and v.lstrip("-").isdigit():
        return int(v)
    return None


class HwmonTempSensor(BaseSensor):
    """hwmon temperature sensor reader."""
    
    def __init__(self, hwmon_path: str, max_index: int = 16):
        super().__init__()
        self._hwmon_path = hwmon_path
        self._max_index = max_index
    
    def read(self) -> list[TemperatureSensor]:
        """Read all temperature sensors from hwmon device."""
        temps = []
        for i in range(1, self._max_index):
            t = ri(f"{self._hwmon_path}/temp{i}_input")
            if t is None:
                continue
            label = rf(f"{self._hwmon_path}/temp{i}_label") or f"Sensor {i}"
            temps.append(TemperatureSensor(
                label=label,
                temp=round(t / 1000, 1),
                source="hwmon"
            ))
        return temps


class NvmeSensor(BaseSensor):
    """NVMe temperature sensor reader."""
    
    def __init__(self):
        super().__init__()
    
    def read(self) -> list[NVMeSensor]:
        """Find and read all NVMe temperature sensors."""
        nvme_list = []
        for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*/")):
            name = rf(hw + "name") or ""
            if "nvme" in name.lower():
                drive = hw.split("/")[-2]
                for i in range(1, 5):
                    t = ri(f"{hw}temp{i}_input")
                    if t is None:
                        continue
                    label = rf(f"{hw}temp{i}_label") or f"Sensor {i}"
                    nvme_list.append(NVMeSensor(
                        label=label,
                        temp=round(t / 1000, 1),
                        drive=drive
                    ))
        return nvme_list


class HwmonFanSensor(BaseSensor):
    """hwmon fan RPM sensor reader."""
    
    def __init__(self):
        super().__init__()
    
    def read(self) -> list[FanSensor]:
        """Read all fan sensors from hwmon devices."""
        fans = []
        for f in sorted(glob.glob("/sys/class/hwmon/hwmon*/fan*_input")):
            if not _safe_read_path(f):
                continue
            val = ri(f)
            if val is None:
                continue
            hwname = rf(os.path.join(os.path.dirname(f), "name")) or "?"
            label = rf(f.replace("_input", "_label")) or os.path.basename(f).replace("_input", "")
            fans.append(FanSensor(
                name=f"{hwname}/{label}",
                rpm=val,
                source="hwmon"
            ))
        return fans


def find_hwmon_by_name(name: str) -> Optional[str]:
    """Find hwmon device by name."""
    for i in range(20):
        hw_name = rf(f"/sys/class/hwmon/hwmon{i}/name")
        if hw_name == name:
            return f"/sys/class/hwmon/hwmon{i}"
    return None


def get_all_hwmon_devices() -> dict[str, str]:
    """Get all hwmon devices with their names."""
    devices = {}
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        name = rf(hw + "/name")
        if name:
            devices[name] = hw
    return devices

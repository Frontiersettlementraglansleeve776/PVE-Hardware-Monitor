"""Battery sensor implementations."""
import glob
import os
from typing import Optional

from ..types import BatteryInfo
from .base import BaseSensor


class BatterySensor(BaseSensor):
    """Battery status sensor."""
    
    def __init__(self, bat_path: Optional[str] = None):
        super().__init__(cache_ttl=5.0)
        self._bat_path = bat_path or self._auto_detect()
    
    def _auto_detect(self) -> Optional[str]:
        """Auto-detect battery path."""
        for supply in glob.glob("/sys/class/power_supply/BAT*"):
            if os.path.isdir(supply):
                return supply
        return None
    
    def read(self) -> Optional[BatteryInfo]:
        """Read battery status."""
        if not self._bat_path or not os.path.isdir(self._bat_path):
            return None
        
        status = self._rf("status")
        capacity = self._ri("capacity")
        e_now = self._ri("energy_now") or self._ri("charge_now")
        e_full = self._ri("energy_full") or self._ri("charge_full")
        power = self._ri("power_now") or self._ri("current_now")
        voltage = self._ri("voltage_now")
        cycles = self._ri("cycle_count")
        
        return BatteryInfo(
            status=status or "Unknown",
            capacity=capacity,
            energy_now=round(e_now / 1e6, 2) if e_now else None,
            energy_full=round(e_full / 1e6, 2) if e_full else None,
            power=round(power / 1e6, 2) if power else None,
            voltage=round(voltage / 1e6, 2) if voltage else None,
            cycles=cycles,
        )
    
    def _rf(self, attr: str) -> Optional[str]:
        """Read battery attribute."""
        try:
            with open(os.path.join(self._bat_path, attr)) as f:  # type: ignore[arg-type]
                return f.read().strip()
        except (OSError, IOError, PermissionError):
            return None
    
    def _ri(self, attr: str) -> Optional[int]:
        """Read battery attribute as int."""
        v = self._rf(attr)
        if v and v.lstrip("-").isdigit():
            return int(v)
        return None

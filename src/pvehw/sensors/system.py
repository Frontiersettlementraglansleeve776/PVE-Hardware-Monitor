"""System information sensor implementations."""
from typing import Optional

from ..types import SystemInfo
from .base import BaseSensor


class SystemSensor(BaseSensor):
    """System information sensor (uptime, load, memory)."""
    
    def __init__(self):
        super().__init__(cache_ttl=2.0)
    
    def read(self) -> SystemInfo:
        """Read system information."""
        uptime = self._read_uptime()
        load = self._read_loadavg()
        mem = self._read_meminfo()
        
        return SystemInfo(
            uptime_s=uptime,
            load=load,
            mem_total=mem.get("total"),
            mem_used=mem.get("used"),
            mem_pct=mem.get("pct"),
        )
    
    def _read_uptime(self) -> Optional[float]:
        """Read system uptime in seconds."""
        try:
            with open("/proc/uptime") as f:
                return float(f.read().split()[0])
        except (OSError, IOError, ValueError):
            return None
    
    def _read_loadavg(self) -> list[float]:
        """Read system load average."""
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                return [float(parts[0]), float(parts[1]), float(parts[2])]
        except (OSError, IOError, ValueError, IndexError):
            return []
    
    def _read_meminfo(self) -> dict:
        """Read memory information."""
        mem = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        mem["total"] = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        mem["available"] = int(line.split()[1]) // 1024
        except (OSError, IOError, ValueError, IndexError):
            return mem
        
        if "total" in mem and "available" in mem:
            mem["used"] = mem["total"] - mem["available"]
            mem["pct"] = round(mem["used"] / mem["total"] * 100, 1)
        
        return mem

"""IPMI sensor implementations for server BMC access."""
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Optional

from ..types import FanSensor, TemperatureSensor, IPMIPower, IPMIInfo
from .base import BaseSensor


class IPMISensor(BaseSensor):
    """IPMI sensor reader with caching and threading."""
    
    def __init__(self, 
                 interface: str = "open",
                 sdr_cache: Optional[str] = None,
                 cache_ttl: float = 2.0,
                 has_fans: bool = True,
                 has_temps: bool = True,
                 has_power: bool = True,
                 has_psu: bool = True,
                 has_voltage: bool = True):
        super().__init__(cache_ttl=cache_ttl)
        self._interface = interface
        self._sdr_cache = sdr_cache
        self._has_fans = has_fans
        self._has_temps = has_temps
        self._has_power = has_power
        self._has_psu = has_psu
        self._has_voltage = has_voltage
        self._timeout = 6.0
    
    def _sdr_cache_valid(self) -> bool:
        """Check if SDR cache is valid and secure."""
        if not self._sdr_cache or not os.path.exists(self._sdr_cache):
            return False
        try:
            st = os.stat(self._sdr_cache)
            return st.st_uid == 0 and not (st.st_mode & 0o022)
        except OSError:
            return False
    
    def _ipmitool(self, *args: str) -> list[str]:
        """Run ipmitool command with timeout."""
        try:
            cmd = ["ipmitool", "-I", self._interface, "-N", "3", "-R", "1"]
            if self._sdr_cache and self._sdr_cache_valid():
                cmd += ["-S", self._sdr_cache]
            cmd += list(args)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout - 1
            )
            return result.stdout.splitlines() if result.returncode == 0 else []
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
    
    def _parse_sdr_value(self, line: str) -> Optional[tuple]:
        """Parse SDR value line."""
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            return None
        name = parts[0].strip()
        raw = parts[1].strip()
        status = parts[2].strip().lower()
        m = re.match(r"^([\d.]+)\s*(.*)", raw)
        if not m:
            return None
        try:
            val = float(m.group(1))
        except ValueError:
            return None
        return name, val, m.group(2).strip(), status
    
    def _run_with_timeout(self, func) -> list:
        """Run function in thread with hard timeout."""
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(func).result(timeout=self._timeout)
        except Exception:
            return []
    
    def read(self) -> IPMIInfo:
        """Read all IPMI sensors in parallel."""
        ipmi = IPMIInfo()
        
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {}
            
            if self._has_fans:
                futures["fans"] = ex.submit(self._read_fans)
            if self._has_temps:
                futures["temps"] = ex.submit(self._read_temps)
            if self._has_power:
                futures["power"] = ex.submit(self._read_power)
            if self._has_psu:
                futures["psu"] = ex.submit(self._read_psu)
            if self._has_voltage:
                futures["voltages"] = ex.submit(self._read_voltages)
            
            for key, future in futures.items():
                try:
                    result = future.result(timeout=self._timeout + 1)
                    if key == "fans":
                        ipmi.fans = result
                    elif key == "temps":
                        ipmi.temps = result
                    elif key == "power":
                        ipmi.power = result
                    elif key == "psu":
                        ipmi.psu = result
                    elif key == "voltages":
                        ipmi.voltages = result
                except Exception:
                    pass
        
        return ipmi
    
    def _read_fans(self) -> list[FanSensor]:
        """Read fan sensors."""
        fans = []
        for line in self._ipmitool("sdr", "type", "Fan"):
            r = self._parse_sdr_value(line)
            if not r:
                continue
            name, val, unit, status = r
            if "RPM" not in unit.upper():
                continue
            fans.append(FanSensor(
                name=name,
                rpm=int(val),
                status=status,
                source="ipmi"
            ))
        return fans
    
    def _read_temps(self) -> list[TemperatureSensor]:
        """Read temperature sensors."""
        temps = []
        for line in self._ipmitool("sdr", "type", "Temperature"):
            r = self._parse_sdr_value(line)
            if not r:
                continue
            name, val, unit, status = r
            if "degrees" not in unit.lower() and "°" not in unit:
                continue
            if status in ("ns", "na", "n/a"):
                continue
            temps.append(TemperatureSensor(
                label=name,
                temp=round(val, 1),
                source="ipmi"
            ))
        return temps
    
    def _read_power(self) -> Optional[IPMIPower]:
        """Read power consumption."""
        result = {}
        for line in self._ipmitool("dcmi", "power", "reading"):
            line = line.strip()
            patterns = [
                (r"Instantaneous power reading:\s+([\d.]+)\s+Watts", "watts_now"),
                (r"Minimum.*?:\s+([\d.]+)\s+Watts", "watts_min"),
                (r"Maximum.*?:\s+([\d.]+)\s+Watts", "watts_max"),
                (r"Average.*?:\s+([\d.]+)\s+Watts", "watts_avg"),
            ]
            for pattern, key in patterns:
                m = re.search(pattern, line)
                if m:
                    result[key] = float(m.group(1))
        return IPMIPower(**result) if result else None
    
    def _read_psu(self) -> list[dict]:
        """Read PSU status."""
        psus = []
        for line in self._ipmitool("sdr", "type", "Power Supply"):
            r = self._parse_sdr_value(line)
            if not r:
                continue
            name, val, unit, status = r
            psus.append({"name": name, "value": val, "unit": unit, "status": status})
        return psus
    
    def _read_voltages(self) -> list[dict]:
        """Read voltage sensors."""
        volts = []
        for line in self._ipmitool("sdr", "type", "Voltage"):
            r = self._parse_sdr_value(line)
            if not r:
                continue
            name, val, unit, status = r
            if status in ("ns", "na", "n/a"):
                continue
            volts.append({
                "label": name,
                "value": round(val, 3),
                "unit": unit,
                "status": status
            })
        return volts


class IPMICache:
    """Cache for IPMI data to reduce BMC load."""
    
    def __init__(self, cache_file: str, ttl: float = 2.0):
        self._cache_file = cache_file
        self._ttl = ttl
        self._cache: dict = {}
        self._last_write: float = 0
    
    def get(self, key: str) -> Optional[dict]:
        """Get cached value if not expired."""
        if not os.path.exists(self._cache_file):
            return None
        try:
            with open(self._cache_file) as f:
                data = json.load(f)
            entry = data.get(key)
            if entry and time.time() - entry.get("_ts", 0) < self._ttl:
                return entry
        except (json.JSONDecodeError, OSError):
            pass
        return None
    
    def set(self, key: str, value: dict) -> None:
        """Set cached value."""
        try:
            if os.path.exists(self._cache_file):
                try:
                    with open(self._cache_file) as f:
                        self._cache = json.load(f)
                except (json.JSONDecodeError, OSError):
                    self._cache = {}
            
            self._cache[key] = {**value, "_ts": time.time()}
            
            if time.time() - self._last_write > 1.0:
                with open(self._cache_file, "w") as f:
                    json.dump(self._cache, f)
                self._last_write = time.time()
        except OSError:
            pass

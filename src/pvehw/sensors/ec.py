"""Embedded Controller (EC) sensor implementations for ASUS laptops."""
import struct
from typing import Optional

from ..types import FanSensor
from .base import BaseSensor


EC_FAN_REGISTERS = [
    ("CPU", 0x66, 0x97),
    ("GPU", 0x68, 0x98),
]


class ECSensor(BaseSensor):
    """Embedded Controller sensor for reading EC registers."""
    
    def __init__(self, ec_path: str = "/sys/kernel/debug/ec/ec0/io"):
        super().__init__(cache_ttl=0.5)
        self._ec_path = ec_path
    
    def read_ec(self, offset: int, count: int = 1) -> Optional[bytes]:
        """Read bytes from EC register."""
        try:
            with open(self._ec_path, "rb") as f:
                f.seek(offset)
                return f.read(count)
        except (OSError, IOError, PermissionError):
            return None
    
    def read(self) -> dict:
        """Read all EC sensor data."""
        ec_temp_b = self.read_ec(0x58)
        ec_temp = struct.unpack("B", ec_temp_b)[0] if ec_temp_b else None
        
        board_b = self.read_ec(0xC5)
        board_temp = struct.unpack("B", board_b)[0] if board_b else None
        
        fans = []
        for name, offset, duty_offset in EC_FAN_REGISTERS:
            raw_b = self.read_ec(offset, 2)
            duty_b = self.read_ec(duty_offset)
            raw = struct.unpack("<H", raw_b)[0] if raw_b else 0
            duty = struct.unpack("B", duty_b)[0] if duty_b else 0
            rpm = round(2156250 / raw) if raw > 0 else 0
            fans.append(FanSensor(
                name=name,
                rpm=rpm,
                duty=duty,
                raw=raw,
                source="ec"
            ))
        
        if all(f.raw == 0 for f in fans):
            return {"ec_temp": ec_temp, "board_temp": board_temp, "fans": []}
        
        return {
            "ec_temp": ec_temp,
            "board_temp": board_temp,
            "fans": fans
        }


class ECTempSensor(BaseSensor):
    """EC temperature sensor."""
    
    def __init__(self, ec_path: str = "/sys/kernel/debug/ec/ec0/io", offset: int = 0x58):
        super().__init__(cache_ttl=0.5)
        self._ec_path = ec_path
        self._offset = offset
    
    def read(self) -> Optional[float]:
        """Read EC temperature."""
        try:
            with open(self._ec_path, "rb") as f:
                f.seek(self._offset)
                data = f.read(1)
                if data:
                    return float(struct.unpack("B", data)[0])
        except (OSError, IOError, PermissionError):
            return None
        return None


class ECFanSensor(BaseSensor):
    """EC fan speed sensor."""
    
    def __init__(self, ec_path: str = "/sys/kernel/debug/ec/ec0/io",
                 name: str = "CPU", offset: int = 0x66, duty_offset: int = 0x97):
        super().__init__(cache_ttl=0.5)
        self._ec_path = ec_path
        self._name = name
        self._offset = offset
        self._duty_offset = duty_offset
    
    def read(self) -> FanSensor:
        """Read fan speed from EC register."""
        try:
            with open(self._ec_path, "rb") as f:
                f.seek(self._offset)
                raw_b = f.read(2)
                raw = struct.unpack("<H", raw_b)[0] if raw_b else 0
                
                f.seek(self._duty_offset)
                duty_b = f.read(1)
                duty = struct.unpack("B", duty_b)[0] if duty_b else 0
                
                rpm = round(2156250 / raw) if raw > 0 else 0
                
                return FanSensor(
                    name=self._name,
                    rpm=rpm,
                    duty=duty,
                    raw=raw,
                    source="ec"
                )
        except (OSError, IOError, PermissionError):
            return FanSensor(name=self._name, rpm=0, source="ec")

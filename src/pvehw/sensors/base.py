"""Base sensor interface for PVE Hardware Monitor."""
from abc import ABC, abstractmethod
from typing import Any, Optional
import time


class BaseSensor(ABC):
    """Abstract base class for all sensors."""
    
    def __init__(self, cache_ttl: float = 0.0):
        self._cache_ttl = cache_ttl
        self._cached_data: Optional[Any] = None
        self._cache_time: float = 0.0
    
    @abstractmethod
    def read(self) -> Any:
        """Read sensor data."""
        pass
    
    def get(self, force_refresh: bool = False) -> Any:
        """Get sensor data with caching."""
        if self._cache_ttl <= 0 or force_refresh:
            return self.read()
        
        now = time.monotonic()
        if now - self._cache_time > self._cache_ttl:
            self._cached_data = self.read()
            self._cache_time = now
        return self._cached_data
    
    def invalidate_cache(self) -> None:
        """Invalidate cached data."""
        self._cache_time = 0.0


class SensorRegistry:
    """Registry for managing multiple sensors."""
    
    def __init__(self):
        self._sensors: dict[str, BaseSensor] = {}
    
    def register(self, name: str, sensor: BaseSensor) -> None:
        """Register a sensor."""
        self._sensors[name] = sensor
    
    def get(self, name: str) -> Optional[BaseSensor]:
        """Get a sensor by name."""
        return self._sensors.get(name)
    
    def read_all(self) -> dict[str, Any]:
        """Read all registered sensors."""
        return {name: sensor.get() for name, sensor in self._sensors.items()}
    
    def read_all_forced(self) -> dict[str, Any]:
        """Read all sensors, bypassing cache."""
        return {name: sensor.get(force_refresh=True) for name, sensor in self._sensors.items()}

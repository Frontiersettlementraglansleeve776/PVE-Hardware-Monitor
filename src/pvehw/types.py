"""Type definitions for PVE Hardware Monitor."""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class FanSource(Enum):
    HWMON = "hwmon"
    EC = "ec"
    IPMI = "ipmi"


class FanProfile(Enum):
    NORMAL = 0
    BOOST = 1
    SILENT = 2


@dataclass
class TemperatureSensor:
    label: str
    temp: float
    source: str = "hwmon"


@dataclass
class FanSensor:
    name: str
    rpm: int
    duty: Optional[int] = None
    raw: Optional[int] = None
    status: str = "ok"
    source: str = "hwmon"


@dataclass
class NVMeSensor:
    label: str
    temp: float
    drive: Optional[str] = None


@dataclass
class BatteryInfo:
    status: str
    capacity: Optional[int] = None
    energy_now: Optional[float] = None
    energy_full: Optional[float] = None
    power: Optional[float] = None
    voltage: Optional[float] = None
    cycles: Optional[int] = None


@dataclass
class SystemInfo:
    uptime_s: Optional[float] = None
    load: list[float] = field(default_factory=list)
    mem_total: Optional[int] = None
    mem_used: Optional[int] = None
    mem_pct: Optional[float] = None


@dataclass
class IPMIPower:
    watts_now: Optional[float] = None
    watts_min: Optional[float] = None
    watts_max: Optional[float] = None
    watts_avg: Optional[float] = None


@dataclass
class IPMIInfo:
    fans: list[FanSensor] = field(default_factory=list)
    temps: list[TemperatureSensor] = field(default_factory=list)
    power: Optional[IPMIPower] = None
    psu: list[dict] = field(default_factory=list)
    voltages: list[dict] = field(default_factory=list)


@dataclass
class HardwareStatus:
    ok: bool = True
    model: str = ""
    cpu_temp: Optional[float] = None
    core_temps: list[TemperatureSensor] = field(default_factory=list)
    ec_temp: Optional[float] = None
    board_temp: Optional[float] = None
    pch_temp: Optional[float] = None
    nvme: list[NVMeSensor] = field(default_factory=list)
    fans: list[FanSensor] = field(default_factory=list)
    battery: Optional[BatteryInfo] = None
    system: Optional[SystemInfo] = None
    ipmi: Optional[IPMIInfo] = None
    has_ipmi: bool = False
    mode: str = "n/a"
    mode_raw: Optional[int] = None
    has_boost: bool = False


@dataclass
class Alert:
    level: str
    message: str
    timestamp: float


@dataclass
class NodeInfo:
    name: str
    host: str
    port: int = 9099
    token: Optional[str] = None
    enabled: bool = True
    status: Optional[dict] = None

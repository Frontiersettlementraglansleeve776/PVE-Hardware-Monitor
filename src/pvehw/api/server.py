"""Async HTTP/WebSocket server for PVE Hardware Monitor."""
import asyncio
import hmac
import json
import logging
import os
import ssl
import sys
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import AppConfig, load_config, save_config, AlertConfig as ConfigAlertConfig, Thresholds
from ..types import HardwareStatus, Alert
from ..sensors import (
    ECSensor,
    HwmonTempSensor,
    HwmonFanSensor,
    NvmeSensor,
    BatterySensor,
    SystemSensor,
    IPMISensor,
    IPMICache,
    find_hwmon_by_name,
)
from .websocket import WebSocketManager


SAFE_READ_PREFIXES = ("/sys/", "/proc/", "/opt/pve-hwmonitor/", "/dev/")
ALLOWED_WRITE_PATHS: set = set()


def _safe_read_path(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(path)
        return any(real.startswith(p) for p in SAFE_READ_PREFIXES)
    except (OSError, ValueError):
        return False


def rf(path: Optional[str]) -> Optional[str]:
    if not path or not _safe_read_path(path):
        return None
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError, PermissionError):
        return None


def ri(path: Optional[str]) -> Optional[int]:
    v = rf(path)
    if v and v.lstrip("-").isdigit():
        return int(v)
    return None


def wf(path: Optional[str], value: str) -> bool:
    if not path or path not in ALLOWED_WRITE_PATHS:
        return False
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except (OSError, IOError, PermissionError):
        return False


def _log(ctx: str, msg: str) -> None:
    print(f"[ERROR] {ctx}: {msg}", flush=True)


def _log_exc(ctx: str) -> None:
    print(f"[ERROR] {ctx}:\n{traceback.format_exc()}", flush=True)


class AuditLogger:
    """Audit logging for API access."""
    
    def __init__(self, log_file: Optional[str] = None):
        self._log_file = log_file
        self._lock = threading.Lock()
    
    def log(self, client_ip: str, method: str, path: str, status: int, 
            user_agent: str = "", token_ok: bool = True) -> None:
        if not self._log_file:
            return
        try:
            with self._lock:
                with open(self._log_file, "a") as f:
                    timestamp = datetime.utcnow().isoformat()
                    f.write(
                        f'{{"ts":"{timestamp}","ip":"{client_ip}","method":"{method}",'
                        f'"path":"{path}","status":{status},'
                        f'"ua":"{user_agent}","auth_ok":{token_ok}}}\n'
                    )
        except OSError:
            pass


class RateLimiter:
    """Rate limiter for API requests."""
    
    def __init__(self, limit: int = 10, window: float = 1.0):
        self._limit = limit
        self._window = window
        self._lock = threading.Lock()
        self._counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    
    def check(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            count, start = self._counts[ip]
            if now - start > self._window:
                self._counts[ip] = (1, now)
                return True
            if count >= self._limit:
                return False
            self._counts[ip] = (count + 1, start)
            return True


class HistoryBuffer:
    """Rolling history buffer for chart data."""
    
    def __init__(self, max_points: int = 100):
        self._max = max_points
        self._data: dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
    
    def push(self, **values: float) -> None:
        with self._lock:
            for key, val in values.items():
                self._data[key].append(val)
                if len(self._data[key]) > self._max:
                    self._data[key].pop(0)
    
    def get(self, key: str) -> list:
        with self._lock:
            return list(self._data.get(key, []))
    
    def get_all(self) -> dict:
        with self._lock:
            return {k: list(v) for k, v in self._data.items()}


class AlertManager:
    """Alert detection and management."""
    
    def __init__(self, config: ConfigAlertConfig):
        self._config = config
        self._lock = threading.Lock()
        self._alerts: list[Alert] = []
    
    def check(self, status: HardwareStatus) -> list[Alert]:
        if not self._config.enabled:
            return []
        
        alerts = []
        t = self._config.thresholds
        
        if status.cpu_temp and status.cpu_temp > t.cpu_crit:
            alerts.append(Alert("critical", f"CPU {status.cpu_temp}°C — critical", time.time()))
        elif status.cpu_temp and status.cpu_temp > t.cpu_warn:
            alerts.append(Alert("warning", f"CPU {status.cpu_temp}°C — warm", time.time()))
        
        if status.nvme:
            for nvme in status.nvme:
                if nvme.temp > t.nvme_crit:
                    alerts.append(Alert("critical", f"NVMe {nvme.label} {nvme.temp}°C", time.time()))
                    break
                elif nvme.temp > t.nvme_warn:
                    alerts.append(Alert("warning", f"NVMe {nvme.label} {nvme.temp}°C", time.time()))
                    break
        
        if status.battery and status.battery.capacity:
            if status.battery.capacity < t.battery_crit:
                alerts.append(Alert("critical", f"Battery {status.battery.capacity}% — very low", time.time()))
            elif status.battery.capacity < t.battery_warn:
                alerts.append(Alert("warning", f"Battery {status.battery.capacity}% — low", time.time()))
        
        for fan in status.fans:
            if fan.rpm < t.fan_min_rpm and fan.rpm > 0:
                alerts.append(Alert("warning", f"{fan.name} fan {fan.rpm} RPM — low", time.time()))
                break
        
        with self._lock:
            self._alerts = alerts
        
        return alerts
    
    def get_active(self) -> list[Alert]:
        with self._lock:
            return list(self._alerts)


class HardwareMonitor:
    """Main hardware monitoring engine."""
    
    def __init__(self, config: AppConfig):
        self._config = config
        self._ec_sensor = ECSensor(config.sensor.paths.ec_path) if config.sensor.has_ec else None
        self._coretemp_sensor = HwmonTempSensor(config.sensor.paths.hw_coretemp or "") if config.sensor.paths.hw_coretemp else None
        self._nvme_sensor = NvmeSensor()
        self._fan_sensor = HwmonFanSensor()
        self._battery_sensor = BatterySensor(config.sensor.paths.bat_path) if config.sensor.paths.bat_path else BatterySensor()
        self._system_sensor = SystemSensor()
        self._ipmi_sensor: Optional[IPMISensor] = None
        self._ipmi_cache: Optional[IPMICache] = None
        
        if config.sensor.has_ipmi:
            self._ipmi_sensor = IPMISensor(
                interface=config.sensor.ipmi_interface,
                sdr_cache=config.sdr_cache,
                cache_ttl=config.cache.ipmi_cache_ttl,
                has_fans=config.sensor.ipmi_has_fans,
                has_temps=config.sensor.ipmi_has_temps,
                has_power=config.sensor.ipmi_has_power,
                has_psu=config.sensor.ipmi_has_psu,
                has_voltage=config.sensor.ipmi_has_voltage,
            )
            self._ipmi_cache = IPMICache(config.cache.ipmi_cache_file, config.cache.ipmi_cache_ttl)
        
        global ALLOWED_WRITE_PATHS
        if config.sensor.paths.boost_path:
            ALLOWED_WRITE_PATHS.add(config.sensor.paths.boost_path)
        
        self._history = HistoryBuffer(config.history.max_points)
        self._alert_mgr = AlertManager(config.alert)
        
        if config.alert.enabled:
            ALLOWED_WRITE_PATHS.add(config.sensor.paths.boost_path)
    
    def get_status(self) -> HardwareStatus:
        ec_data = self._ec_sensor.read() if self._ec_sensor else {}
        coretemp_list = self._coretemp_sensor.read() if self._coretemp_sensor else []
        nvme_list = self._nvme_sensor.read()
        fans_hw = self._fan_sensor.read()
        battery = self._battery_sensor.read()
        system = self._system_sensor.read()
        
        pkg_temp = coretemp_list[0].temp if coretemp_list else ec_data.get("ec_temp")
        core_temps = coretemp_list[1:] if len(coretemp_list) > 1 else []
        
        pch_temp = None
        if self._config.sensor.paths.hw_pch:
            pch_temps = HwmonTempSensor(self._config.sensor.paths.hw_pch).read()
            if pch_temps:
                pch_temp = pch_temps[0].temp
        
        ipmi = None
        ipmi_fans = []
        if self._ipmi_sensor:
            cached = self._ipmi_cache.get("ipmi") if self._ipmi_cache else None
            if cached:
                from ..types import IPMIInfo, FanSensor, TemperatureSensor, IPMIPower
                ipmi_fans = [FanSensor(**f) for f in cached.get("fans", [])]
                ipmi = IPMIInfo(
                    fans=ipmi_fans,
                    temps=[TemperatureSensor(**t) for t in cached.get("temps", [])],
                    power=IPMIPower(**cached["power"]) if cached.get("power") else None,
                    psu=cached.get("psu", []),
                    voltages=cached.get("voltages", []),
                )
            else:
                ipmi = self._ipmi_sensor.read()
                ipmi_fans = ipmi.fans
                if self._ipmi_cache:
                    self._ipmi_cache.set("ipmi", {
                        "fans": [asdict(f) for f in ipmi.fans],
                        "temps": [asdict(t) for t in ipmi.temps],
                        "power": asdict(ipmi.power) if ipmi.power else None,
                        "psu": ipmi.psu,
                        "voltages": ipmi.voltages,
                    })
        
        fans_ec = ec_data.get("fans", [])
        if fans_ec:
            fans = fans_ec
        elif fans_hw:
            fans = fans_hw
        elif ipmi_fans:
            fans = ipmi_fans
        else:
            fans = []
        
        boost_str = rf(self._config.sensor.paths.boost_path) if self._config.sensor.has_boost else None
        bv = int(boost_str) if boost_str and boost_str.isdigit() else None
        
        status = HardwareStatus(
            ok=True,
            model=self._config.system_model,
            cpu_temp=pkg_temp,
            core_temps=core_temps,
            ec_temp=ec_data.get("ec_temp"),
            board_temp=ec_data.get("board_temp"),
            pch_temp=pch_temp,
            nvme=nvme_list,
            fans=fans,
            battery=battery,
            system=system,
            ipmi=ipmi,
            has_ipmi=self._config.sensor.has_ipmi,
            mode={0: "normal", 1: "boost", 2: "silent"}.get(bv, "n/a") if bv is not None else "n/a",
            mode_raw=bv,
            has_boost=self._config.sensor.has_boost,
        )
        
        self._history.push(
            cpu_rpm=(fans[0].rpm if fans else 0),
            gpu_rpm=(fans[1].rpm if len(fans) > 1 else 0),
            cpu_temp=(status.cpu_temp or 0),
            nvme_temp=(nvme_list[0].temp if nvme_list else 0),
        )
        
        self._alert_mgr.check(status)
        
        return status
    
    def get_history(self) -> dict:
        return self._history.get_all()
    
    def get_alerts(self) -> list:
        return self._alert_mgr.get_active()


class RequestHandler:
    """HTTP request handler with security and routing."""
    
    def __init__(self, monitor: HardwareMonitor, config: AppConfig):
        self._monitor = monitor
        self._config = config
        self._rate_limiter = RateLimiter(
            config.api.security.rate_limit,
            config.api.security.rate_window
        )
        self._audit_logger = AuditLogger(
            config.api.security.audit_file if config.api.security.audit_log else None
        )
        self._ws_manager = WebSocketManager()
    
    def _client_ip(self, handler) -> str:
        return handler.client_address[0]
    
    def _check_auth(self, headers: dict) -> bool:
        token = self._config.api.security.token
        if not token:
            return True
        provided = headers.get("X-Api-Token", "")
        return hmac.compare_digest(provided, token)
    
    def _check_rate(self, ip: str) -> bool:
        return self._rate_limiter.check(ip)
    
    def _cors_headers(self, handler, origin: str = "") -> None:
        allowed = self._config.api.security.cors_origins
        if "*" in allowed or (origin and origin in allowed):
            handler.send_header("Access-Control-Allow-Origin", origin if origin else "*")
        elif origin:
            handler.send_header("Vary", "Origin")
        self._config.api.security.cors_origins
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type, X-Api-Token")
    
    def _security_headers(self, handler) -> None:
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("X-Frame-Options", "DENY")
        handler.send_header("Cache-Control", "no-store")
    
    def handle(self, handler, method: str, path: str, headers: dict, 
               body: Optional[bytes] = None) -> tuple[int, dict]:
        client_ip = self._client_ip(handler)
        origin = headers.get("Origin", "")
        
        if not self._check_rate(client_ip):
            self._audit_logger.log(client_ip, method, path, 429, 
                                   headers.get("User-Agent", ""))
            return 429, {"ok": False, "error": "Too many requests"}
        
        if not self._check_auth(headers):
            self._audit_logger.log(client_ip, method, path, 401,
                                   headers.get("User-Agent", ""), False)
            return 401, {"ok": False, "error": "Unauthorized"}
        
        self._audit_logger.log(client_ip, method, path, 200,
                               headers.get("User-Agent", ""), True)
        
        if path == "/api/status":
            try:
                status = self._monitor.get_status()
                return 200, asdict(status)
            except Exception:
                _log_exc("get_status")
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/history":
            try:
                return 200, self._monitor.get_history()
            except Exception:
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/alerts":
            try:
                return 200, {"alerts": [asdict(a) for a in self._monitor.get_alerts()]}
            except Exception:
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/metrics":
            try:
                status = self._monitor.get_status()
                return 200, self._prometheus_metrics(status)
            except Exception:
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/export/json":
            try:
                status = self._monitor.get_status()
                return 200, asdict(status)
            except Exception:
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/export/csv":
            try:
                status = self._monitor.get_status()
                csv = self._to_csv(status)
                return 200, {"csv": csv, "content_type": "text/csv"}
            except Exception:
                return 500, {"ok": False, "error": "Internal server error"}
        
        elif path == "/api/config" and method == "GET":
            return 200, {
                "port": self._config.api.port,
                "has_boost": self._config.sensor.has_boost,
                "has_ipmi": self._config.sensor.has_ipmi,
                "alerts_enabled": self._config.alert.enabled,
                "thresholds": asdict(self._config.alert.thresholds),
            }
        
        elif path == "/api/config/thresholds" and method == "POST":
            try:
                data = json.loads(body) if body else {}
                self._config.alert.thresholds.cpu_warn = data.get("cpu_warn", 80.0)
                self._config.alert.thresholds.cpu_crit = data.get("cpu_crit", 90.0)
                self._config.alert.thresholds.nvme_warn = data.get("nvme_warn", 55.0)
                self._config.alert.thresholds.nvme_crit = data.get("nvme_crit", 70.0)
                self._config.alert.thresholds.battery_warn = data.get("battery_warn", 20.0)
                self._config.alert.thresholds.battery_crit = data.get("battery_crit", 10.0)
                save_config(self._config)
                return 200, {"ok": True, "msg": "Thresholds updated"}
            except Exception:
                return 500, {"ok": False, "error": "Failed to update thresholds"}
        
        elif path == "/api/mode" and method == "POST" and self._config.sensor.has_boost:
            try:
                data = json.loads(body) if body else {}
                mode = int(data.get("mode", -1))
                if mode not in (0, 1, 2):
                    return 400, {"ok": False, "error": "mode must be 0, 1, or 2"}
                names = {0: "Normal", 1: "Boost", 2: "Silent"}
                res = wf(self._config.sensor.paths.boost_path, str(mode))
                if res:
                    return 200, {"ok": True, "msg": f"Fan profile: {names[mode]}"}
                return 500, {"ok": False, "error": "Write failed"}
            except Exception:
                return 500, {"ok": False, "error": "Invalid request"}
        
        elif path == "/health":
            return 200, {"status": "ok", "timestamp": time.time()}
        
        elif path in ("/", "/index.html", "/dashboard.html"):
            return 200, {"redirect": "/dashboard.html"}
        
        elif path == "/api/ws/connect":
            return 200, {"ws_endpoint": "/ws"}
        
        return 404, {"ok": False, "error": "Not found"}
    
    def _prometheus_metrics(self, status: HardwareStatus) -> dict:
        lines = [f'# HELP pve_hwmonitor_info Hardware monitor info']
        lines.append(f'# TYPE pve_hwmonitor_info gauge')
        lines.append(f'pve_hwmonitor_info{{model="{status.model}"}} 1')
        
        if status.cpu_temp is not None:
            lines.append(f'# HELP pve_cpu_temperature CPU temperature in Celsius')
            lines.append(f'# TYPE pve_cpu_temperature gauge')
            lines.append(f'pve_cpu_temperature {status.cpu_temp}')
        
        for fan in status.fans:
            lines.append(f'# HELP pve_fan_rpm Fan speed in RPM')
            lines.append(f'# TYPE pve_fan_rpm gauge')
            lines.append(f'pve_fan_rpm{{name="{fan.name}",source="{fan.source}"}} {fan.rpm}')
        
        for nvme in status.nvme:
            lines.append(f'# HELP pve_nvme_temperature NVMe temperature')
            lines.append(f'# TYPE pve_nvme_temperature gauge')
            lines.append(f'pve_nvme_temperature{{label="{nvme.label}"}} {nvme.temp}')
        
        if status.system and status.system.mem_pct is not None:
            lines.append(f'# HELP pve_memory_usage_percent Memory usage percentage')
            lines.append(f'# TYPE pve_memory_usage_percent gauge')
            lines.append(f'pve_memory_usage_percent {status.system.mem_pct}')
        
        return {"metrics": "\n".join(lines), "content_type": "text/plain"}
    
    def _to_csv(self, status: HardwareStatus) -> str:
        lines = ["timestamp,metric,value"]
        lines.append(f'{datetime.now().isoformat()},cpu_temp,{status.cpu_temp or ""}')
        for fan in status.fans:
            lines.append(f'{datetime.now().isoformat()},{fan.name}_rpm,{fan.rpm}')
        for nvme in status.nvme:
            lines.append(f'{datetime.now().isoformat()},nvme_{nvme.label},{nvme.temp}')
        return "\n".join(lines)
    
    def register_ws(self, ws_handler):
        self._ws_manager.register(ws_handler)
    
    def unregister_ws(self, ws_handler):
        self._ws_manager.unregister(ws_handler)
    
    async def broadcast_status(self) -> None:
        try:
            status = self._monitor.get_status()
            await self._ws_manager.broadcast(json.dumps(asdict(status)))
        except Exception:
            pass

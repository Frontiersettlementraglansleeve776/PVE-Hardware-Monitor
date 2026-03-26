"""Unit tests for PVE Hardware Monitor."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from pvehw.config import (
    AppConfig,
    load_config,
    save_config,
    AlertConfig,
    Thresholds,
    NodeConfig,
    ClusterConfig,
    APIConfig,
    SensorConfig,
    TLSConfig,
    SecurityConfig,
)
from pvehw.types import (
    HardwareStatus,
    TemperatureSensor,
    FanSensor,
    NVMeSensor,
    BatteryInfo,
    SystemInfo,
    IPMIInfo,
    IPMIPower,
    Alert,
)
from pvehw.sensors.base import BaseSensor, SensorRegistry
from pvehw.api.websocket import WebSocketFrame


class TestConfig:
    """Test configuration management."""
    
    def test_default_config(self):
        config = AppConfig()
        assert config.api.port == 9099
        assert config.api.host == "0.0.0.0"
        assert config.alert.enabled is True
        assert config.cluster.enabled is False
    
    def test_save_load_config(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        
        try:
            config = AppConfig()
            config.api.port = 8080
            config.system_model = "Test Server"
            config.alert.thresholds.cpu_warn = 75.0
            
            save_config(config, temp_path)
            loaded = load_config(temp_path)
            
            assert loaded.api.port == 8080
            assert loaded.system_model == "Test Server"
            assert loaded.alert.thresholds.cpu_warn == 75.0
        finally:
            temp_path.unlink(missing_ok=True)
    
    def test_load_nonexistent_config(self):
        config = load_config(Path("/nonexistent/path/config.json"))
        assert config.api.port == 9099
        assert config.alert.enabled is True


class TestTypes:
    """Test type definitions."""
    
    def test_hardware_status_defaults(self):
        status = HardwareStatus()
        assert status.ok is True
        assert status.model == ""
        assert status.cpu_temp is None
        assert status.fans == []
        assert status.has_ipmi is False
    
    def test_fan_sensor(self):
        fan = FanSensor(name="CPU", rpm=3500, duty=128, raw=615, source="ec")
        assert fan.name == "CPU"
        assert fan.rpm == 3500
        assert fan.duty == 128
        assert fan.raw == 615
        assert fan.source == "ec"
    
    def test_temperature_sensor(self):
        temp = TemperatureSensor(label="Core 0", temp=45.5)
        assert temp.label == "Core 0"
        assert temp.temp == 45.5
        assert temp.source == "hwmon"
    
    def test_nvme_sensor(self):
        nvme = NVMeSensor(label="Composite", temp=38.9, drive="nvme0")
        assert nvme.label == "Composite"
        assert nvme.temp == 38.9
        assert nvme.drive == "nvme0"
    
    def test_battery_info(self):
        battery = BatteryInfo(
            status="Charging",
            capacity=85,
            energy_now=45.2,
            energy_full=53.2,
            power=15.5,
            voltage=11.4,
            cycles=150
        )
        assert battery.status == "Charging"
        assert battery.capacity == 85
        assert battery.cycles == 150
    
    def test_system_info(self):
        system = SystemInfo(
            uptime_s=86400.0,
            load=[0.5, 0.4, 0.3],
            mem_total=65536,
            mem_used=8192,
            mem_pct=12.5
        )
        assert system.uptime_s == 86400.0
        assert len(system.load) == 3
        assert system.mem_pct == 12.5
    
    def test_alert(self):
        alert = Alert(level="warning", message="CPU 85°C", timestamp=1234567890.0)
        assert alert.level == "warning"
        assert "CPU" in alert.message


class TestSensorRegistry:
    """Test sensor registry."""
    
    def test_registry_register_get(self):
        registry = SensorRegistry()
        
        class DummySensor(BaseSensor):
            def read(self):
                return "test"
        
        sensor = DummySensor()
        registry.register("test_sensor", sensor)
        
        assert registry.get("test_sensor") is sensor
        assert registry.get("nonexistent") is None
    
    def test_registry_read_all(self):
        registry = SensorRegistry()
        
        class DummySensor(BaseSensor):
            def __init__(self, value):
                super().__init__()
                self._value = value
            def read(self):
                return self._value
        
        registry.register("s1", DummySensor("v1"))
        registry.register("s2", DummySensor("v2"))
        
        results = registry.read_all()
        assert results["s1"] == "v1"
        assert results["s2"] == "v2"


class TestWebSocketFrame:
    """Test WebSocket frame utilities."""
    
    def test_build_text_frame(self):
        frame = WebSocketFrame.build_text_frame("Hello")
        assert len(frame) > 2
        assert frame[0] & 0x80 == 0x80
        assert frame[0] & 0x0F == 1
    
    def test_build_ping_frame(self):
        frame = WebSocketFrame.build_ping_frame()
        assert frame[0] & 0x0F == 9
    
    def test_build_pong_frame(self):
        frame = WebSocketFrame.build_pong_frame()
        assert frame[0] & 0x0F == 10
    
    def test_build_close_frame(self):
        frame = WebSocketFrame.build_close_frame(1000, "Normal closure")
        assert frame[0] & 0x0F == 8
    
    def test_build_large_frame(self):
        large_data = "x" * 200
        frame = WebSocketFrame.build_text_frame(large_data)
        assert len(frame) > 200


class TestThresholds:
    """Test threshold configuration."""
    
    def test_default_thresholds(self):
        thresholds = Thresholds()
        assert thresholds.cpu_warn == 80.0
        assert thresholds.cpu_crit == 90.0
        assert thresholds.nvme_warn == 55.0
        assert thresholds.nvme_crit == 70.0
        assert thresholds.battery_warn == 20.0
        assert thresholds.battery_crit == 10.0
        assert thresholds.fan_min_rpm == 500


class TestAlertConfig:
    """Test alert configuration."""
    
    def test_default_alert_config(self):
        config = AlertConfig()
        assert config.enabled is True
        assert isinstance(config.thresholds, Thresholds)
    
    def test_custom_thresholds(self):
        thresholds = Thresholds(cpu_warn=75.0, cpu_crit=85.0)
        config = AlertConfig(enabled=False, thresholds=thresholds)
        assert config.enabled is False
        assert config.thresholds.cpu_warn == 75.0
        assert config.thresholds.cpu_crit == 85.0


class TestNodeConfig:
    """Test node configuration."""
    
    def test_default_node(self):
        node = NodeConfig(name="node1", host="192.168.1.100")
        assert node.name == "node1"
        assert node.host == "192.168.1.100"
        assert node.port == 9099
        assert node.enabled is True
        assert node.token is None
    
    def test_node_with_token(self):
        node = NodeConfig(name="node2", host="192.168.1.101", token="secret123")
        assert node.token == "secret123"


class TestClusterConfig:
    """Test cluster configuration."""
    
    def test_default_cluster(self):
        cluster = ClusterConfig()
        assert cluster.enabled is False
        assert cluster.poll_interval == 3.0
        assert cluster.nodes == []
    
    def test_cluster_with_nodes(self):
        nodes = [
            NodeConfig(name="node1", host="192.168.1.100"),
            NodeConfig(name="node2", host="192.168.1.101"),
        ]
        cluster = ClusterConfig(enabled=True, poll_interval=5.0, nodes=nodes)
        assert cluster.enabled is True
        assert cluster.poll_interval == 5.0
        assert len(cluster.nodes) == 2


class TestTLSConfig:
    """Test TLS configuration."""
    
    def test_default_tls(self):
        tls = TLSConfig()
        assert tls.enabled is False
        assert tls.cert_file == "/opt/pve-hwmonitor/cert.pem"
        assert tls.key_file == "/opt/pve-hwmonitor/key.pem"
        assert tls.auto_generate is True
    
    def test_tls_enabled(self):
        tls = TLSConfig(enabled=True, cert_file="/custom/cert.pem", key_file="/custom/key.pem")
        assert tls.enabled is True
        assert tls.cert_file == "/custom/cert.pem"


class TestSecurityConfig:
    """Test security configuration."""
    
    def test_default_security(self):
        security = SecurityConfig()
        assert security.token is None
        assert security.cors_origins == ["*"]
        assert security.rate_limit == 10
        assert security.rate_window == 1.0
        assert security.audit_log is False
    
    def test_security_with_token(self):
        security = SecurityConfig(token="my-secret-token")
        assert security.token == "my-secret-token"
    
    def test_security_cors_origins(self):
        security = SecurityConfig(cors_origins=["https://example.com", "https://app.example.com"])
        assert len(security.cors_origins) == 2
        assert "https://example.com" in security.cors_origins


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

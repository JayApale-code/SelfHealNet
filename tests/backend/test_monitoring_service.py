from backend.app.monitoring import MonitoringService
from datetime import datetime, timedelta
from types import SimpleNamespace
import socket

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.monitoring as monitoring_module
from backend.config import config
from backend.database import Base, NetworkMetric
from backend.monitoring import NetworkMonitor


def make_network_monitor():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    monitor = NetworkMonitor.__new__(NetworkMonitor)
    monitor.db = session
    return monitor, session, engine


def test_status_classification_for_normal_warning_and_critical():
    monitor = MonitoringService()

    normal = monitor.classify_status(
        latency=30,
        packet_loss=0.2,
        throughput=50,
        bandwidth_usage=40,
        link_status="up",
        cpu_usage=35,
        memory_usage=45,
    )
    assert normal == "NORMAL"

    warning = monitor.classify_status(
        latency=80,
        packet_loss=1.2,
        throughput=45,
        bandwidth_usage=77,
        link_status="degraded",
        cpu_usage=72,
        memory_usage=64,
    )
    assert warning == "WARNING"

    critical = monitor.classify_status(
        latency=180,
        packet_loss=5.0,
        throughput=18,
        bandwidth_usage=92,
        link_status="down",
        cpu_usage=92,
        memory_usage=89,
    )
    assert critical == "CRITICAL"


def test_periodic_sample_is_timestamped_and_statused():
    monitor = MonitoringService()
    record = monitor.collect_sample(
        source="h1",
        destination="h2",
        latency=20,
        packet_loss=0.1,
        throughput=70,
        bandwidth_usage=25,
        link_status="up",
        cpu_usage=30,
        memory_usage=40,
    )

    assert "timestamp" in record
    assert record["source"] == "h1"
    assert record["destination"] == "h2"
    assert record["status"] == "NORMAL"
    assert len(monitor.history) >= 1


def test_live_metric_query_excludes_stale_rows_but_history_keeps_them(monkeypatch):
    monkeypatch.setattr(config, "MONITORING_INTERVAL", 30)
    monitor, session, engine = make_network_monitor()
    now = datetime.utcnow()
    session.add_all([
        NetworkMetric(
            node_id="Wi-Fi",
            metric_type="throughput_mbps",
            value=1.5,
            unit="Mbps",
            timestamp=now - timedelta(seconds=10),
        ),
        NetworkMetric(
            node_id="Wi-Fi",
            metric_type="latency_ms",
            value=200.0,
            unit="ms",
            timestamp=now - timedelta(seconds=120),
        ),
    ])
    session.commit()

    live = monitor.get_latest_metrics(fresh_only=True)
    history = monitor.get_latest_metrics()

    assert [metric["metric_type"] for metric in live] == ["throughput_mbps"]
    assert len(history) == 2
    session.close()
    engine.dispose()


def test_network_identity_reports_fresh_latency_without_probe_target(monkeypatch):
    monkeypatch.setattr(config, "MONITORING_INTERVAL", 30)
    monkeypatch.setattr(config, "MONITORING_INTERFACE", "monitor0")
    monkeypatch.setattr(config, "MONITORING_TARGET", None)
    monkeypatch.setattr(
        NetworkMonitor,
        "detect_active_interface",
        staticmethod(lambda: {
            "name": "monitor0",
            "ip_address": "192.0.2.10",
            "status": "CONNECTED",
            "network_name": "test-network",
            "network_type": "Wi-Fi",
        }),
    )
    monitor, session, engine = make_network_monitor()
    now = datetime.utcnow()
    session.add_all([
        NetworkMetric(
            node_id="monitor0",
            metric_type="latency_ms",
            value=201.8,
            unit="ms",
            timestamp=datetime(2026, 9, 22, 10, 24, 49),
        ),
        NetworkMetric(
            node_id="monitor0",
            metric_type="latency_ms",
            value=42.5,
            unit="ms",
            timestamp=now - timedelta(seconds=10),
        ),
        NetworkMetric(
            node_id="monitor0",
            metric_type="throughput_sent_bps",
            value=1000.0,
            unit="bytes_per_second",
            timestamp=now - timedelta(seconds=10),
        ),
        NetworkMetric(
            node_id="monitor0",
            metric_type="throughput_received_bps",
            value=2000.0,
            unit="bytes_per_second",
            timestamp=now - timedelta(seconds=10),
        ),
    ])
    session.commit()

    identity = monitor.get_network_identity()

    assert identity["monitoring_status"] == "LIVE"
    assert identity["latency_ms"] == 42.5
    assert identity["latency_measured_at"] is not None
    assert identity["upload_throughput_bps"] == 1000.0
    assert identity["download_throughput_bps"] == 2000.0
    assert identity["connected_network_name"] == "test-network"
    assert identity["network_type"] == "Wi-Fi"
    session.close()
    engine.dispose()


def test_active_interface_uses_default_route_instead_of_virtual_adapter(monkeypatch):
    interfaces = {
        "vEthernet (WSL)": [SimpleNamespace(family=socket.AF_INET, address="172.20.64.1")],
        "Wi-Fi 2": [SimpleNamespace(family=socket.AF_INET, address="192.0.2.10")],
    }
    stats = {
        "vEthernet (WSL)": SimpleNamespace(isup=True),
        "Wi-Fi 2": SimpleNamespace(isup=True),
    }

    class RouteSocket:
        def connect(self, address):
            assert address == ("8.8.8.8", config.MONITORING_TARGET_PORT)

        def getsockname(self):
            return ("192.0.2.10", 0)

        def close(self):
            pass

    monkeypatch.setattr(
        monitoring_module,
        "psutil",
        SimpleNamespace(net_if_addrs=lambda: interfaces, net_if_stats=lambda: stats),
    )
    monkeypatch.setattr(monitoring_module.socket, "socket", lambda *args: RouteSocket())
    monkeypatch.setattr(NetworkMonitor, "_detect_network_name", staticmethod(lambda name, kind: "test-network"))

    detected = NetworkMonitor.detect_active_interface()

    assert detected["name"] == "Wi-Fi 2"
    assert detected["ip_address"] == "192.0.2.10"
    assert detected["network_type"] == "Wi-Fi"
    assert detected["network_name"] == "test-network"


def test_wifi_network_name_matches_selected_adapter(monkeypatch):
    output = (
        "    Name                   : Wi-Fi\n"
        "    State                  : disconnected\n"
        "    Name                   : Wi-Fi 2\n"
        "    State                  : connected\n"
        "    SSID                   : vivo Y39 5G\n"
    )
    monkeypatch.setattr(monitoring_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        monitoring_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output),
    )

    assert NetworkMonitor._detect_network_name("Wi-Fi 2", "Wi-Fi") == "vivo Y39 5G"


@pytest.mark.parametrize(
    ("system", "output", "expected"),
    [
        ("Windows", "Packets: Sent = 4, Received = 3, Lost = 1 (25% loss)", 25.0),
        ("Linux", "4 packets transmitted, 4 received, 0% packet loss", 0.0),
    ],
)
def test_packet_loss_probe_parses_measured_ping_summary(monkeypatch, system, output, expected):
    monkeypatch.setattr(monitoring_module.platform, "system", lambda: system)
    monkeypatch.setattr(
        monitoring_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=output, stderr=""),
    )

    assert NetworkMonitor._probe_packet_loss_pct("8.8.8.8") == expected


def test_host_collector_does_not_infer_packet_loss_from_interface_drops(monkeypatch):
    monitor, session, engine = make_network_monitor()
    monitor.buffer_size = 100
    monitor.metrics_buffer = []
    monitor._previous_io = None
    monitor._previous_io_at = None
    monkeypatch.setattr(config, "MONITORING_INTERFACE", "Wi-Fi")
    monkeypatch.setattr(config, "MONITORING_TARGET", None)
    monkeypatch.setattr(
        NetworkMonitor,
        "detect_active_interface",
        staticmethod(lambda: {"name": "Wi-Fi"}),
    )
    counters = SimpleNamespace(
        bytes_sent=1000,
        bytes_recv=2000,
        packets_sent=10,
        packets_recv=20,
        errin=0,
        errout=0,
        dropin=3,
        dropout=4,
    )
    monkeypatch.setattr(
        "backend.monitoring.psutil",
        SimpleNamespace(
            cpu_percent=lambda interval: 23.5,
            net_io_counters=lambda pernic: {"Wi-Fi": counters},
            net_if_stats=lambda: {"Wi-Fi": SimpleNamespace(speed=100)},
        ),
    )

    assert monitor._collect_once() == 9

    persisted = monitor.get_latest_metrics()
    cpu = next(metric for metric in persisted if metric["metric_type"] == "cpu_utilization_pct")
    assert cpu["value"] == 23.5
    assert cpu["unit"] == "%"
    assert cpu["interface_id"] == "Wi-Fi"
    assert not any(metric["metric_type"] in {"packet_loss", "packet_loss_pct"} for metric in persisted)
    session.close()
    engine.dispose()


def test_host_collector_skips_rates_after_interface_counter_reset(monkeypatch):
    monitor, session, engine = make_network_monitor()
    monitor.buffer_size = 100
    monitor.metrics_buffer = []
    monitor._previous_io = SimpleNamespace(bytes_sent=2000, bytes_recv=3000)
    monitor._previous_io_at = 5.0
    monkeypatch.setattr(config, "MONITORING_INTERFACE", "Wi-Fi")
    monkeypatch.setattr(config, "MONITORING_TARGET", None)
    monkeypatch.setattr(NetworkMonitor, "detect_active_interface", staticmethod(lambda: {"name": "Wi-Fi"}))
    counters = SimpleNamespace(
        bytes_sent=1000,
        bytes_recv=2000,
        packets_sent=10,
        packets_recv=20,
        errin=0,
        errout=0,
        dropin=0,
        dropout=0,
    )
    monkeypatch.setattr(
        "backend.monitoring.psutil",
        SimpleNamespace(
            cpu_percent=lambda interval: 20.0,
            net_io_counters=lambda pernic: {"Wi-Fi": counters},
            net_if_stats=lambda: {"Wi-Fi": SimpleNamespace(speed=100)},
        ),
    )
    monkeypatch.setattr("backend.monitoring.time.monotonic", lambda: 10.0)

    monitor._collect_once()

    metrics = monitor.get_latest_metrics()
    assert not any(metric["metric_type"].startswith("throughput_") for metric in metrics)

    counters = SimpleNamespace(
        bytes_sent=1100,
        bytes_recv=2200,
        packets_sent=11,
        packets_recv=21,
        errin=0,
        errout=0,
        dropin=0,
        dropout=0,
    )
    monkeypatch.setattr("backend.monitoring.time.monotonic", lambda: 15.0)
    monitor._collect_once()

    metrics = monitor.get_latest_metrics()
    rates = {
        metric["metric_type"]: metric["value"]
        for metric in metrics
        if metric["metric_type"].startswith("throughput_")
        or metric["metric_type"] == "bandwidth_utilization_pct"
    }
    assert rates["throughput_sent_bps"] == 20.0
    assert rates["throughput_received_bps"] == 40.0
    assert rates["throughput_mbps"] == 0.00048
    assert rates["bandwidth_utilization_pct"] == pytest.approx(0.00048)
    session.close()
    engine.dispose()

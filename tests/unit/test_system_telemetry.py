from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.monitoring as monitoring_module
from backend.api.routes import system_memory
from backend.database import Base, NetworkMetric, get_db
from backend.main import app
from backend.monitoring import NetworkMonitor


@pytest.fixture
def isolated_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_memory_endpoint_returns_recent_persisted_measurements(isolated_session):
    values = {
        "memory_total_mb": (8192.0, "MB"),
        "memory_used_mb": (4096.0, "MB"),
        "memory_available_mb": (4096.0, "MB"),
        "memory_utilization_pct": (50.0, "%"),
    }
    for metric_type, (value, unit) in values.items():
        isolated_session.add(NetworkMetric(
            node_id="host",
            metric_type=metric_type,
            value=value,
            unit=unit,
            timestamp=datetime.utcnow(),
        ))
    isolated_session.commit()

    response = system_memory(isolated_session)

    assert response["status"] == "available"
    assert response["total_mb"] == 8192.0
    assert response["used_mb"] == 4096.0
    assert response["available_mb"] == 4096.0
    assert response["usage_pct"] == 50.0
    assert response["timestamp"] is not None
    assert response["reason"] is None


def test_memory_endpoint_reports_missing_measurements_without_zero_fallback(isolated_session):
    response = system_memory(isolated_session)

    assert response["status"] == "unavailable"
    assert response["usage_pct"] is None
    assert response["total_mb"] is None
    assert "incomplete" in response["reason"]


def test_collector_persists_actual_psutil_memory_fields(monkeypatch, isolated_session):
    fake_memory = SimpleNamespace(
        total=8 * 1024 ** 3,
        used=3 * 1024 ** 3,
        available=5 * 1024 ** 3,
        percent=37.5,
    )
    fake_counter = SimpleNamespace(
        bytes_sent=100,
        bytes_recv=200,
        packets_sent=1,
        packets_recv=2,
        errin=0,
        errout=0,
        dropin=0,
        dropout=0,
    )
    fake_psutil = SimpleNamespace(
        cpu_percent=lambda interval: 12.5,
        virtual_memory=lambda: fake_memory,
        net_io_counters=lambda pernic: {"Ethernet0": fake_counter},
    )
    monkeypatch.setattr(monitoring_module, "psutil", fake_psutil)
    monkeypatch.setattr(monitoring_module.config, "MONITORING_INTERFACE", "Ethernet0")
    monkeypatch.setattr(monitoring_module.config, "MONITORING_TARGET", None)
    monitor = NetworkMonitor.__new__(NetworkMonitor)
    monitor.db = isolated_session
    monitor.metrics_buffer = []
    monitor.buffer_size = 100
    monitor._previous_io = None
    monitor._previous_io_at = None

    monitor._collect_once()

    rows = {
        metric.metric_type: (metric.value, metric.unit)
        for metric in isolated_session.query(NetworkMetric).all()
    }
    assert rows["memory_total_mb"] == (8589.934592, "MB")
    assert rows["memory_used_mb"] == (3221.225472, "MB")
    assert rows["memory_available_mb"] == (5368.70912, "MB")
    assert rows["memory_utilization_pct"] == (37.5, "%")


def test_collector_logs_memory_failure_without_fabricating_values(monkeypatch, isolated_session, caplog):
    def unavailable_memory():
        raise OSError("memory counters unavailable")

    monkeypatch.setattr(
        monitoring_module,
        "psutil",
        SimpleNamespace(
            cpu_percent=lambda interval: 12.5,
            virtual_memory=unavailable_memory,
            net_io_counters=lambda pernic: {},
        ),
    )
    monkeypatch.setattr(monitoring_module.config, "MONITORING_INTERFACE", "Ethernet0")
    monitor = NetworkMonitor.__new__(NetworkMonitor)
    monitor.db = isolated_session
    monitor.metrics_buffer = []
    monitor.buffer_size = 100
    monitor._previous_io = None
    monitor._previous_io_at = None

    monitor._collect_once()

    stored_types = {
        metric.metric_type
        for metric in isolated_session.query(NetworkMetric).all()
    }
    assert "cpu_utilization_pct" in stored_types
    assert not any(metric_type.startswith("memory_") for metric_type in stored_types)
    assert "System memory metric collection failed" in caplog.text


def test_memory_api_returns_live_host_psutil_measurement(monkeypatch, isolated_session):
    psutil_module = monitoring_module.psutil
    memory_sample = psutil_module.virtual_memory()
    monkeypatch.setattr(psutil_module, "cpu_percent", lambda interval: 0.0)
    monkeypatch.setattr(psutil_module, "virtual_memory", lambda: memory_sample)
    monkeypatch.setattr(monitoring_module.config, "MONITORING_INTERFACE", None)
    monkeypatch.setattr(monitoring_module.config, "MONITORING_TARGET", None)
    monitor = NetworkMonitor.__new__(NetworkMonitor)
    monitor.db = isolated_session
    monitor.metrics_buffer = []
    monitor.buffer_size = 100
    monitor._previous_io = None
    monitor._previous_io_at = None
    monitor._collect_once()

    def override_get_db():
        yield isolated_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/api/v1/system/memory")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["total_mb"] == pytest.approx(memory_sample.total / 1_000_000)
    assert body["used_mb"] == pytest.approx(memory_sample.used / 1_000_000)
    assert body["available_mb"] == pytest.approx(memory_sample.available / 1_000_000)
    assert body["usage_pct"] == pytest.approx(memory_sample.percent)

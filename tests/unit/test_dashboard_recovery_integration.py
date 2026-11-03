from collections.abc import Iterator

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import config
from backend.main import app
from backend.api import routes
from backend.database import (
    AlertRecord,
    Base,
    NetworkIncident,
    NetworkMetric,
    NotificationRecord,
    RecoveryAttempt,
    RecoveryRecord,
    User,
    get_db,
)
from backend.monitoring import NetworkMonitor
from ml.predict import predict_from_record


@pytest.fixture
def isolated_api(monkeypatch) -> Iterator[tuple[TestClient, sessionmaker]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    monitor_session = test_session()
    test_monitor = NetworkMonitor.__new__(NetworkMonitor)
    test_monitor.db = monitor_session
    monkeypatch.setattr(routes, "monitor", test_monitor)
    app.dependency_overrides[get_db] = override_get_db
    routes.state.metrics = []
    routes.state.predictions = []
    routes.state.incidents = []
    routes.state.faults = []
    routes.state.recovery_status = {"status": "idle", "active_recovery": None}
    try:
        yield TestClient(app), test_session
    finally:
        app.dependency_overrides.pop(get_db, None)
        monitor_session.close()
        engine.dispose()


def register_and_login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Operator",
            "username": "dashboard-operator",
            "email": "dashboard-operator@example.test",
            "mobile_number": "1234567890",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_dashboard_feed_endpoints_return_persisted_backend_records(isolated_api):
    client, test_session = isolated_api
    headers = register_and_login(client)

    prediction = client.post(
        "/api/v1/predictions",
        json={"label": "CONGESTION", "probability": 0.91, "component": "edge-1"},
    )
    assert prediction.status_code == 201, prediction.text
    incident = client.post(
        "/api/v1/incidents",
        json={
            "incident_id": "INC-TEST-1",
            "detected_fault": "CONGESTION",
            "affected_component": "edge-1",
            "confidence": 0.91,
            "severity": "high",
            "final_status": "ESCALATED",
        },
    )
    assert incident.status_code == 201, incident.text

    with test_session() as session:
        user = session.query(User).filter_by(username="dashboard-operator").one()
        session.add_all([
            AlertRecord(alert_type="test", severity="high", message="Test alert"),
            NotificationRecord(
                user_id=user.id,
                type="test",
                severity="high",
                message="Test notification",
            ),
        ])
        session.commit()

    routes.state.predictions = []
    routes.state.incidents = []
    assert client.get("/api/v1/predictions").json()["predictions"][0]["label"] == "CONGESTION"
    assert client.get("/api/v1/incidents").json()["incidents"][0]["incident_id"] == "INC-TEST-1"
    assert client.get("/api/v1/alerts").status_code == 401
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.get("/api/v1/alerts", headers=headers).json()["alerts"][0]["message"] == "Test alert"
    assert client.get("/api/v1/notifications", headers=headers).json()["notifications"][0]["message"] == "Test notification"


def test_diagnosis_persists_real_fault_and_supplied_prediction(isolated_api):
    client, test_session = isolated_api

    response = client.post(
        "/api/v1/diagnosis",
        json={
            "live_metrics": {"latency_ms": 120, "packet_loss_pct": 4},
            "ml_prediction": {"label": "CONGESTION", "probability": 0.91},
            "affected_node": "edge-1",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["fault_type"] == "CONGESTION"
    assert result["incident_id"]

    incident_feed = client.get("/api/v1/incidents").json()
    prediction_feed = client.get("/api/v1/predictions").json()
    assert incident_feed["incidents"][0]["incident_id"] == result["incident_id"]
    assert incident_feed["incidents"][0]["selected_action"] is None
    assert incident_feed["incidents"][0]["safety_result"] is None
    assert prediction_feed["predictions"][0]["label"] == "CONGESTION"
    assert prediction_feed["predictions"][0]["probability"] == 0.91
    assert prediction_feed["predictions"][0]["component"] == "edge-1"

    with test_session() as session:
        assert session.query(NetworkIncident).count() == 1
        assert session.query(RecoveryRecord).count() == 0
        assert session.query(RecoveryAttempt).count() == 0


def test_ml_input_does_not_replace_unmeasured_fields_with_zero():
    model_input = routes._ml_input({
        "latency_ms": 121.7967,
        "cpu_utilization_pct": 32.1,
    })

    assert model_input["latency_ms"] == 121.7967
    assert model_input["cpu_utilization_pct"] == 32.1
    assert model_input["throughput_mbps"] is None
    assert model_input["packet_loss_pct"] is None
    assert model_input["link_status"] is None
    assert model_input["route_redundancy"] is None


def test_model_accepts_live_input_with_unmeasured_fields():
    prediction = predict_from_record(routes._ml_input({
        "latency_ms": 121.7967,
        "cpu_utilization_pct": 32.1,
    }))

    assert prediction["label"] in {
        "CONGESTION",
        "CONNECTIVITY_FAILURE",
        "LINK_FAILURE",
        "NORMAL",
        "SERVICE_DEGRADATION",
    }
    assert 0 <= prediction["probability"] <= 1


def test_normal_diagnosis_does_not_create_incident(isolated_api):
    client, test_session = isolated_api

    response = client.post(
        "/api/v1/diagnosis",
        json={
            "live_metrics": {
                "latency_ms": 10,
                "packet_loss_pct": 0,
                "throughput_mbps": 50,
                "route_redundancy": 1,
                "connectivity_score": 1,
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["fault_type"] == "NORMAL"
    assert "incident_id" not in response.json()
    assert client.get("/api/v1/incidents").json()["count"] == 0
    with test_session() as session:
        assert session.query(NetworkIncident).count() == 0


def test_recovery_status_is_empty_until_a_recovery_intent_is_persisted(isolated_api):
    client, test_session = isolated_api

    empty_status = client.get("/api/v1/recovery/status").json()
    assert empty_status == {"status": "idle", "active_recovery": None}
    assert client.get("/api/v1/incidents").json() == {"incidents": [], "count": 0}
    assert client.get("/api/v1/predictions").json() == {"predictions": [], "count": 0}
    assert client.get("/api/v1/metrics/live").json() == {"metrics": [], "count": 0}

    response = client.post(
        "/api/v1/recovery/actions",
        json={
            "action": "APPLY_QOS",
            "target": "edge-1",
            "parameters": {"class": "critical"},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"

    persisted_status = client.get("/api/v1/recovery/status").json()
    active = persisted_status["active_recovery"]
    assert persisted_status["status"] == "pending"
    assert active["status"] == "pending"
    assert active["recommended_action"] == "APPLY_QOS"
    assert active["safety_check"] == "pending"
    assert active["attempts"] == []

    with test_session() as session:
        record = session.query(RecoveryRecord).one()
        assert record.status == "pending"
        assert record.result == "pending"
        assert session.query(RecoveryAttempt).count() == 0
        assert session.query(NetworkIncident).count() == 0


def test_network_status_reports_unavailable_without_fresh_metrics(isolated_api):
    client, test_session = isolated_api
    with test_session() as session:
        session.add(NetworkMetric(
            node_id="Wi-Fi",
            interface_id="Wi-Fi",
            metric_type="cpu_utilization_pct",
            value=15.1,
            unit="%",
            timestamp=datetime.utcnow() - timedelta(seconds=120),
        ))
        session.commit()

    live = client.get("/api/v1/metrics/live").json()
    status = client.get("/api/v1/network/status").json()

    assert live == {"metrics": [], "count": 0}
    assert status["status"] == "unknown"
    assert status["last_metric_at"] is None


def test_network_status_reports_fresh_persisted_metric(isolated_api):
    client, test_session = isolated_api
    measured_at = datetime.utcnow()
    with test_session() as session:
        session.add(NetworkMetric(
            node_id="Wi-Fi",
            interface_id="Wi-Fi",
            metric_type="cpu_utilization_pct",
            value=15.1,
            unit="%",
            timestamp=measured_at,
        ))
        session.commit()

    live = client.get("/api/v1/metrics/live").json()
    status = client.get("/api/v1/network/status").json()

    assert live["count"] == 1
    assert live["metrics"][0]["value"] == 15.1
    assert status["status"] == "healthy"
    assert status["last_metric_at"] == measured_at.isoformat()


def test_recovery_workflow_is_blocked_without_verified_real_transport(isolated_api, monkeypatch):
    client, test_session = isolated_api
    headers = register_and_login(client)
    monkeypatch.setattr(config, "SDN_CONTROLLER_URL", "http://controller.example:8080")
    monkeypatch.setattr(
        routes,
        "predict_from_record",
        lambda _record: {"label": "LINK_FAILURE", "probability": 0.99},
    )
    monkeypatch.setattr(
        routes.safety_checker,
        "validate_action",
        lambda *_args, **_kwargs: {"safe": True, "administrator_alert": None},
    )

    class DisconnectedController:
        @staticmethod
        def has_real_connection():
            return False

    class NoExecutionOrchestrator:
        def __init__(self, **_kwargs):
            self.sdn_controller = DisconnectedController()

        @staticmethod
        def execute_with_fallback(**_kwargs):
            raise AssertionError("Blocked workflow must not attempt controller execution")

    monkeypatch.setattr(routes, "RecoveryOrchestrator", NoExecutionOrchestrator)
    response = client.post(
        "/api/v1/recovery/workflow",
        headers=headers,
        json={
            "live_metrics": {"latency_ms": 120, "packet_loss_pct": 4},
            "affected_component": "edge-1",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["recovery"]["status"] == "blocked"
    assert result["recovery"]["reason"] == (
        "SDN Controller NOT_CONFIGURED: Set SDN_CONTROLLER_URL to the Ryu REST API base URL."
    )
    assert result["recovery"]["actions_executed"] == []
    assert result["verification"]["verified"] is False
    assert result["verification"]["result"] == "RECOVERY_FAILED"
    assert result["fallback"]["status"] == "blocked"

    routes.state.recovery_status = {"status": "idle", "active_recovery": None}
    persisted_status = client.get("/api/v1/recovery/status").json()
    assert persisted_status["status"] == "escalated"
    assert persisted_status["active_recovery"]["result"] == "RECOVERY_FAILED"
    assert len(persisted_status["active_recovery"]["attempts"]) == 1
    assert persisted_status["active_recovery"]["attempts"][0]["status"] == "blocked"
    assert persisted_status["active_recovery"]["attempts"][0]["recovery_actions"] == []
    assert persisted_status["active_recovery"]["attempts"][0]["success"] is False
    assert persisted_status["active_recovery"]["attempts"][0]["verified"] is False

    incident = client.get("/api/v1/incidents").json()["incidents"][0]
    assert incident["selected_action"] == result["decision"]["selected_action"]
    assert incident["safety_result"]["safe"] is True
    assert incident["recovery_result"]["status"] == "blocked"
    assert incident["verification_metrics"]["result"] == "RECOVERY_FAILED"
    assert incident["verification_metrics"]["verified"] is False

    with test_session() as session:
        attempt = session.query(RecoveryAttempt).one()
        recovery_record = session.query(RecoveryRecord).one()
        incident_row = session.query(NetworkIncident).one()
        assert attempt.status == "blocked"
        assert attempt.success is False
        assert attempt.verified is False
        assert attempt.safety_check_passed is True
        assert attempt.recovery_actions == []
        assert recovery_record.safety_check == "passed"
        assert recovery_record.result == "RECOVERY_FAILED"
        assert recovery_record.status == "escalated"
        assert incident_row.selected_action == result["decision"]["selected_action"]
        assert incident_row.safety_result["safe"] is True
        assert incident_row.recovery_result["status"] == "blocked"


def test_safety_gate_block_is_persisted_without_execution(isolated_api, monkeypatch):
    client, test_session = isolated_api
    headers = register_and_login(client)
    monkeypatch.setattr(
        routes,
        "predict_from_record",
        lambda _record: {"label": "LINK_FAILURE", "probability": 0.99},
    )
    safety_result = {
        "safe": False,
        "administrator_alert": ["Action requires an unavailable alternate path"],
    }
    monkeypatch.setattr(
        routes.safety_checker,
        "validate_action",
        lambda *_args, **_kwargs: safety_result,
    )

    class ConnectedController:
        @staticmethod
        def has_real_connection():
            return True

    class NoExecutionOrchestrator:
        def __init__(self, **_kwargs):
            self.sdn_controller = ConnectedController()

        @staticmethod
        def execute_with_fallback(**_kwargs):
            raise AssertionError("Safety-rejected workflow must not execute an action")

    monkeypatch.setattr(routes, "RecoveryOrchestrator", NoExecutionOrchestrator)
    response = client.post(
        "/api/v1/recovery/workflow",
        headers=headers,
        json={
            "live_metrics": {"latency_ms": 120, "packet_loss_pct": 4},
            "affected_component": "edge-1",
        },
    )

    assert response.status_code == 201, response.text
    workflow = response.json()
    assert workflow["safety"] == safety_result
    assert workflow["recovery"]["status"] == "blocked"
    assert workflow["recovery"]["actions_executed"] == []
    assert workflow["verification"]["result"] == "RECOVERY_FAILED"
    assert workflow["verification"]["verified"] is False

    with test_session() as session:
        incident = session.query(NetworkIncident).one()
        recovery = session.query(RecoveryRecord).one()
        attempt = session.query(RecoveryAttempt).one()
        assert incident.selected_action == workflow["decision"]["selected_action"]
        assert incident.safety_result == safety_result
        assert incident.recovery_result["status"] == "blocked"
        assert recovery.safety_check == "failed"
        assert recovery.result == "RECOVERY_FAILED"
        assert recovery.status == "escalated"
        assert attempt.status == "blocked"
        assert attempt.safety_check_passed is False
        assert attempt.success is False
        assert attempt.verified is False
        assert attempt.recovery_actions == []

    incident_feed = client.get("/api/v1/incidents").json()["incidents"][0]
    assert incident_feed["selected_action"] == workflow["decision"]["selected_action"]
    assert incident_feed["safety_result"]["safe"] is False
    assert incident_feed["recovery_result"]["status"] == "blocked"
    recovery_feed = client.get("/api/v1/recovery/status").json()["active_recovery"]
    assert recovery_feed["status"] == "escalated"
    assert recovery_feed["safety_check"] == "failed"
    assert recovery_feed["result"] == "RECOVERY_FAILED"
    assert recovery_feed["attempts"][0]["status"] == "blocked"
    assert recovery_feed["attempts"][0]["success"] is False
    assert recovery_feed["attempts"][0]["verified"] is False
    assert recovery_feed["attempts"][0]["recovery_actions"] == []


def test_websocket_snapshot_reads_fresh_persisted_metrics(isolated_api):
    client, test_session = isolated_api
    headers = register_and_login(client)
    with test_session() as session:
        session.add(NetworkMetric(
            node_id="Wi-Fi",
            interface_id="Wi-Fi",
            metric_type="throughput_mbps",
            value=1.25,
            unit="Mbps",
            timestamp=datetime.utcnow(),
        ))
        session.commit()

    with client.websocket_connect("/api/v1/ws/dashboard") as websocket:
        websocket.send_json({"type": "authenticate", "token": headers["Authorization"].removeprefix("Bearer ")})
        assert websocket.receive_json() == {"type": "authenticated"}
        snapshot = websocket.receive_json()

    assert snapshot["live_metrics"][0]["metric_type"] == "throughput_mbps"
    assert snapshot["live_metrics"][0]["value"] == 1.25
    assert snapshot["network_status"]["last_metric_at"] == snapshot["live_metrics"][0]["timestamp"]
    assert snapshot["network_status"]["status"] == "healthy"


def test_websocket_snapshot_marks_stale_metrics_unavailable(isolated_api):
    client, test_session = isolated_api
    headers = register_and_login(client)
    with test_session() as session:
        session.add(NetworkMetric(
            node_id="Wi-Fi",
            interface_id="Wi-Fi",
            metric_type="cpu_utilization_pct",
            value=15.1,
            unit="%",
            timestamp=datetime.utcnow() - timedelta(seconds=120),
        ))
        session.commit()

    with client.websocket_connect("/api/v1/ws/dashboard") as websocket:
        websocket.send_json({
            "type": "authenticate",
            "token": headers["Authorization"].removeprefix("Bearer "),
        })
        assert websocket.receive_json() == {"type": "authenticated"}
        snapshot = websocket.receive_json()

    assert snapshot["live_metrics"] == []
    assert snapshot["network_status"]["status"] == "unknown"
    assert snapshot["network_status"]["last_metric_at"] is None


def test_dashboard_websocket_rejects_missing_or_invalid_auth(isolated_api):
    client, _ = isolated_api
    with client.websocket_connect("/api/v1/ws/dashboard") as websocket:
        websocket.send_json({"type": "authenticate", "token": "invalid-token"})
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()
    assert closed.value.code == 4401


def test_metric_apis_return_persisted_latency_and_throughput(isolated_api, monkeypatch):
    client, test_session = isolated_api
    now = datetime.utcnow()
    measurements = [
        NetworkMetric(
            node_id="monitor0",
            interface_id="monitor0",
            metric_type="latency_ms",
            value=42.5,
            unit="ms",
            timestamp=now,
        ),
        NetworkMetric(
            node_id="monitor0",
            interface_id="monitor0",
            metric_type="throughput_mbps",
            value=1.25,
            unit="Mbps",
            timestamp=now,
        ),
        NetworkMetric(
            node_id="monitor0",
            interface_id="monitor0",
            metric_type="throughput_sent_bps",
            value=400.0,
            unit="bytes_per_second",
            timestamp=now,
        ),
        NetworkMetric(
            node_id="monitor0",
            interface_id="monitor0",
            metric_type="throughput_received_bps",
            value=900.0,
            unit="bytes_per_second",
            timestamp=now,
        ),
    ]
    with test_session() as session:
        session.add_all(measurements)
        session.commit()

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
            "network_type": "Ethernet",
        }),
    )
    with test_session() as monitor_db:
        test_monitor = NetworkMonitor.__new__(NetworkMonitor)
        test_monitor.db = monitor_db
        monkeypatch.setattr(routes, "monitor", test_monitor)

        live = client.get("/api/v1/metrics/live").json()
        history = client.get("/api/v1/metrics/history?node_id=monitor0").json()
        network_info = client.get("/api/v1/network/info").json()

    live_values = {item["metric_type"]: item["value"] for item in live["metrics"]}
    history_values = {item["metric_type"]: item["value"] for item in history["metrics"]}
    assert live_values["latency_ms"] == 42.5
    assert live_values["throughput_mbps"] == 1.25
    assert history_values["throughput_sent_bps"] == 400.0
    assert history_values["throughput_received_bps"] == 900.0
    assert network_info["latency_ms"] == 42.5
    assert network_info["upload_throughput_bps"] == 400.0
    assert network_info["download_throughput_bps"] == 900.0


def test_recovery_workflow_persists_and_returns_actual_execution_attempts(isolated_api, monkeypatch):
    client, test_session = isolated_api
    headers = register_and_login(client)
    monkeypatch.setattr(config, "SDN_CONTROLLER_URL", "http://controller.example:8080")
    monkeypatch.setattr(
        routes,
        "predict_from_record",
        lambda _record: {"label": "LINK_FAILURE", "probability": 0.99},
    )
    monkeypatch.setattr(
        routes.safety_checker,
        "validate_action",
        lambda *_args, **_kwargs: {"safe": True, "administrator_alert": None},
    )

    class ConnectedController:
        write_operations_enabled = True

        @staticmethod
        def has_real_connection():
            return True

    class AttemptingOrchestrator:
        def __init__(self, **_kwargs):
            self.sdn_controller = ConnectedController()

        @staticmethod
        def execute_with_fallback(**_kwargs):
            return {
                "status": "ESCALATED",
                "attempts": [{
                    "attempt": 1,
                    "strategy": "REROUTE_TRAFFIC",
                    "execution": {
                        "status": "failed",
                        "actions_executed": [],
                        "errors": [{"error": "controller rejected action"}],
                    },
                    "verification": {"success": False, "verified": False},
                }],
            }

    monkeypatch.setattr(routes, "RecoveryOrchestrator", AttemptingOrchestrator)
    response = client.post(
        "/api/v1/recovery/workflow",
        headers=headers,
        json={
            "live_metrics": {"latency_ms": 120, "throughput_mbps": 20, "link_status": "down"},
            "affected_component": "edge-1",
            "network_state": {"alternate_path_available": True},
        },
    )
    assert response.status_code == 201, response.text
    workflow = response.json()

    with test_session() as session:
        incident = session.query(NetworkIncident).one()
        recovery_record = session.query(RecoveryRecord).one()
        attempt = session.query(RecoveryAttempt).one()
        assert incident.selected_action
        assert incident.safety_result["safe"] is True
        assert recovery_record.status == "escalated"
        assert recovery_record.result == "RECOVERY_FAILED"
        assert attempt.incident_id == incident.id
        assert attempt.strategy_name == "REROUTE_TRAFFIC"
        assert attempt.status == "failed"
        assert attempt.success is False
        assert attempt.verified is False
        assert attempt.verification_metrics["verified"] is False

    persisted = client.get("/api/v1/recovery/status").json()
    assert persisted["active_recovery"]["attempts"][0]["strategy_name"] == "REROUTE_TRAFFIC"
    assert persisted["active_recovery"]["attempts"][0]["verified"] is False
    assert persisted["active_recovery"]["attempts"][0]["status"] == "failed"
    assert persisted["active_recovery"]["attempts"][0]["success"] is False
    assert persisted["active_recovery"]["result"] == "RECOVERY_FAILED"
    incident_feed = client.get("/api/v1/incidents").json()["incidents"][0]
    assert incident_feed["selected_action"] == workflow["decision"]["selected_action"]
    assert incident_feed["safety_result"]["safe"] is True
    assert incident_feed["recovery_result"]["attempts"][0]["execution"]["status"] == "failed"
    assert incident_feed["verification_metrics"]["verified"] is False
    prediction_feed = client.get("/api/v1/predictions").json()["predictions"][0]
    assert prediction_feed["label"] == "LINK_FAILURE"
    assert prediction_feed["component"] == "edge-1"


def test_dashboard_websocket_uses_persisted_recovery_status(isolated_api):
    client, test_session = isolated_api
    headers = register_and_login(client)
    with test_session() as session:
        incident = NetworkIncident(
            incident_id="INC-RECOVERY-STATUS",
            incident_type="CONGESTION",
            affected_node="edge-1",
            affected_component="edge-1",
            description="Measured congestion",
        )
        session.add(incident)
        session.flush()
        session.add(RecoveryRecord(
            recovery_id="REC-STATUS",
            fault_id=incident.incident_id,
            status="escalated",
            result="RECOVERY_FAILED",
            verification={"verified": False},
        ))
        session.commit()

    routes.state.recovery_status = {"status": "idle", "active_recovery": None}
    with client.websocket_connect("/api/v1/ws/dashboard") as websocket:
        websocket.send_json({"type": "authenticate", "token": headers["Authorization"].removeprefix("Bearer ")})
        assert websocket.receive_json() == {"type": "authenticated"}
        snapshot = websocket.receive_json()

    assert snapshot["recovery_status"]["status"] == "escalated"
    assert snapshot["recovery_status"]["active_recovery"]["recovery_id"] == "REC-STATUS"

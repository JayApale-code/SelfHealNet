from fastapi.testclient import TestClient

from backend.main import app
from backend.api.routes import state
from backend.config import config
from backend.database import reset_database


client = TestClient(app)


def setup_function():
    reset_database()
    state.metrics.clear()
    state.faults.clear()
    state.predictions.clear()
    state.incidents.clear()
    state.recovery_actions.clear()
    state.recovery_status = {"status": "idle", "active_recovery": None}
    state.topology = {"nodes": [], "links": []}


def test_status_metrics_topology_history_and_model_endpoints(monkeypatch):
    monkeypatch.setattr(config, "SDN_SIMULATION_ENABLED", True)
    assert client.get("/api/v1/network/status").status_code == 200
    metric = client.post(
        "/api/v1/metrics/live",
        json={"node_id": "router-1", "metric_type": "latency_ms", "value": 42, "unit": "ms"},
    )
    assert metric.status_code == 201
    assert client.get("/api/v1/metrics/live").json()["count"] == 1
    assert client.get("/api/v1/metrics/history?node_id=router-1").json()["count"] == 1
    assert client.put("/api/v1/topology", json={"nodes": ["router-1"], "links": []}).status_code == 200
    assert client.get("/api/v1/topology").json()["nodes"] == ["router-1"]
    assert client.get("/api/v1/ml/model").status_code == 200


def test_empty_active_faults_are_reported_as_clear():
    response = client.get("/api/v1/faults/active")

    assert response.status_code == 200
    assert response.json() == {"faults": [], "count": 0}


def test_diagnosis_and_recovery_endpoints_validate_and_update_state():
    diagnosis = client.post(
        "/api/v1/diagnosis",
        json={
            "live_metrics": {"latency_ms": 120, "packet_loss_pct": 4, "bandwidth_utilization_pct": 94},
            "ml_prediction": {"label": "CONGESTION", "probability": 0.9},
            "topology": {"nodes": ["router-1"], "links": []},
            "affected_node": "router-1",
        },
    )
    assert diagnosis.status_code == 200
    assert diagnosis.json()["fault_type"] == "CONGESTION"
    assert client.get("/api/v1/faults/active").json()["count"] == 1
    action = client.post("/api/v1/recovery/actions", json={"action": "APPLY_QOS", "target": "router-1"})
    assert action.status_code == 201
    assert client.get("/api/v1/recovery/status").json()["status"] == "pending"


def test_invalid_payloads_return_validation_errors():
    response = client.post("/api/v1/metrics/live", json={"node_id": "", "metric_type": "latency_ms", "value": 1})
    assert response.status_code == 422
    topology = client.put("/api/v1/topology", json={"nodes": "router-1", "links": []})
    assert topology.status_code == 422


def test_dashboard_websocket_sends_live_snapshot():
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Dashboard Test",
            "username": "dashboard-test",
            "email": "dashboard-test@example.test",
            "mobile_number": "1234567890",
            "password": "dashboard-test-password",
        },
    )
    assert registration.status_code == 201, registration.text

    with client.websocket_connect("/api/v1/ws/dashboard") as websocket:
        websocket.send_json({"token": registration.json()["token"]})
        assert websocket.receive_json() == {"type": "authenticated"}
        snapshot = websocket.receive_json()
        assert "network_status" in snapshot
        websocket.send_text("ping")
        assert "live_metrics" in websocket.receive_json()

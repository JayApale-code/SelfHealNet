from unittest.mock import Mock

import requests

from backend.api import routes
from backend.config import config
from sdn_controller.ryu_adapter import RyuControllerAdapter


class FakeResponse:
    def __init__(self, payload=None, status_code=200, invalid_json=False):
        self.payload = payload
        self.status_code = status_code
        self.invalid_json = invalid_json

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        if self.invalid_json:
            raise ValueError("invalid JSON")
        return self.payload


def make_adapter(payloads):
    session = Mock()

    def get(url, **kwargs):
        path = url.removeprefix("http://controller:8080")
        value = payloads[path]
        if isinstance(value, Exception):
            raise value
        return value

    session.get.side_effect = get
    return RyuControllerAdapter("http://controller:8080", session=session), session


def connected_payloads():
    return {
        "/stats/switches": FakeResponse([1]),
        "/healthz": FakeResponse({
            "controller": "os-ken-lab",
            "automatic_recovery": {
                "enabled": True,
                "attempts": 1,
                "last_result": "verified",
            },
        }),
        "/stats/port/1": FakeResponse({"1": [{"port_no": 1, "rx_bytes": 512}]}),
        "/stats/portdesc/1": FakeResponse({"1": [{"port_no": 1, "name": "s1-eth1", "config": 0, "state": 4}]}),
        "/stats/flow/1": FakeResponse({"1": [{"priority": 10, "packet_count": 7}]}),
        "/v1.0/topology/switches": FakeResponse([
            {"dpid": "1", "ports": [{"port_no": 1, "name": "s1-eth1"}]},
        ]),
        "/v1.0/topology/links": FakeResponse([
            {
                "src": {"dpid": "1", "port_no": 1},
                "dst": {"dpid": "2", "port_no": 3},
            },
        ]),
    }


def test_connected_ryu_rest_api_returns_switch_topology_ports_and_flows():
    adapter, session = make_adapter(connected_payloads())

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "CONNECTED"
    assert snapshot["source"] == "ryu_rest_api"
    assert snapshot["timestamp"] == snapshot["last_check_at"]
    assert snapshot["topology"]["nodes"] == [
        {"id": "1", "type": "switch", "ports": [{"port_no": 1, "name": "s1-eth1"}]},
    ]
    assert snapshot["topology"]["links"] == [
        {"source": "1", "source_port": 1, "target": "2", "target_port": 3},
    ]
    assert snapshot["switches"][0]["ports"][0]["rx_bytes"] == 512
    assert snapshot["switches"][0]["ports"][0]["available"] is True
    assert snapshot["switches"][0]["ports"][0]["admin_state"] == "ENABLED"
    assert snapshot["switches"][0]["ports"][0]["link_state"] == "UP"
    assert snapshot["switches"][0]["ports"][0]["forwarding_state"] == "NOT_BLOCKED"
    assert snapshot["environment_ready"] is True
    assert snapshot["switches"][0]["flow_count"] == 1
    assert snapshot["flow_count"] == 1
    assert snapshot["last_check_at"]
    requested_paths = {call.args[0].removeprefix("http://controller:8080") for call in session.get.call_args_list}
    assert requested_paths == {
        "/stats/switches",
        "/stats/port/1",
        "/stats/portdesc/1",
        "/stats/flow/1",
        "/v1.0/topology/switches",
        "/v1.0/topology/links",
    }
    assert all(call.kwargs["timeout"] == 2 for call in session.get.call_args_list)


def test_os_ken_lab_rest_api_reports_distinct_source():
    _, session = make_adapter(connected_payloads())
    adapter = RyuControllerAdapter(
        "http://controller:8080",
        session=session,
        controller_type="os_ken_lab",
    )

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "CONNECTED"
    assert snapshot["source"] == "os_ken_lab_rest_api"
    assert snapshot["write_operations_enabled"] is False
    assert snapshot["automatic_recovery_enabled"] is True
    assert snapshot["automatic_recovery"]["last_result"] == "verified"
    assert snapshot["mode"] == "read-only+mininet-lab-auto-recovery"
    assert any(
        call.args[0].endswith("/healthz")
        for call in session.get.call_args_list
    )


def test_unconfigured_controller_does_not_attempt_network_request():
    session = Mock()

    snapshot = RyuControllerAdapter(None, session=session).snapshot()

    assert snapshot["status"] == "NOT_CONFIGURED"
    assert snapshot["source"] == "none"
    assert snapshot["topology"] == {"nodes": [], "links": []}
    assert "SDN_CONTROLLER_URL" in snapshot["error"]
    session.get.assert_not_called()


def test_partial_credentials_are_rejected_without_network_request():
    session = Mock()

    snapshot = RyuControllerAdapter(
        "http://controller:8080",
        username="user",
        session=session,
    ).snapshot()

    assert snapshot["status"] == "DISCONNECTED"
    assert "Set both SDN_CONTROLLER_USERNAME" in snapshot["error"]
    session.get.assert_not_called()


def test_connection_failure_is_reported_as_disconnected():
    adapter, _ = make_adapter({
        "/stats/switches": requests.ConnectionError("connection refused"),
    })

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "DISCONNECTED"
    assert snapshot["topology"] == {"nodes": [], "links": []}
    assert "Could not connect" in snapshot["error"]


def test_timeout_is_reported_as_disconnected():
    adapter, _ = make_adapter({
        "/stats/switches": requests.Timeout("slow controller"),
    })

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "DISCONNECTED"
    assert "Timed out" in snapshot["error"]


def test_timeout_and_controller_url_are_configurable():
    session = Mock()
    session.get.side_effect = requests.Timeout("slow controller")
    adapter = RyuControllerAdapter("http://controller:8081/", timeout_seconds=4.5, session=session)

    snapshot = adapter.snapshot()

    assert snapshot["controller_url"] == "http://controller:8081"
    assert session.get.call_args.kwargs["timeout"] == 4.5
    assert snapshot["status"] == "DISCONNECTED"


def test_malformed_core_response_is_not_marked_connected():
    adapter, _ = make_adapter({
        "/stats/switches": FakeResponse({"switches": []}),
    })

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "DISCONNECTED"
    assert "unexpected response shape" in snapshot["error"]


def test_empty_switch_list_means_controller_connected_but_no_switches():
    adapter, _ = make_adapter({
        "/stats/switches": FakeResponse([]),
        "/v1.0/topology/switches": FakeResponse([]),
        "/v1.0/topology/links": FakeResponse([]),
    })

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "CONNECTED"
    assert snapshot["switches"] == []
    assert snapshot["topology"] == {"nodes": [], "links": []}
    assert snapshot["flow_count"] is None
    assert "no OpenFlow switches" in snapshot["error"]
    assert snapshot["connection_state"] == "WAITING_FOR_SWITCHES"
    assert snapshot["message"] == "Controller Connected - Waiting for Switches"


def test_admin_disabled_and_link_down_ports_are_not_reported_as_active():
    adapter, _ = make_adapter({
        "/stats/switches": FakeResponse([1]),
        "/stats/port/1": FakeResponse({"1": [{"port_no": 1, "rx_packets": 0, "tx_packets": 0}]}),
        "/stats/portdesc/1": FakeResponse({"1": [{"port_no": 1, "config": 1, "state": 1}]}),
        "/stats/flow/1": FakeResponse({"1": []}),
        "/v1.0/topology/switches": FakeResponse([]),
        "/v1.0/topology/links": FakeResponse([]),
    })

    port = adapter.snapshot()["switches"][0]["ports"][0]

    assert port["available"] is True
    assert port["admin_state"] == "DISABLED"
    assert port["link_state"] == "DOWN"
    assert port["operational_state"] == "ADMIN_DOWN"
    assert port["traffic_state"] == "UNKNOWN"


def test_optional_topology_endpoints_can_be_missing_without_faking_links():
    adapter, _ = make_adapter({
        **connected_payloads(),
        "/v1.0/topology/switches": FakeResponse(status_code=404),
        "/v1.0/topology/links": FakeResponse(status_code=404),
    })

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "CONNECTED"
    assert snapshot["topology"]["nodes"][0]["id"] == "1"
    assert snapshot["topology"]["links"] == []
    assert len(snapshot["partial_errors"]) == 2
    assert all("Ryu REST endpoint" in item["error"] for item in snapshot["partial_errors"])


def test_missing_core_ryu_application_is_not_marked_connected():
    adapter, _ = make_adapter({"/stats/switches": FakeResponse(status_code=404)})

    snapshot = adapter.snapshot()

    assert snapshot["status"] == "DISCONNECTED"
    assert snapshot["source"] == "none"
    assert "verify that the corresponding Ryu REST application is running" in snapshot["error"]


def test_switch_writes_are_blocked_by_read_only_adapter():
    adapter = RyuControllerAdapter("http://controller:8080", session=Mock())

    result = adapter.execute_action({"type": "apply_qos", "target": "switch-1"})

    assert adapter.write_operations_enabled is False
    assert result["status"] == "blocked"
    assert "read-only" in result["reason"]


def test_status_and_topology_routes_return_real_controller_snapshot(monkeypatch):
    adapter, _ = make_adapter(connected_payloads())
    monkeypatch.setattr(routes, "sdn_controller", adapter)
    monkeypatch.setattr(config, "SDN_SIMULATION_ENABLED", False)

    status = routes.sdn_status()
    topology = routes.topology()

    assert status["status"] == "CONNECTED"
    assert status["source"] == "ryu_rest_api"
    assert status["timestamp"]
    assert topology["status"] == "CONNECTED"
    assert topology["source"] == "ryu_rest_api"
    assert topology["timestamp"]
    assert topology["nodes"][0]["id"] == "1"
    assert topology["links"][0]["target"] == "2"


def test_simulation_is_labeled_and_separate_from_real_controller(monkeypatch):
    monkeypatch.setattr(config, "SDN_SIMULATION_ENABLED", True)
    monkeypatch.setattr(routes.state, "topology", {"nodes": ["sim-switch"], "links": []})

    snapshot = routes.sdn_status()

    assert snapshot["status"] == "SIMULATED"
    assert snapshot["source"] == "simulation"
    assert snapshot["timestamp"] == snapshot["last_check_at"]
    assert snapshot["topology"]["nodes"] == ["sim-switch"]
    assert snapshot["switches"] == []

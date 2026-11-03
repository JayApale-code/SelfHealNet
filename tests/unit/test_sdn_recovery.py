from backend.recovery import RecoveryOrchestrator
from backend.safety import SafetyChecker
from sdn_controller.controller import SDNController


def test_link_failure_recovery_changes_active_route_state():
    controller = SDNController(
        links=[("a", "b"), ("a", "c"), ("c", "b")],
        routes={"flow-1": ["a", "b"]},
    )
    orchestrator = RecoveryOrchestrator(controller=controller, safety_checker=SafetyChecker())

    result = orchestrator.execute_recovery(
        recovery_id="recovery-1",
        incident_id="incident-1",
        strategy={
            "actions": [
                {"type": "disable_link", "source": "a", "target": "b"},
                {"type": "update_routing", "flow_id": "flow-1", "path": ["a", "c", "b"]},
            ]
        },
        network_state={"alternate_path_available": True},
    )

    assert result["status"] == "success"
    assert controller.links[("a", "b")] is False
    assert controller.routes["flow-1"] == ["a", "c", "b"]
    assert controller.flows["flow-1"]["status"] == "active"
    assert len(controller.action_log) == 2


def test_congestion_action_updates_controller_qos_state():
    controller = SDNController(links=[("a", "b")])
    orchestrator = RecoveryOrchestrator(controller=controller, safety_checker=SafetyChecker())

    result = orchestrator.execute_recovery(
        recovery_id="recovery-2",
        incident_id="incident-2",
        strategy={"actions": [{"type": "apply_qos", "target": "video", "rate_mbps": 50}]},
        network_state={},
    )

    assert result["status"] == "success"
    assert controller.qos_policies["video"]["rate_mbps"] == 50


def test_congestion_weight_change_updates_controller_link_state():
    controller = SDNController(links=[("a", "b")])
    orchestrator = RecoveryOrchestrator(controller=controller, safety_checker=SafetyChecker())

    result = orchestrator.execute_recovery(
        recovery_id="recovery-weights",
        incident_id="incident-weights",
        strategy={"actions": [{"type": "adjust_weights", "source": "a", "target": "b", "weight": 25}]},
        network_state={"alternate_path_available": True},
    )

    assert result["status"] == "success"
    assert controller.link_weights[("a", "b")] == 25


def test_connectivity_recovery_updates_flow_rule():
    controller = SDNController(links=[("a", "b"), ("a", "c"), ("c", "b")])
    orchestrator = RecoveryOrchestrator(controller=controller, safety_checker=SafetyChecker())

    result = orchestrator.execute_recovery(
        recovery_id="recovery-flow",
        incident_id="incident-flow",
        strategy={"actions": [{"type": "update_routing", "flow_id": "flow-2", "path": ["a", "c", "b"]}]},
        network_state={"alternate_path_available": True},
    )

    assert result["status"] == "success"
    assert controller.flows["flow-2"] == {"path": ["a", "c", "b"], "status": "active"}


def test_service_degradation_restarts_managed_service():
    controller = SDNController(services=["api-gateway"])
    orchestrator = RecoveryOrchestrator(controller=controller, safety_checker=SafetyChecker())
    controller.services["api-gateway"] = "degraded"

    result = orchestrator.execute_recovery(
        recovery_id="recovery-3",
        incident_id="incident-3",
        strategy={"actions": [{"type": "restart_service", "target": "api-gateway"}]},
        network_state={},
    )

    assert result["status"] == "success"
    assert controller.services["api-gateway"] == "running"

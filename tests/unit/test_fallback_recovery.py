from backend.recovery import RecoveryOrchestrator
from backend.safety import SafetyChecker
from sdn_controller.controller import SDNController


def test_fallback_runs_after_failed_primary_and_then_succeeds():
    orchestrator = RecoveryOrchestrator(
        controller=SDNController(),
        safety_checker=SafetyChecker(),
    )
    verification_results = iter([
        {"result": "RECOVERY_FAILED", "success": False},
        {"result": "RECOVERY_SUCCESSFUL", "success": True},
    ])

    audit = orchestrator.execute_with_fallback(
        recovery_id="recovery-1",
        incident_id="incident-1",
        primary_strategy={"name": "reroute", "actions": [{"type": "increase_monitoring"}]},
        fallback_strategy={"name": "update-flow", "actions": [{"type": "increase_monitoring"}]},
        verify_attempt=lambda execution: next(verification_results),
    )

    assert audit["status"] == "RECOVERY_SUCCESSFUL"
    assert audit["successful_attempt"] == 2
    assert len(audit["attempts"]) == 2
    assert audit["administrator_alert"] is None


def test_failed_primary_and_fallback_escalate_without_looping():
    orchestrator = RecoveryOrchestrator(
        controller=SDNController(),
        safety_checker=SafetyChecker(),
    )

    audit = orchestrator.recover_with_fallback(
        recovery_id="recovery-2",
        incident_id="incident-2",
        primary_strategy={"name": "primary", "actions": [{"type": "increase_monitoring"}]},
        fallback_strategy={"name": "fallback", "actions": [{"type": "increase_monitoring"}]},
        verify_attempt=lambda execution: {"success": False},
        max_attempts=99,
    )

    assert audit["status"] == "ESCALATED"
    assert audit["max_attempts"] == 2
    assert len(audit["attempts"]) == 2
    assert audit["administrator_alert"]["severity"] == "CRITICAL"
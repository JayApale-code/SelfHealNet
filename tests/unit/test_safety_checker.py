from backend.recovery import RecoveryOrchestrator
from backend.safety import SafetyChecker


def test_safe_action_is_allowed_and_logged():
    checker = SafetyChecker()
    result = checker.validate_action(
        {"type": "enable_backup_link", "target": "backup-1"},
        {"alternate_path_available": True, "backup_links": ["backup-1"]},
        {"incident_id": "inc-1"},
    )

    assert result["safe"] is True
    assert result["administrator_alert"] is None
    assert checker.decision_log[-1] == result
    assert all(check["passed"] for check in result["checks"])


def test_unsupported_action_is_blocked_with_admin_alert():
    result = SafetyChecker().validate_action(
        {"type": "delete_network"},
        {},
        {"incident_id": "inc-2"},
    )

    assert result["safe"] is False
    assert result["administrator_alert"]["severity"] == "CRITICAL"
    assert "not supported" in result["administrator_alert"]["reasons"][0]


def test_missing_path_resource_and_overload_are_blocked():
    result = SafetyChecker().validate_action(
        {
            "type": "enable_backup_link",
            "target": "backup-2",
            "target_links": ["backup-2"],
            "traffic_shift": 20,
        },
        {
            "alternate_path_available": False,
            "backup_links": [],
            "link_utilization": {"backup-2": 70},
        },
        {"incident_id": "inc-3"},
    )

    assert result["safe"] is False
    failed_checks = {check["check"] for check in result["checks"] if not check["passed"]}
    assert failed_checks == {"required_alternate_path", "required_resource", "overload_prevention"}


def test_recovery_executor_blocks_action_before_execution():
    checker = SafetyChecker()
    orchestrator = RecoveryOrchestrator(safety_checker=checker)
    result = orchestrator.execute_recovery(
        recovery_id="rec-1",
        incident_id="inc-4",
        strategy={"actions": [{"type": "disable_link", "target": "link-1"}]},
        network_state={"alternate_path_available": False},
    )

    assert result["status"] == "failed"
    assert result["actions_executed"] == []
    assert result["errors"][0]["safety_decision"]["safe"] is False

from backend.verification import VerificationEngine


def test_verification_collects_after_stabilization_and_succeeds():
    waits = []
    engine = VerificationEngine(sleep_fn=waits.append)

    result = engine.verify_metrics(
        recovery_id="recovery-1",
        incident_id="incident-1",
        pre_recovery_metrics={"latency": 240, "packet_loss": 18, "bandwidth_usage": 96, "link_status": "down"},
        metric_collector=lambda: {"latency_ms": 42, "packet_loss_pct": 2, "bandwidth_utilization_pct": 60, "link_status": "up"},
        stabilization_seconds=5,
    )

    assert waits == [5]
    assert result["result"] == "RECOVERY_SUCCESSFUL"
    assert result["verified"] is True
    assert result["criteria_failed"] == []
    assert result["metric_comparisons"]["latency_ms"]["improvement_percent"] == 82.5


def test_verification_fails_when_post_recovery_metrics_remain_bad():
    result = VerificationEngine().verify(
        recovery_id="recovery-2",
        incident_id="incident-2",
        pre_recovery_metrics={"latency_ms": 100, "packet_loss_pct": 10, "bandwidth_utilization_pct": 95, "link_status": "down"},
        post_recovery_metrics={"latency_ms": 140, "packet_loss_pct": 8, "bandwidth_utilization_pct": 92, "link_status": "down"},
    )

    assert result["result"] == "RECOVERY_FAILED"
    assert result["verified"] is False
    assert set(result["criteria_failed"]) == {"link_available", "latency_stable", "packet_loss_acceptable", "bandwidth_safe"}
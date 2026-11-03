import pytest

from backend.incident_logging import IncidentLogger


def test_incident_logger_stores_complete_lifecycle_record():
    logger = IncidentLogger()
    created = logger.create_incident(
        incident_id="incident-1",
        detected_fault="LINK_FAILURE",
        affected_component="link-a-b",
        metrics={"packet_loss_pct": 100},
        ml_prediction={"label": "LINK_FAILURE", "probability": 0.94},
        confidence=0.96,
        severity="CRITICAL",
        selected_action="REROUTE_TRAFFIC",
        safety_result={"safe": True},
    )
    updated = logger.update_incident(
        "incident-1",
        recovery_result={"status": "success"},
        verification_metrics={"before": {"packet_loss_pct": 100}, "after": {"packet_loss_pct": 2}},
        final_status="RESOLVED",
    )

    assert created["timestamp"]
    assert updated["detected_fault"] == "LINK_FAILURE"
    assert updated["selected_action"] == "REROUTE_TRAFFIC"
    assert updated["final_status"] == "RESOLVED"
    assert updated["verification_metrics"]["after"]["packet_loss_pct"] == 2


def test_incident_logger_rejects_duplicates_and_unknown_updates():
    logger = IncidentLogger()
    arguments = {
        "incident_id": "incident-2",
        "detected_fault": "CONGESTION",
        "affected_component": "router-1",
        "metrics": {},
        "ml_prediction": {},
        "confidence": 0.8,
        "severity": "HIGH",
    }
    logger.create_incident(**arguments)

    with pytest.raises(ValueError, match="already exists"):
        logger.create_incident(**arguments)
    with pytest.raises(ValueError, match="Unsupported incident updates"):
        logger.update_incident("incident-2", metrics={"latency_ms": 100})
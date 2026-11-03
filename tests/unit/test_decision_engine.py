from backend.explainability import ExplainableDecisionEngine


ENGINE = ExplainableDecisionEngine()


def test_link_failure_selects_reroute_with_explanation():
    result = ENGINE.decide(
        diagnosis={
            "fault_type": "LINK_FAILURE",
            "affected_component": "link-1-2",
            "confidence": 0.92,
            "supporting_metrics": [
                {"metric": "link_status", "value": "down", "reason": "link is down"},
                {"metric": "packet_loss_pct", "value": 100, "reason": "near-total traffic loss"},
            ],
        },
        risk_assessment={"risk_level": "HIGH", "risk_score": 62},
        live_metrics={"link_status": "down", "packet_loss_pct": 100},
        alternate_path_available=True,
    )

    assert result["selected_action"] == "REROUTE_TRAFFIC"
    assert "alternate path is available" in result["reason"]
    assert result["expected_effect"] == "Restore connectivity through the alternate path."
    assert result["evidence"][0]["metric"] == "link_status"
    assert result["risk"] == "HIGH"
    assert result["confidence"] == 0.98


def test_critical_risk_blocks_automatic_recovery():
    result = ENGINE.decide(
        diagnosis={"fault_type": "LINK_FAILURE", "confidence": 0.9},
        risk_assessment={"risk_level": "CRITICAL", "risk_score": 90},
        live_metrics={"link_status": "down"},
        alternate_path_available=True,
    )

    assert result["selected_action"] == "ALERT_OPERATIONS"
    assert "automated action is blocked" in result["reason"]
    assert result["expected_effect"] == "Escalate for approval and controlled recovery."


def test_congestion_without_alternate_path_uses_qos():
    result = ENGINE.generate_decision(
        diagnosis={"fault_type": "CONGESTION", "confidence": 0.8},
        risk_assessment={"risk_level": "MEDIUM", "risk_score": 45},
        live_metrics={"latency_ms": 120, "packet_loss_pct": 4, "bandwidth_utilization_pct": 94},
        alternate_path_available=False,
    )

    assert result["selected_action"] == "APPLY_QOS"
    assert "traffic shaping" in result["reason"]
    assert len(result["evidence"]) == 3

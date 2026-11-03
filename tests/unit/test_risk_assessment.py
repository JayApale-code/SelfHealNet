from backend.risk_assessment import RiskAssessmentEngine


def test_critical_risk_combines_all_phase_seven_factors():
    result = RiskAssessmentEngine().assess_risk(
        diagnosis={
            "severity": "CRITICAL",
            "affected_component": "link-router-1-router-2",
            "affected_services": ["database"],
        },
        traffic_impact=0.9,
        recovery_action_risk="high",
        alternate_path_available=False,
    )

    assert result["risk_level"] == "CRITICAL"
    assert result["risk_score"] == 85.0
    assert result["factor_scores"] == {
        "severity": 100,
        "traffic_impact": 100,
        "affected_component": 100,
        "recovery_action_risk": 70,
        "alternate_path": 10,
    }
    assert "alternate path=unavailable" in result["decision_logic"]


def test_low_risk_has_available_alternate_path():
    result = RiskAssessmentEngine().assess_risk(
        diagnosis={"severity": "LOW", "affected_component": "host-1"},
        traffic_impact=0.1,
        recovery_action_risk=0.1,
        alternate_path_available=True,
    )

    assert result["risk_level"] == "LOW"
    assert result["risk_score"] == 13.5
    assert result["factor_scores"]["alternate_path"] == 0


def test_numeric_percentages_are_supported():
    result = RiskAssessmentEngine().assess_risk(
        diagnosis={"severity": "HIGH", "affected_component": "router-1"},
        traffic_impact=60,
        recovery_action_risk=20,
        alternate_path_available=2,
    )

    assert result["factor_scores"]["traffic_impact"] == 70
    assert result["factor_scores"]["recovery_action_risk"] == 10
    assert result["factor_scores"]["alternate_path"] == 0
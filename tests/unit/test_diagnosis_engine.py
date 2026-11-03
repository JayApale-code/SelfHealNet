from backend.diagnosis import DiagnosisEngine


ENGINE = DiagnosisEngine()
TOPOLOGY = {
    "nodes": ["router-1", "router-2"],
    "links": [["router-1", "router-2"]],
}


def test_diagnoses_congestion_with_explainable_evidence():
    result = ENGINE.diagnose(
        live_metrics={
            "latency_ms": 120,
            "packet_loss_pct": 4.0,
            "bandwidth_utilization_pct": 94,
            "throughput_mbps": 20,
            "link_status": "up",
        },
        ml_prediction={"label": "CONGESTION", "probability": 0.86},
        topology=TOPOLOGY,
        affected_node="router-1",
    )

    assert result["fault_type"] == "CONGESTION"
    assert result["affected_component"] == "router-1"
    assert result["severity"] == "HIGH"
    assert result["confidence"] >= 0.86
    assert {item["metric"] for item in result["supporting_metrics"]} >= {
        "latency_ms",
        "packet_loss_pct",
        "bandwidth_utilization_pct",
    }
    assert "CONGESTION" in result["explanation"]
    assert result["topology_context"]["node_degree"] == 1


def test_diagnoses_link_failure_from_link_state():
    result = ENGINE.diagnose(
        live_metrics={
            "latency": 0,
            "packet_loss": 100,
            "throughput": 0,
            "link_status": "down",
            "connectivity": "down",
        },
        ml_prediction={"label": "LINK_FAILURE", "probability": 0.91},
        topology=TOPOLOGY,
        affected_link=["router-1", "router-2"],
    )

    assert result["fault_type"] == "LINK_FAILURE"
    assert result["severity"] == "CRITICAL"
    assert result["topology_context"]["link_known"] is True
    assert "link is down" in result["explanation"]


def test_healthy_metrics_return_normal():
    result = ENGINE.diagnose(
        live_metrics={
            "latency": 20,
            "packet_loss": 0.1,
            "throughput": 100,
            "bandwidth_usage": 35,
            "link_status": "up",
            "connectivity_score": 1.0,
            "route_redundancy": 2,
        },
        ml_prediction={"label": "NORMAL", "probability": 0.95},
        topology=TOPOLOGY,
        affected_node="router-1",
    )

    assert result["fault_type"] == "NORMAL"
    assert result["severity"] == "LOW"
    assert result["supporting_metrics"] == []


def test_missing_throughput_does_not_create_link_failure():
    result = ENGINE.diagnose(
        live_metrics={"latency_ms": 120, "cpu_utilization_pct": 32.1},
        ml_prediction={"label": "NORMAL", "probability": 0.95},
        topology={"nodes": [], "links": []},
    )

    assert result["fault_type"] == "CONGESTION"
    assert "throughput_mbps" not in {
        item["metric"] for item in result["supporting_metrics"]
    }


def test_invalid_throughput_does_not_create_link_failure():
    result = ENGINE.diagnose(
        live_metrics={"latency_ms": 120, "throughput_mbps": "unavailable"},
        ml_prediction={"label": "NORMAL", "probability": 0.95},
        topology={"nodes": [], "links": []},
    )

    assert result["fault_type"] == "CONGESTION"
    assert "throughput_mbps" not in {
        item["metric"] for item in result["supporting_metrics"]
    }


def test_measured_zero_throughput_is_link_failure():
    result = ENGINE.diagnose(
        live_metrics={
            "throughput_mbps": 0,
            "connectivity_score": 1,
            "route_redundancy": 1,
        },
        ml_prediction={"label": "NORMAL", "probability": 0.95},
        topology={"nodes": [], "links": []},
    )

    assert result["fault_type"] == "LINK_FAILURE"
    assert any(
        item["metric"] == "throughput_mbps"
        for item in result["supporting_metrics"]
    )

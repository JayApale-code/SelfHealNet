from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base, NetworkIncident, NetworkMetric, PredictionRecord
from backend.ml_engine.telemetry_pipeline import TelemetryInferencePipeline
from backend.diagnosis import DiagnosisEngine
from ml.predict import predict_from_record
from ml.preprocessing import prepare_prediction_frame


@pytest.fixture
def isolated_sessions():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    try:
        yield sessions
    finally:
        engine.dispose()


def add_metric(
    session,
    metric_type: str,
    value: float,
    timestamp: datetime,
    interface_id: str = "test-interface",
) -> NetworkMetric:
    metric = NetworkMetric(
        metric_type=metric_type,
        value=value,
        timestamp=timestamp.replace(tzinfo=None),
        interface_id=interface_id,
        node_id="test-host",
        unit="percent" if metric_type == "cpu_utilization_pct" else "mbps",
    )
    session.add(metric)
    session.flush()
    return metric


def test_prediction_frame_preserves_missing_values_for_saved_imputer():
    frame = prepare_prediction_frame({
        "cpu_utilization_pct": 41.0,
        "throughput_mbps": 12.5,
    })

    assert frame.loc[0, "cpu_utilization_pct"] == 41.0
    assert frame.loc[0, "throughput_mbps"] == 12.5
    assert frame.loc[0, "source"] is None
    assert frame.loc[0, "packet_loss_pct"] is None
    assert frame.loc[0, "fault_scenario"] is None


def test_saved_model_predicts_and_reports_imputed_features():
    prediction = predict_from_record({
        "cpu_utilization_pct": 41.0,
        "throughput_mbps": 12.5,
        "latency_ms": 22.0,
    })

    assert prediction["label"] in {
        "CONGESTION",
        "CONNECTIVITY_FAILURE",
        "LINK_FAILURE",
        "NORMAL",
        "SERVICE_DEGRADATION",
    }
    assert set(prediction["observed_features"]) == {
        "cpu_utilization_pct",
        "throughput_mbps",
        "latency_ms",
    }
    assert "packet_loss_pct" in prediction["imputed_features"]
    assert "source" in prediction["imputed_features"]
    assert len(prediction["imputed_features"]) == 13
    assert prediction["model_version"]


def test_missing_measurements_remain_unknown_in_diagnosis():
    normalized = DiagnosisEngine._normalize_metrics({"cpu_utilization_pct": 45.0})

    assert normalized["latency_ms"] is None
    assert normalized["packet_loss_pct"] is None
    assert normalized["bandwidth_utilization_pct"] is None
    assert normalized["cpu_utilization_pct"] == 45.0


def test_pipeline_rejects_stale_or_cross_interface_core_samples(isolated_sessions):
    now = datetime.now(timezone.utc)
    with isolated_sessions() as session:
        add_metric(session, "cpu_utilization_pct", 40.0, now)
        add_metric(
            session,
            "throughput_mbps",
            5.0,
            now - timedelta(seconds=120),
        )
        session.commit()

    pipeline = TelemetryInferencePipeline(
        session_factory=isolated_sessions,
        freshness_seconds=60,
    )
    result = pipeline.process_once(now)

    assert result["state"] == "skipped"
    with isolated_sessions() as session:
        assert session.query(PredictionRecord).count() == 0

    with isolated_sessions() as session:
        add_metric(session, "throughput_mbps", 5.0, now, interface_id="other-interface")
        session.commit()

    result = pipeline.process_once(now)
    assert result["state"] == "skipped"


def test_pipeline_persists_actual_inference_provenance_and_diagnosis(isolated_sessions):
    now = datetime.now(timezone.utc)
    with isolated_sessions() as session:
        cpu = add_metric(session, "cpu_utilization_pct", 42.0, now)
        throughput = add_metric(session, "throughput_mbps", 14.0, now)
        latency = add_metric(session, "latency_ms", 24.0, now)
        session.commit()
        metric_ids = {cpu.id, throughput.id, latency.id}

    pipeline = TelemetryInferencePipeline(session_factory=isolated_sessions)
    result = pipeline.process_once(now)

    assert result["state"] == "inferred"
    assert result["last_sample_at"]
    assert result["diagnosis"] in {
        "CONGESTION",
        "CONNECTIVITY_FAILURE",
        "INCONCLUSIVE",
        "LINK_FAILURE",
        "NORMAL",
        "SERVICE_DEGRADATION",
    }
    with isolated_sessions() as session:
        prediction = session.query(PredictionRecord).one()
        snapshot = prediction.feature_snapshot
        assert prediction.model_name == "SelfHealNet Telemetry RandomForest"
        assert snapshot["model_version"]
        assert snapshot["input_sample_ref"]["metric_ids"]
        assert set(snapshot["input_sample_ref"]["metric_ids"].values()) == metric_ids
        assert set(snapshot["observed_features"]) == {
            "cpu_utilization_pct",
            "throughput_mbps",
            "latency_ms",
        }
        assert len(snapshot["imputed_features"]) == 13
        incident_count = session.query(NetworkIncident).count()
        assert incident_count == (
            1 if result["diagnosis"] not in {"NORMAL", "INCONCLUSIVE"} else 0
        )

    duplicate = pipeline.process_once(now)
    assert duplicate["state"] == "skipped"
    with isolated_sessions() as session:
        assert session.query(PredictionRecord).count() == 1


def test_pipeline_requires_cpu_and_throughput(isolated_sessions):
    now = datetime.now(timezone.utc)
    with isolated_sessions() as session:
        add_metric(session, "cpu_utilization_pct", 40.0, now)
        session.commit()

    pipeline = TelemetryInferencePipeline(session_factory=isolated_sessions)
    result = pipeline.process_once(now)

    assert result["state"] == "skipped"
    with isolated_sessions() as session:
        assert session.query(PredictionRecord).count() == 0


def test_low_probability_prediction_is_inconclusive_without_incident(isolated_sessions):
    now = datetime.now(timezone.utc)
    with isolated_sessions() as session:
        add_metric(session, "cpu_utilization_pct", 42.0, now)
        add_metric(session, "throughput_mbps", 14.0, now)
        add_metric(session, "latency_ms", 24.0, now)
        session.commit()

    prediction = {
        "label": "LINK_FAILURE",
        "probability": 0.32,
        "probabilities": {"LINK_FAILURE": 0.32, "NORMAL": 0.28},
        "model_version": "test",
        "observed_features": ["cpu_utilization_pct", "throughput_mbps", "latency_ms"],
        "imputed_features": ["packet_loss_pct"],
    }
    pipeline = TelemetryInferencePipeline(
        session_factory=isolated_sessions,
        predictor=lambda _: prediction,
    )

    result = pipeline.process_once(now)

    assert result["state"] == "inferred"
    assert result["prediction"] == "LINK_FAILURE"
    assert result["diagnosis"] == "INCONCLUSIVE"
    assert result["incident_created"] is False
    with isolated_sessions() as session:
        assert session.query(PredictionRecord).count() == 1
        assert session.query(NetworkIncident).count() == 0


def test_independent_measured_fault_can_create_incident_below_model_threshold(isolated_sessions):
    now = datetime.now(timezone.utc)
    with isolated_sessions() as session:
        add_metric(session, "cpu_utilization_pct", 42.0, now)
        add_metric(session, "throughput_mbps", 14.0, now)
        add_metric(session, "latency_ms", 150.0, now)
        session.commit()

    prediction = {
        "label": "LINK_FAILURE",
        "probability": 0.32,
        "probabilities": {"LINK_FAILURE": 0.32, "NORMAL": 0.28},
        "model_version": "test",
        "observed_features": ["cpu_utilization_pct", "throughput_mbps", "latency_ms"],
        "imputed_features": ["packet_loss_pct"],
    }
    pipeline = TelemetryInferencePipeline(
        session_factory=isolated_sessions,
        predictor=lambda _: prediction,
    )

    result = pipeline.process_once(now)

    assert result["diagnosis"] == "CONGESTION"
    assert result["incident_created"] is True
    with isolated_sessions() as session:
        incident = session.query(NetworkIncident).one()
        assert incident.incident_type == "CONGESTION"

from pathlib import Path

from ml.evaluate import evaluate_saved_model
from ml.predict import predict_from_record
from ml.train import train_and_save_model


def test_training_pipeline_creates_model_and_metrics():
    model_path = Path("ml/model/fault_prediction_model.joblib")
    result = train_and_save_model()

    assert model_path.exists(), "Expected the trained model to be saved to ml/model"
    assert result["model_path"] == str(model_path)
    assert result["metrics"]["accuracy"] > 0.0
    assert set(result["metrics"].keys()) >= {
        "accuracy",
        "precision",
        "recall",
        "f1",
        "confusion_matrix",
    }


def test_prediction_uses_saved_model():
    sample = {
        "latency_ms": 24.0,
        "jitter_ms": 3.2,
        "packet_loss_pct": 0.2,
        "throughput_mbps": 120.0,
        "bandwidth_utilization_pct": 35.0,
        "cpu_utilization_pct": 42.0,
        "memory_utilization_pct": 48.0,
        "active_flows": 60,
        "retransmissions_pct": 0.8,
        "dropped_packets": 3,
        "link_status": "up",
        "route_redundancy": 3,
        "connectivity_score": 0.95,
    }
    prediction = predict_from_record(sample)
    assert prediction["label"] in {
        "NORMAL",
        "CONGESTION",
        "LINK_FAILURE",
        "SERVICE_DEGRADATION",
        "CONNECTIVITY_FAILURE",
    }
    assert prediction["probability"] >= 0.0


def test_evaluation_matches_saved_model():
    metrics = evaluate_saved_model()
    assert metrics["accuracy"] > 0.0
    assert metrics["precision"] > 0.0
    assert metrics["recall"] > 0.0
    assert metrics["f1"] > 0.0

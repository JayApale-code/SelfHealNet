"""Load the trained model and predict the network-fault class for new records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.preprocessing import prepare_prediction_frame

ROOT_DIR = Path(__file__).resolve().parent
MODEL_PATH = ROOT_DIR / "model" / "fault_prediction_model.joblib"


def predict_from_record(record: dict[str, Any]) -> dict[str, Any]:
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    preprocessor = bundle["preprocessor"]
    selector = bundle["selector"]

    frame = prepare_prediction_frame(record)
    feature_columns = list(bundle["feature_columns"])
    if set(feature_columns) != set(frame.columns):
        raise ValueError("Saved model feature schema does not match prediction input.")
    frame = frame[feature_columns]

    if hasattr(preprocessor, "transform"):
        processed = preprocessor.transform(frame)
    else:
        processed = frame.to_numpy()

    if hasattr(selector, "transform"):
        selected = selector.transform(processed)
    else:
        selected = processed

    prediction = model.predict(selected)[0]
    probabilities = model.predict_proba(selected)[0]
    class_labels = list(model.classes_)
    top_index = int(probabilities.argmax())
    observed_features = [
        column for column in feature_columns
        if record.get(column) is not None and not pd.isna(record.get(column))
    ]
    imputed_features = [
        column for column in feature_columns if column not in observed_features
    ]

    return {
        "label": str(prediction),
        "probability": float(probabilities[top_index]),
        "probabilities": {
            str(class_label): float(probabilities[idx])
            for idx, class_label in enumerate(class_labels)
        },
        "model_version": str(bundle.get("version", "1.0.0")),
        "observed_features": observed_features,
        "imputed_features": imputed_features,
    }


def predict_fault(features: list[float] | dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper for either a feature vector or a record dictionary."""
    if isinstance(features, dict):
        return predict_from_record(features)

    if isinstance(features, list):
        default_record = {
            "latency_ms": features[0] if len(features) > 0 else None,
            "jitter_ms": features[1] if len(features) > 1 else None,
            "packet_loss_pct": features[2] if len(features) > 2 else None,
            "throughput_mbps": features[3] if len(features) > 3 else None,
            "bandwidth_utilization_pct": features[4] if len(features) > 4 else None,
            "cpu_utilization_pct": features[5] if len(features) > 5 else None,
            "memory_utilization_pct": features[6] if len(features) > 6 else None,
            "active_flows": features[7] if len(features) > 7 else None,
            "retransmissions_pct": features[8] if len(features) > 8 else None,
            "dropped_packets": features[9] if len(features) > 9 else None,
            "link_status": None,
            "route_redundancy": None,
            "connectivity_score": None,
            "source": None,
            "destination": None,
            "fault_scenario": None,
        }
        return predict_from_record(default_record)

    raise TypeError("features must be either a dict or a list of numeric values")

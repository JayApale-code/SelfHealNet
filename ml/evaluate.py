"""Evaluate the saved Random Forest model using real execution metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score

MODEL_PATH = Path(__file__).resolve().parent / "model" / "fault_prediction_model.joblib"


def evaluate_saved_model(model_path: str | Path = MODEL_PATH) -> dict[str, Any]:
    bundle = joblib.load(model_path)
    X_test = bundle["test_features"]
    y_test = bundle["test_labels"]
    model = bundle["model"]

    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    precision = precision_score(
        y_test,
        predictions,
        average="weighted",
        zero_division=0,
    )
    recall = recall_score(
        y_test,
        predictions,
        average="weighted",
        zero_division=0,
    )
    f1 = f1_score(
        y_test,
        predictions,
        average="weighted",
        zero_division=0,
    )
    cm = confusion_matrix(y_test, predictions, labels=bundle["class_labels"])

    return {
        "accuracy": float(accuracy),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": cm.tolist(),
        "label_order": bundle["class_labels"],
    }


def evaluate_model() -> dict[str, Any]:
    return evaluate_saved_model()

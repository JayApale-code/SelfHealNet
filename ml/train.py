"""Train and save the Real ML fault-prediction model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from ml.preprocessing import DATASET_PATH, prepare_training_data

ROOT_DIR = Path(__file__).resolve().parent
MODEL_DIR = ROOT_DIR / "model"
MODEL_PATH = MODEL_DIR / "fault_prediction_model.joblib"


def train_and_save_model() -> dict[str, Any]:
    """Load dataset, preprocess, select features, split, train, evaluate, and save."""
    dataset = pd.read_csv(DATASET_PATH)
    X_processed, y, preprocessor, selector = prepare_training_data(dataset)

    X_train, X_test, y_train, y_test = train_test_split(
        X_processed,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    model = RandomForestClassifier(
        n_estimators=250,
        random_state=42,
        class_weight="balanced",
        min_samples_leaf=1,
    )
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)
    precision = precision_score(y_test, predictions, average="weighted", zero_division=0)
    recall = recall_score(y_test, predictions, average="weighted", zero_division=0)
    f1 = f1_score(y_test, predictions, average="weighted", zero_division=0)
    cm = confusion_matrix(y_test, predictions, labels=sorted(y.unique()))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "preprocessor": preprocessor,
        "selector": selector,
        "feature_columns": list(dataset.columns.drop("label")),
        "class_labels": sorted(y.unique()),
        "test_features": X_test,
        "test_labels": y_test,
        "metrics": {
            "accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "confusion_matrix": cm.tolist(),
        },
    }
    joblib.dump(bundle, MODEL_PATH)

    project_root = Path(__file__).resolve().parent.parent
    relative_model_path = Path("ml") / "model" / "fault_prediction_model.joblib"

    return {
        "status": "success",
        "model_path": str(relative_model_path),
        "dataset_path": str(Path("ml") / "dataset" / "network_fault_dataset.csv"),
        "metrics": {
            "accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "confusion_matrix": cm.tolist(),
        },
    }


def train_model() -> dict[str, Any]:
    return train_and_save_model()

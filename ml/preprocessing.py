"""Preprocessing utilities for the network-fault prediction pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT_DIR = Path(__file__).resolve().parent
DATASET_PATH = ROOT_DIR / "dataset" / "network_fault_dataset.csv"
TARGET_COLUMN = "label"
CATEGORICAL_COLUMNS = ["source", "destination", "link_status", "fault_scenario"]


def ensure_dataset_dir(dataset_dir: str | Path | None = None) -> Path:
    target = Path(dataset_dir) if dataset_dir is not None else ROOT_DIR / "dataset"
    target.mkdir(parents=True, exist_ok=True)
    return target


def load_dataset(dataset_path: str | Path = DATASET_PATH) -> pd.DataFrame:
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return pd.read_csv(path)


def build_preprocessor(X: pd.DataFrame) -> ColumnTransformer:
    numeric_columns = [
        col for col in X.columns if col not in CATEGORICAL_COLUMNS and col != TARGET_COLUMN
    ]
    categorical_columns = [col for col in CATEGORICAL_COLUMNS if col in X.columns]

    transformers = []
    if numeric_columns:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                    ]
                ),
                numeric_columns,
            )
        )
    if categorical_columns:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical_columns,
            )
        )

    if not transformers:
        raise ValueError("No feature columns found for preprocessing.")

    return ColumnTransformer(transformers=transformers, remainder="drop")


def select_features(X: Any, y: pd.Series) -> tuple[Any, SelectKBest, list[str]]:
    selector = SelectKBest(score_func=f_classif, k=min(12, X.shape[1]))
    X_selected = selector.fit_transform(X, y)
    selected_feature_names = [
        f"feature_{idx}" for idx in range(X_selected.shape[1])
    ]
    return X_selected, selector, selected_feature_names


def prepare_training_data(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, ColumnTransformer, SelectKBest]:
    data = frame.copy()
    if TARGET_COLUMN not in data.columns:
        raise KeyError(f"Target column {TARGET_COLUMN!r} not found in dataset.")

    feature_frame = data.drop(columns=[TARGET_COLUMN])
    target = data[TARGET_COLUMN].astype(str)
    preprocessor = build_preprocessor(feature_frame)
    X_preprocessed = preprocessor.fit_transform(feature_frame)
    X_selected, selector, _ = select_features(X_preprocessed, target)
    return pd.DataFrame(X_selected), target, preprocessor, selector


def prepare_prediction_frame(record: dict[str, Any]) -> pd.DataFrame:
    feature_columns = [
        "source",
        "destination",
        "latency_ms",
        "jitter_ms",
        "packet_loss_pct",
        "throughput_mbps",
        "bandwidth_utilization_pct",
        "cpu_utilization_pct",
        "memory_utilization_pct",
        "active_flows",
        "retransmissions_pct",
        "dropped_packets",
        "link_status",
        "route_redundancy",
        "connectivity_score",
        "fault_scenario",
    ]
    return pd.DataFrame(
        [{column: record.get(column) for column in feature_columns}],
        columns=feature_columns,
    )

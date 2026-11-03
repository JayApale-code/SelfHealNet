"""Fresh persisted-telemetry inference and diagnosis pipeline."""

from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session, sessionmaker

from backend.config import config
from backend.database import (
    NetworkIncident,
    NetworkMetric,
    PredictionRecord,
    SessionLocal,
)
from backend.diagnosis import DiagnosisEngine
from ml.predict import predict_from_record

logger = logging.getLogger(__name__)

MODEL_NAME = "SelfHealNet Telemetry RandomForest"
CORE_FEATURES = ("cpu_utilization_pct", "throughput_mbps")
METRIC_FEATURES = {
    "cpu_utilization_pct": "cpu_utilization_pct",
    "throughput_mbps": "throughput_mbps",
    "latency_ms": "latency_ms",
}
MODEL_FEATURES = (
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
)


class TelemetryInferencePipeline:
    """Infer once per fresh persisted CPU/throughput sample set."""

    def __init__(
        self,
        session_factory: sessionmaker = SessionLocal,
        predictor: Callable[[dict[str, Any]], dict[str, Any]] = predict_from_record,
        interval_seconds: Optional[int] = None,
        freshness_seconds: Optional[int] = None,
    ) -> None:
        self._session_factory = session_factory
        self._predictor = predictor
        self._interval_seconds = interval_seconds or config.MONITORING_INTERVAL
        self._freshness_seconds = freshness_seconds or max(60, config.MONITORING_INTERVAL * 3)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status_lock = threading.Lock()
        self._status: dict[str, Any] = {
            "running": False,
            "state": "stopped",
            "last_inference_at": None,
            "last_sample_at": None,
            "last_reason": "Inference worker has not started.",
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="telemetry-inference",
            daemon=True,
        )
        self._thread.start()
        self._update_status(running=True, state="starting", last_reason=None)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(5, self._interval_seconds + 1))
        self._update_status(running=False, state="stopped")

    def status(self) -> dict[str, Any]:
        with self._status_lock:
            return dict(self._status)

    def process_once(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        freshness_cutoff = current_time - timedelta(seconds=self._freshness_seconds)
        with self._session_factory() as db:
            sample = self._latest_sample(db, freshness_cutoff, current_time)
            if sample is None:
                result = {
                    "state": "skipped",
                    "reason": "Fresh CPU and throughput samples from the same interface are required.",
                }
                self._update_status(**result, running=self._is_running())
                return result

            features, sample_ref, sample_timestamp = sample
            sample_key = json.dumps(sample_ref["metric_ids"], sort_keys=True)
            duplicate = self._existing_sample(db, sample_key, freshness_cutoff)
            if duplicate:
                result = {
                    "state": "skipped",
                    "reason": "This persisted metric sample has already been processed.",
                    "last_sample_at": sample_timestamp.isoformat(),
                }
                self._update_status(**result, running=self._is_running())
                return result

            prediction = self._predictor(features)
            diagnosis_metrics = {
                feature: features[feature]
                for feature in ("cpu_utilization_pct", "throughput_mbps", "latency_ms")
                if features[feature] is not None
            }
            prediction_is_actionable = prediction["probability"] >= config.PREDICTION_THRESHOLD
            diagnosis_prediction = prediction if prediction_is_actionable else {
                **prediction,
                "label": "NORMAL",
                "probability": 0.0,
            }
            diagnosis = DiagnosisEngine().diagnose(
                live_metrics=diagnosis_metrics,
                ml_prediction=diagnosis_prediction,
                topology={"nodes": [], "links": []},
                affected_node=sample_ref["interface_id"] or sample_ref["node_id"],
            )
            if not prediction_is_actionable and diagnosis["fault_type"] == "NORMAL":
                diagnosis = {
                    **diagnosis,
                    "fault_type": "INCONCLUSIVE",
                    "severity": "low",
                    "confidence": prediction["probability"],
                    "supporting_metrics": [{
                        "metric": "ml_prediction",
                        "value": prediction["label"],
                        "reason": (
                            f"Top class probability {prediction['probability']:.2f} is below "
                            f"the configured threshold {config.PREDICTION_THRESHOLD:.2f}; "
                            "this prediction is not confirmation of a fault."
                        ),
                    }],
                    "explanation": (
                        f"The model's top class was {prediction['label']} at "
                        f"{prediction['probability']:.2f}, below the configured "
                        f"{config.PREDICTION_THRESHOLD:.2f} threshold. No independent "
                        "measured telemetry evidence confirmed a fault."
                    ),
                }
            created_at = current_time.astimezone(timezone.utc).replace(tzinfo=None)
            feature_snapshot = {
                "component": sample_ref["interface_id"] or sample_ref["node_id"],
                "model_version": prediction["model_version"],
                "input_sample_ref": sample_ref,
                "observed_features": prediction["observed_features"],
                "imputed_features": prediction["imputed_features"],
                "input_features": {
                    name: features[name]
                    for name in prediction["observed_features"]
                    if name in features
                },
                "diagnosis": diagnosis,
            }
            db.add(PredictionRecord(
                prediction_id=f"PRED-{uuid.uuid4().hex[:12].upper()}",
                model_name=MODEL_NAME,
                prediction_label=prediction["label"],
                probability=prediction["probability"],
                confidence=prediction["probability"],
                feature_snapshot=feature_snapshot,
                created_at=created_at,
            ))
            incident_created = diagnosis["fault_type"] not in {"NORMAL", "INCONCLUSIVE"}
            if incident_created:
                self._persist_incident(
                    db,
                    prediction=prediction,
                    diagnosis=diagnosis,
                    metrics=diagnosis_metrics,
                    sample_ref=sample_ref,
                    created_at=created_at,
                )
            db.commit()

        result = {
            "state": "inferred",
            "reason": None,
            "last_inference_at": created_at.replace(tzinfo=timezone.utc).isoformat(),
            "last_sample_at": sample_timestamp.isoformat(),
            "prediction": prediction["label"],
            "diagnosis": diagnosis["fault_type"],
            "incident_created": incident_created,
        }
        self._update_status(**result, running=self._is_running())
        logger.info(
            "Telemetry inference completed: label=%s diagnosis=%s observed_features=%s imputed_features=%s",
            prediction["label"],
            diagnosis["fault_type"],
            len(prediction["observed_features"]),
            len(prediction["imputed_features"]),
        )
        return result

    def _latest_sample(
        self,
        db: Session,
        freshness_cutoff: datetime,
        current_time: datetime,
    ) -> Optional[tuple[dict[str, Any], dict[str, Any], datetime]]:
        rows = (
            db.query(NetworkMetric)
            .filter(
                NetworkMetric.metric_type.in_(METRIC_FEATURES),
                NetworkMetric.timestamp >= freshness_cutoff.replace(tzinfo=None),
                NetworkMetric.timestamp <= current_time.replace(tzinfo=None),
            )
            .order_by(NetworkMetric.timestamp.desc(), NetworkMetric.id.desc())
            .all()
        )
        by_interface: dict[tuple[Optional[str], Optional[str]], dict[str, NetworkMetric]] = {}
        for row in rows:
            key = (row.interface_id, row.node_id)
            feature = METRIC_FEATURES[row.metric_type]
            if feature not in by_interface.setdefault(key, {}):
                if row.value is not None and math.isfinite(row.value):
                    by_interface[key][feature] = row

        candidates = [
            (key, records)
            for key, records in by_interface.items()
            if all(feature in records for feature in CORE_FEATURES)
        ]
        if not candidates:
            return None
        interface, records = max(
            candidates,
            key=lambda item: max(row.timestamp for row in item[1].values()),
        )
        features = {feature: None for feature in MODEL_FEATURES}
        for feature, row in records.items():
            features[feature] = row.value
        sample_timestamp = max(row.timestamp for row in records.values())
        sample_ref = {
            "interface_id": interface[0],
            "node_id": interface[1],
            "metric_ids": {feature: row.id for feature, row in records.items()},
            "metric_timestamps": {
                feature: row.timestamp.replace(tzinfo=timezone.utc).isoformat()
                for feature, row in records.items()
            },
            "sample_timestamp": sample_timestamp.replace(tzinfo=timezone.utc).isoformat(),
        }
        return features, sample_ref, sample_timestamp

    @staticmethod
    def _existing_sample(db: Session, sample_key: str, cutoff: datetime) -> bool:
        recent_predictions = (
            db.query(PredictionRecord)
            .filter(
                PredictionRecord.model_name == MODEL_NAME,
                PredictionRecord.created_at >= cutoff.replace(tzinfo=None),
            )
            .order_by(PredictionRecord.created_at.desc())
            .limit(100)
            .all()
        )
        return any(
            json.dumps(
                (record.feature_snapshot or {}).get("input_sample_ref", {}).get("metric_ids", {}),
                sort_keys=True,
            ) == sample_key
            for record in recent_predictions
        )

    @staticmethod
    def _persist_incident(
        db: Session,
        prediction: dict[str, Any],
        diagnosis: dict[str, Any],
        metrics: dict[str, Any],
        sample_ref: dict[str, Any],
        created_at: datetime,
    ) -> None:
        incident_type = diagnosis["fault_type"]
        db.add(NetworkIncident(
            incident_id=f"INC-{uuid.uuid4().hex[:12].upper()}",
            timestamp=created_at,
            status="diagnosed",
            affected_node=sample_ref["node_id"] or sample_ref["interface_id"] or "monitored-host",
            affected_component=sample_ref["interface_id"] or sample_ref["node_id"],
            incident_type=incident_type,
            description=diagnosis["explanation"],
            metrics=metrics,
            prediction_confidence=prediction["probability"],
            predicted_fault=prediction["label"],
            ml_prediction=prediction,
            confidence=diagnosis["confidence"],
            root_cause=diagnosis["explanation"],
            severity=diagnosis["severity"].lower(),
            prediction_explanation={
                "model_version": prediction["model_version"],
                "observed_features": prediction["observed_features"],
                "imputed_features": prediction["imputed_features"],
                "input_sample_ref": sample_ref,
            },
            diagnosis_reasoning=diagnosis,
        ))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.process_once()
            except Exception:
                logger.exception("Telemetry inference cycle failed.")
                self._update_status(
                    running=True,
                    state="error",
                    reason="Inference failed; see backend logs for the exception.",
                )
            self._stop_event.wait(self._interval_seconds)
        self._update_status(running=False, state="stopped")

    def _is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())

    def _update_status(self, **values: Any) -> None:
        with self._status_lock:
            self._status.update(values)


_pipeline = TelemetryInferencePipeline()


def initialize_telemetry_inference() -> TelemetryInferencePipeline:
    _pipeline.start()
    return _pipeline


def shutdown_telemetry_inference() -> None:
    _pipeline.stop()


def get_telemetry_inference_status() -> dict[str, Any]:
    return _pipeline.status()

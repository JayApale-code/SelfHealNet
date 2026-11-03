"""Persistent incident lifecycle logging."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Optional

try:
    from ..database import IncidentFinalStatus, NetworkIncident, SeverityLevel
except ImportError:
    IncidentFinalStatus = None
    NetworkIncident = None
    SeverityLevel = None


class IncidentLogger:
    """Store complete incident records and update their lifecycle state."""

    def __init__(self, db_session=None):
        self.db = db_session
        self.records: Dict[str, Dict[str, Any]] = {}

    def create_incident(
        self,
        incident_id: str,
        detected_fault: str,
        affected_component: str,
        metrics: Mapping[str, Any],
        ml_prediction: Mapping[str, Any],
        confidence: float,
        severity: str,
        selected_action: Optional[str] = None,
        safety_result: Optional[Mapping[str, Any]] = None,
        recovery_result: Optional[Mapping[str, Any]] = None,
        verification_metrics: Optional[Mapping[str, Any]] = None,
        fallback_action: Optional[Mapping[str, Any]] = None,
        final_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and persist the complete incident audit record."""
        if incident_id in self.records:
            raise ValueError(f"Incident '{incident_id}' already exists")
        if final_status is not None and str(final_status).upper() not in {"RESOLVED", "FAILED", "ESCALATED"}:
            raise ValueError("final_status must be RESOLVED, FAILED, or ESCALATED")
        record = {
            "incident_id": incident_id,
            "timestamp": datetime.utcnow().isoformat(),
            "detected_fault": detected_fault,
            "affected_component": affected_component,
            "metrics": dict(metrics),
            "ml_prediction": dict(ml_prediction),
            "confidence": float(confidence),
            "severity": str(severity).upper(),
            "selected_action": selected_action,
            "safety_result": dict(safety_result) if safety_result else None,
            "recovery_result": dict(recovery_result) if recovery_result else None,
            "verification_metrics": dict(verification_metrics) if verification_metrics else None,
            "fallback_action": dict(fallback_action) if fallback_action else None,
            "final_status": final_status,
        }
        self.records[incident_id] = record
        self._persist_new(record)
        return record

    def update_incident(self, incident_id: str, **updates: Any) -> Dict[str, Any]:
        """Update lifecycle fields without discarding previously logged data."""
        if incident_id not in self.records:
            raise KeyError(f"Incident '{incident_id}' does not exist")
        allowed = {
            "selected_action", "safety_result", "recovery_result",
            "verification_metrics", "fallback_action", "final_status",
        }
        invalid = set(updates) - allowed
        if invalid:
            raise ValueError(f"Unsupported incident updates: {sorted(invalid)}")
        if "final_status" in updates and str(updates["final_status"]).upper() not in {"RESOLVED", "FAILED", "ESCALATED"}:
            raise ValueError("final_status must be RESOLVED, FAILED, or ESCALATED")
        self.records[incident_id].update(updates)
        self._persist_update(incident_id, updates)
        return self.records[incident_id]

    def _persist_new(self, record: Dict[str, Any]) -> None:
        if self.db is None or NetworkIncident is None:
            return
        severity = record["severity"].lower()
        incident = NetworkIncident(
            incident_id=record["incident_id"],
            incident_type=record["detected_fault"],
            predicted_fault=record["ml_prediction"].get("label"),
            prediction_confidence=record["ml_prediction"].get("probability"),
            affected_node=record["affected_component"],
            affected_component=record["affected_component"],
            metrics=record["metrics"],
            ml_prediction=record["ml_prediction"],
            confidence=record["confidence"],
            severity=SeverityLevel(severity) if SeverityLevel else severity,
            selected_action=record["selected_action"],
            safety_result=record["safety_result"],
            recovery_result=record["recovery_result"],
            verification_metrics=record["verification_metrics"],
            fallback_action=record["fallback_action"],
            final_status=record["final_status"],
        )
        self.db.add(incident)
        self.db.commit()

    def _persist_update(self, incident_id: str, updates: Dict[str, Any]) -> None:
        if self.db is None or NetworkIncident is None:
            return
        incident = self.db.query(NetworkIncident).filter(
            NetworkIncident.incident_id == incident_id
        ).first()
        if incident is None:
            raise KeyError(f"Incident '{incident_id}' does not exist in database")
        for field, value in updates.items():
            setattr(incident, field, value)
        self.db.commit()


_logger = None


def get_incident_logger(db_session=None) -> IncidentLogger:
    """Return the process incident logger, optionally binding a DB session."""
    global _logger
    if _logger is None or db_session is not None:
        _logger = IncidentLogger(db_session)
    return _logger
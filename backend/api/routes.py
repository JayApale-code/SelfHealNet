"""Validated Phase 14 REST and WebSocket endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.config import config
from backend.auth.sms import SmsProvider, get_sms_provider
from backend.database import (
    AlertRecord,
    FaultRecord,
    NetworkHistoryEntry,
    NetworkIncident,
    NetworkLink,
    NetworkMetric,
    NetworkNode,
    NotificationRecord,
    PasswordResetToken,
    PredictionRecord,
    RecoveryAttempt,
    RecoveryRecord,
    User,
    UserLoginActivity,
    UserSession,
    UserSettings,
    get_db,
)
from backend.diagnosis import DiagnosisEngine
from backend.monitoring import get_monitor
from backend.explainability import ExplainableDecisionEngine
from backend.incident_logging import IncidentLogger
from backend.recovery import RecoveryOrchestrator
from backend.risk_assessment import RiskAssessmentEngine
from backend.safety import SafetyChecker
from backend.verification import VerificationEngine
from backend.ml_engine import get_fault_prediction_model
from backend.ml_engine.telemetry_pipeline import get_telemetry_inference_status
from ml.predict import predict_from_record
from sdn_controller.ryu_adapter import RyuControllerAdapter

router = APIRouter(prefix="/api/v1", tags=["network"])


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_password(password: str, password_hash: str) -> bool:
    if not password_hash or not password_hash.startswith("pbkdf2_sha256$"):
        return False
    _, salt, expected = password_hash.split("$", 2)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return hmac.compare_digest(digest.hex(), expected)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_otp(otp: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", otp.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"{salt}${digest.hex()}"


def _verify_otp(otp: str, otp_hash: str) -> bool:
    parts = otp_hash.split("$", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    digest = hashlib.pbkdf2_hmac("sha256", otp.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return hmac.compare_digest(digest.hex(), expected)


def _record_successful_login(db: Session, user: User, request: Optional[Request] = None) -> None:
    login_at = datetime.utcnow()
    user.last_login_at = login_at
    db.add(
        UserLoginActivity(
            user_id=user.id,
            login_at=login_at,
            ip_address=request.client.host if request and request.client else None,
            success=True,
        )
    )
    db.commit()
    db.refresh(user)


def _create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    session = UserSession(
        user_id=user.id,
        token_hash=_hash_token(token),
        expires_at=datetime.utcnow() + timedelta(days=7),
        created_at=datetime.utcnow(),
        last_used_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    return token


def _get_token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    token = _get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token_hash = _hash_token(token)
    session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not session or session.revoked or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid")

    user = db.query(User).filter(User.id == session.user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    session.last_used_at = datetime.utcnow()
    db.commit()
    return user


def get_or_create_user_settings(db: Session, user_id: int) -> UserSettings:
    settings = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if settings is None:
        settings = UserSettings(
            user_id=user_id,
            refresh_interval=30,
            notification_enabled=True,
            email_alerts=True,
            push_notifications=True,
            monitoring_settings={"time_range": "15m"},
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _serialize_user(user: User) -> Dict[str, Any]:
    mobile_number = user.mobile_number or ""
    return {
        "id": user.id,
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "mobile_number": f"***{mobile_number[-4:]}" if mobile_number else None,
        "account_status": user.account_status,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


class MetricPayload(BaseModel):
    node_id: str = Field(min_length=1, max_length=255)
    metric_type: str = Field(min_length=1, max_length=80)
    value: float
    unit: str = Field(default="", max_length=20)


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    username: str = Field(min_length=3, max_length=80)
    email: str = Field(min_length=3, max_length=180)
    mobile_number: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=180)
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=180)


class VerifyResetOtpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    otp: str = Field(pattern=r"^\d{6}$")


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=180)
    mobile_number: str | None = Field(default=None, min_length=8, max_length=20)


class SettingsUpdateRequest(BaseModel):
    refresh_interval: int | None = Field(default=None, ge=5, le=600)
    notification_enabled: bool | None = None
    email_alerts: bool | None = None
    push_notifications: bool | None = None
    monitoring_settings: Dict[str, Any] | None = None


class AuthResponse(BaseModel):
    user: Dict[str, Any]
    token: str
    message: str


@router.post("/auth/register", status_code=201, response_model=AuthResponse)
def register_user(request: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    username = request.username.strip()
    email = request.email.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        full_name=request.full_name.strip(),
        username=username,
        email=email,
        mobile_number=request.mobile_number.strip(),
        password_hash=_hash_password(request.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    get_or_create_user_settings(db, user.id)

    token = _create_session(db, user)
    _record_successful_login(db, user)

    return AuthResponse(
        user=_serialize_user(user),
        token=token,
        message="Registration successful",
    )


@router.post("/auth/login", response_model=AuthResponse)
def login_user(
    request: LoginRequest,
    http_request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    identifier = request.username_or_email.strip().lower()
    user = db.query(User).filter((User.username == identifier) | (User.email == identifier)).first()
    if not user or not _verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    token = _create_session(db, user)
    _record_successful_login(db, user, http_request)

    return AuthResponse(
        user=_serialize_user(user),
        token=token,
        message="Login successful",
    )


@router.post("/auth/logout")
def logout_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    token = _get_token_from_header(authorization)
    if token:
        session = db.query(UserSession).filter(UserSession.token_hash == _hash_token(token)).first()
        if session:
            session.revoked = True
            session.last_used_at = datetime.utcnow()
    db.commit()
    return {"message": "Logged out successfully"}


@router.post("/auth/forgot-password")
def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db),
    sms_provider: SmsProvider = Depends(get_sms_provider),
) -> Dict[str, str]:
    user = db.query(User).filter(User.email == request.email.strip().lower()).first()
    if config.DEBUG and user and user.mobile_number:
        now = datetime.utcnow()
        otp = f"{secrets.randbelow(1_000_000):06d}"
        reset_entry = PasswordResetToken(
            user_id=user.id,
            token=_hash_token(secrets.token_urlsafe(32)),
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            otp_hash=_hash_otp(otp),
            attempt_count=0,
        )
        db.add(reset_entry)
        db.commit()
        sms_provider.send_otp(user.mobile_number, otp)
    if config.DEBUG:
        message = "If the account exists, a development-only mock code was requested. No SMS was sent."
    else:
        message = "If the account exists, reset instructions will be available when an SMS provider is configured. No SMS was sent."
    return {"message": message}


@router.post("/auth/verify-reset-otp")
def verify_reset_otp(request: VerifyResetOtpRequest, db: Session = Depends(get_db)) -> Dict[str, str]:
    user = db.query(User).filter(User.email == request.email.strip().lower()).first()
    now = datetime.utcnow()
    reset_entry = None
    if user:
        reset_entry = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.otp_hash.is_not(None),
                PasswordResetToken.verified_at.is_(None),
                PasswordResetToken.used_at.is_(None),
            )
            .order_by(PasswordResetToken.created_at.desc())
            .first()
        )

    if (
        not reset_entry
        or reset_entry.otp_hash is None
        or reset_entry.expires_at <= now
        or reset_entry.attempt_count >= 5
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    if not _verify_otp(request.otp, reset_entry.otp_hash):
        reset_entry.attempt_count += 1
        if reset_entry.attempt_count >= 5:
            reset_entry.used_at = now
            reset_entry.otp_hash = None
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    reset_token = secrets.token_urlsafe(32)
    reset_entry.otp_hash = None
    reset_entry.verified_at = now
    reset_entry.expires_at = now + timedelta(minutes=10)
    reset_entry.reset_token_hash = _hash_token(reset_token)
    db.commit()
    return {"message": "Verification successful. You may reset your password.", "reset_token": reset_token}


@router.post("/auth/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)) -> Dict[str, str]:
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    token_hash = _hash_token(request.token)
    reset_entry = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.reset_token_hash == token_hash,
            PasswordResetToken.verified_at.is_not(None),
        )
        .first()
    )
    if not reset_entry:
        raise HTTPException(status_code=404, detail="Invalid or expired reset token")
    if reset_entry.used_at is not None or reset_entry.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == reset_entry.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = _hash_password(request.new_password)
    reset_entry.used_at = datetime.utcnow()
    db.commit()
    return {"message": "Password reset successful"}


@router.get("/users/me")
def get_current_user_profile(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return _serialize_user(current_user)


@router.put("/users/me")
def update_current_user_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if request.full_name is not None:
        current_user.full_name = request.full_name.strip()
    if request.email is not None:
        email = request.email.strip().lower()
        if email != current_user.email and db.query(User).filter(User.email == email, User.id != current_user.id).first():
            raise HTTPException(status_code=409, detail="Email already exists")
        current_user.email = email
    if request.mobile_number is not None:
        current_user.mobile_number = request.mobile_number.strip()
    db.commit()
    db.refresh(current_user)
    return _serialize_user(current_user)


@router.get("/users/login-history")
def get_login_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dict[str, Any]:
    history = (
        db.query(UserLoginActivity)
        .filter(UserLoginActivity.user_id == current_user.id)
        .order_by(UserLoginActivity.login_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "login_at": item.login_at.isoformat() if item.login_at else None,
                "ip_address": item.ip_address,
                "user_agent": item.user_agent,
                "success": item.success,
            }
            for item in history
        ],
        "count": len(history),
    }


@router.post("/users/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if not _verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    current_user.password_hash = _hash_password(request.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@router.get("/users/settings")
def get_current_user_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = get_or_create_user_settings(db, current_user.id)
    return {
        "refresh_interval": settings.refresh_interval,
        "notification_enabled": settings.notification_enabled,
        "email_alerts": settings.email_alerts,
        "push_notifications": settings.push_notifications,
        "monitoring_settings": settings.monitoring_settings or {},
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


@router.put("/users/settings")
def update_current_user_settings(
    request: SettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = get_or_create_user_settings(db, current_user.id)
    values = request.model_dump(exclude_unset=True) if hasattr(request, "model_dump") else request.dict(exclude_unset=True)
    for key, value in values.items():
        setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return {
        "refresh_interval": settings.refresh_interval,
        "notification_enabled": settings.notification_enabled,
        "email_alerts": settings.email_alerts,
        "push_notifications": settings.push_notifications,
        "monitoring_settings": settings.monitoring_settings or {},
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


@router.get("/alerts")
def get_alerts(
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    records = db.query(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(limit).all()
    return {"alerts": [{
        "id": item.id,
        "alert_type": item.alert_type,
        "severity": item.severity,
        "message": item.message,
        "affected_node": item.affected_node,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "acknowledged_at": item.acknowledged_at.isoformat() if item.acknowledged_at else None,
    } for item in records], "count": len(records)}


@router.get("/notifications")
def get_notifications(
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    records = (
        db.query(NotificationRecord)
        .filter(NotificationRecord.user_id == current_user.id)
        .order_by(NotificationRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"notifications": [{
        "id": item.id,
        "type": item.type,
        "severity": item.severity,
        "message": item.message,
        "read_at": item.read_at.isoformat() if item.read_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    } for item in records], "count": len(records)}


class DiagnosisRequest(BaseModel):
    live_metrics: Dict[str, Any]
    ml_prediction: Dict[str, Any] = Field(default_factory=dict)
    topology: Dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "links": []})
    affected_node: Optional[str] = None
    affected_link: Optional[str] = None


class RecoveryActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    target: Optional[str] = Field(default=None, max_length=255)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RecoveryWorkflowRequest(BaseModel):
    live_metrics: Dict[str, Any]
    topology: Dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "links": []})
    affected_component: Optional[str] = None
    network_state: Dict[str, Any] = Field(default_factory=dict)
    post_recovery_metrics: Optional[Dict[str, Any]] = None


class PredictionPayload(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    probability: float = Field(ge=0.0, le=1.0)
    component: Optional[str] = Field(default=None, max_length=255)


class IncidentPayload(BaseModel):
    incident_id: str = Field(min_length=1, max_length=255)
    detected_fault: str = Field(min_length=1, max_length=100)
    affected_component: str = Field(min_length=1, max_length=255)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    ml_prediction: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    severity: str = Field(min_length=1, max_length=20)
    final_status: Optional[str] = Field(default=None, pattern="^(RESOLVED|FAILED|ESCALATED)$")


class APIState:
    """Small state adapter used by the API until database-backed services are wired."""

    def __init__(self) -> None:
        self.metrics: List[Dict[str, Any]] = []
        self.topology: Dict[str, Any] = {"nodes": [], "links": []}
        self.predictions: List[Dict[str, Any]] = []
        self.faults: List[Dict[str, Any]] = []
        self.recovery_actions: List[Dict[str, Any]] = []
        self.recovery_status: Dict[str, Any] = {"status": "idle", "active_recovery": None}
        self.incidents: List[Dict[str, Any]] = []
        self.model: Dict[str, Any] = {"status": "not_loaded", "version": None}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "network_status": self.network_status(),
            "live_metrics": self.metrics[-100:],
            "active_faults": self.faults,
            "recovery_status": self.recovery_status,
        }

    def network_status(self) -> Dict[str, Any]:
        return {
            "status": "degraded" if self.faults else "healthy",
            "nodes": len(self.topology.get("nodes", [])),
            "links": len(self.topology.get("links", [])),
            "active_faults": len(self.faults),
            "last_metric_at": self.metrics[-1].get("timestamp") if self.metrics else None,
        }


state = APIState()
monitor = get_monitor()
sdn_controller = RyuControllerAdapter(
    controller_url=config.SDN_CONTROLLER_URL,
    timeout_seconds=config.SDN_CONTROLLER_API_TIMEOUT_SECONDS,
    retry_interval_seconds=config.SDN_RETRY_INTERVAL_SECONDS,
    username=config.SDN_CONTROLLER_USERNAME,
    password=config.SDN_CONTROLLER_PASSWORD,
    controller_type=config.SDN_CONTROLLER_TYPE,
)
diagnosis_engine = DiagnosisEngine()
risk_engine = RiskAssessmentEngine()
decision_engine = ExplainableDecisionEngine()
safety_checker = SafetyChecker()
verification_engine = VerificationEngine()


def _as_number(metrics: Dict[str, Any], names: tuple[str, ...], default: float = 0.0) -> float:
    for name in names:
        if name in metrics:
            try:
                return float(metrics[name])
            except (TypeError, ValueError):
                continue
    return default


def _as_optional_number(metrics: Dict[str, Any], names: tuple[str, ...]) -> Optional[float]:
    for name in names:
        if name in metrics:
            try:
                return float(metrics[name])
            except (TypeError, ValueError):
                continue
    return None


def _ml_input(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "latency_ms": _as_optional_number(metrics, ("latency_ms", "latency", "latency_mean")),
        "jitter_ms": _as_optional_number(metrics, ("jitter_ms", "jitter")),
        "packet_loss_pct": _as_optional_number(metrics, ("packet_loss_pct", "packet_loss", "packet_loss_mean")),
        "throughput_mbps": _as_optional_number(metrics, ("throughput_mbps", "throughput")),
        "bandwidth_utilization_pct": _as_optional_number(metrics, ("bandwidth_utilization_pct", "bandwidth_usage", "bandwidth_util")),
        "cpu_utilization_pct": _as_optional_number(metrics, ("cpu_utilization_pct", "cpu_usage_pct", "cpu_usage")),
        "memory_utilization_pct": _as_optional_number(metrics, ("memory_utilization_pct", "memory_usage_pct", "memory_usage")),
        "active_flows": _as_optional_number(metrics, ("active_flows",)),
        "retransmissions_pct": _as_optional_number(metrics, ("retransmissions_pct", "retransmissions")),
        "dropped_packets": _as_optional_number(metrics, ("dropped_packets", "dropped")),
        "link_status": metrics.get("link_status"),
        "route_redundancy": _as_optional_number(metrics, ("route_redundancy",)),
        "connectivity_score": _as_optional_number(metrics, ("connectivity_score",)),
        "source": metrics.get("source"),
        "destination": metrics.get("destination"),
        "fault_scenario": metrics.get("fault_scenario"),
    }


def _live_metric_records(db: Session, limit: int = 100) -> List[Dict[str, Any]]:
    freshness_seconds = max(60, config.MONITORING_INTERVAL * 3)
    cutoff = datetime.utcnow() - timedelta(seconds=freshness_seconds)
    records = (
        db.query(NetworkMetric)
        .filter(NetworkMetric.timestamp >= cutoff)
        .order_by(NetworkMetric.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [{
        "node_id": item.node_id,
        "metric_type": item.metric_type,
        "value": item.value,
        "unit": item.unit,
        "timestamp": item.timestamp.isoformat(),
        "interface_id": item.interface_id,
    } for item in reversed(records)]


def _apply_metric_freshness(network_status: Dict[str, Any], metrics: List[Dict[str, Any]]) -> None:
    latest = metrics[-1] if metrics else None
    network_status["last_metric_at"] = latest["timestamp"] if latest else None
    if latest is None:
        network_status["status"] = "unknown"
    else:
        network_status["status"] = "degraded" if network_status["active_faults"] else "healthy"


def _action_for_decision(decision: Dict[str, Any], request: RecoveryWorkflowRequest) -> Dict[str, Any]:
    action_name = decision["selected_action"]
    target = decision.get("affected_component") or request.affected_component or "network"
    alternate_path = request.network_state.get("alternate_path")
    if action_name in {"REROUTE_TRAFFIC", "FAILOVER"} and alternate_path:
        return {"type": "update_routing", "flow_id": target, "path": alternate_path}
    if action_name in {"TRAFFIC_ENGINEERING", "APPLY_QOS"}:
        action_type = "adjust_weights" if action_name == "TRAFFIC_ENGINEERING" else "apply_qos"
        return {"type": action_type, "target": target}
    return {"type": "alert_ops", "target": target, "severity": "critical"}


def _sdn_available(controller: Any = None) -> bool:
    if not config.SDN_CONTROLLER_URL:
        return False
    return bool(
        controller
        and getattr(controller, "write_operations_enabled", False)
        and controller.has_real_connection()
    )


def _db_topology_snapshot(db: Session) -> Dict[str, Any]:
    nodes = [
        {"id": item.node_id, "name": item.name, "type": item.node_type, "status": item.status, "metadata": item.node_metadata or {}}
        for item in db.query(NetworkNode).order_by(NetworkNode.id.asc()).all()
    ]
    if not nodes:
        metric_nodes = db.query(NetworkMetric.node_id).distinct().order_by(NetworkMetric.node_id.asc()).all()
        for (node_id,) in metric_nodes:
            if node_id and node_id not in {item["id"] for item in nodes}:
                node_type = "router" if "router" in node_id.lower() else "switch" if "switch" in node_id.lower() else "host"
                nodes.append({
                    "id": node_id,
                    "name": node_id.replace("-", " ").title(),
                    "type": node_type,
                    "status": "healthy",
                    "metadata": {},
                })
    links = [
        {"source": item.source, "target": item.target, "id": item.link_id, "status": item.status, "capacity": item.capacity, "metadata": item.link_metadata or {}}
        for item in db.query(NetworkLink).order_by(NetworkLink.id.asc()).all()
    ]
    if not links and len(nodes) > 1:
        links = [
            {"source": nodes[0]["id"], "target": nodes[1]["id"], "id": f"link-{idx}", "status": "active", "capacity": "1 Gbps", "metadata": {}}
            for idx in range(min(2, len(nodes) - 1))
        ]
    return {"nodes": nodes, "links": links}


def _db_active_faults(db: Session) -> List[Dict[str, Any]]:
    records = (
        db.query(FaultRecord)
        .filter(FaultRecord.status.in_(["open", "active", "detected", "investigating"]))
        .order_by(FaultRecord.detection_time.desc())
        .all()
    )
    if records:
        return [{
            "fault_id": item.fault_id,
            "fault_type": item.fault_type,
            "affected_component": item.affected_component or item.affected_node,
            "severity": item.severity,
            "status": item.status,
            "root_cause": item.root_cause,
            "summary": item.summary,
            "detected_at": item.detection_time.isoformat() if item.detection_time else None,
        } for item in records]

    incident_rows = (
        db.query(NetworkIncident)
        .filter(
            NetworkIncident.status.notin_(["recovered", "resolved", "failed", "closed"]),
            NetworkIncident.final_status.notin_(["RESOLVED", "FAILED"]),
        )
        .order_by(NetworkIncident.timestamp.desc())
        .limit(10)
        .all()
    )
    return [{
        "fault_id": item.incident_id,
        "fault_type": item.incident_type,
        "affected_component": item.affected_component or item.affected_node,
        "severity": item.severity,
        "status": item.status or "detected",
        "root_cause": item.root_cause,
        "summary": item.description,
        "detected_at": item.timestamp.isoformat() if item.timestamp else None,
    } for item in incident_rows]


@router.get("/network/status")
def network_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    topology = _db_topology_snapshot(db)
    active_faults = _db_active_faults(db)
    metrics = _live_metric_records(db, limit=1)
    result = {
        "status": "degraded" if active_faults else "healthy",
        "nodes": len(topology.get("nodes", [])),
        "links": len(topology.get("links", [])),
        "active_faults": len(active_faults),
        "last_metric_at": metrics[-1]["timestamp"] if metrics else None,
    }
    _apply_metric_freshness(result, metrics)
    return result


@router.get("/network/info")
def network_info() -> Dict[str, Any]:
    response = monitor.get_network_identity()
    response["connection_details"]["sdn_controller"] = _sdn_status_snapshot()
    return response


def _sdn_status_snapshot() -> Dict[str, Any]:
    if config.SDN_SIMULATION_ENABLED:
        simulated_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "SIMULATED",
            "source": "simulation",
            "configured": False,
            "controller_url": None,
            "mode": "simulation",
            "write_operations_enabled": False,
            "timestamp": simulated_at,
            "last_check_at": simulated_at,
            "error": "Simulation is explicitly enabled; this is not a real controller connection.",
            "partial_errors": [],
            "topology": state.topology,
            "switches": [],
            "flow_count": None,
        }
    return sdn_controller.snapshot()


@router.get("/sdn/status")
def sdn_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return read-only controller health, topology, and switch statistics."""
    snapshot = _sdn_status_snapshot()
    if not snapshot.get("topology") or not snapshot["topology"].get("nodes") and not snapshot["topology"].get("links"):
        snapshot["topology"] = _db_topology_snapshot(db)
        if snapshot.get("switches") in (None, []):
            snapshot["switches"] = [item["id"] for item in snapshot["topology"].get("nodes", []) if item.get("type") in {"switch", "router"}]
    return snapshot


@router.get("/metrics/live")
def live_metrics(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    metrics = _live_metric_records(db, limit=limit)
    return {"metrics": metrics, "count": len(metrics)}


@router.get("/system/memory")
def system_memory(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return recent system memory measurements collected from the host."""
    metric_names = {
        "total_mb": "memory_total_mb",
        "used_mb": "memory_used_mb",
        "available_mb": "memory_available_mb",
        "usage_pct": "memory_utilization_pct",
    }
    freshness_seconds = max(60, config.MONITORING_INTERVAL * 3)
    cutoff = datetime.utcnow() - timedelta(seconds=freshness_seconds)
    usage_metric = (
        db.query(NetworkMetric)
        .filter(
            NetworkMetric.metric_type == metric_names["usage_pct"],
            NetworkMetric.timestamp >= cutoff,
        )
        .order_by(NetworkMetric.timestamp.desc(), NetworkMetric.id.desc())
        .first()
    )
    latest = {}
    for field, metric_type in metric_names.items():
        query = (
            db.query(NetworkMetric)
            .filter(
                NetworkMetric.metric_type == metric_type,
                NetworkMetric.timestamp >= cutoff,
            )
        )
        if usage_metric is not None:
            query = query.filter(NetworkMetric.node_id == usage_metric.node_id)
        latest[field] = query.order_by(NetworkMetric.timestamp.desc(), NetworkMetric.id.desc()).first()

    missing_fields = [field for field, record in latest.items() if record is None]
    available_records = [record for record in latest.values() if record is not None]
    measured_at = max(
        (record.timestamp for record in available_records),
        default=None,
    )
    response = {
        field: record.value if record is not None else None
        for field, record in latest.items()
    }
    response.update({
        "status": "available" if not missing_fields else "unavailable",
        "unit": "MB",
        "usage_unit": "%",
        "timestamp": measured_at.isoformat() if measured_at else None,
        "source": "psutil host memory telemetry",
        "reason": (
            None if not missing_fields else
            "Recent memory telemetry is incomplete or has not been collected: "
            + ", ".join(missing_fields)
        ),
    })
    return response


@router.post("/metrics/live", status_code=201)
def record_live_metric(metric: MetricPayload) -> Dict[str, Any]:
    record = metric.model_dump() if hasattr(metric, "model_dump") else metric.dict()
    stored = monitor.collect_metric(
        node_id=record["node_id"],
        metric_type=record["metric_type"],
        value=record["value"],
        unit=record["unit"],
    )
    monitor.flush_metrics()
    response = {
        "node_id": stored.node_id,
        "metric_type": stored.metric_type,
        "value": stored.value,
        "unit": stored.unit,
        "timestamp": stored.timestamp.isoformat(),
        "interface_id": stored.interface_id,
    }
    state.metrics.append(response)
    return response


@router.get("/topology")
def topology(db: Session = Depends(get_db)) -> Dict[str, Any]:
    snapshot = _sdn_status_snapshot()
    if not snapshot.get("topology") or not snapshot["topology"].get("nodes") and not snapshot["topology"].get("links"):
        snapshot["topology"] = _db_topology_snapshot(db)
    return {
        **snapshot["topology"],
        "status": snapshot["status"],
        "source": snapshot["source"],
        "mode": snapshot["mode"],
        "configured": snapshot["configured"],
        "controller_url": snapshot["controller_url"],
        "timestamp": snapshot["timestamp"],
        "last_check_at": snapshot["last_check_at"],
        "error": snapshot["error"],
        "partial_errors": snapshot["partial_errors"],
        "switches": snapshot["switches"],
        "flow_count": snapshot["flow_count"],
        "write_operations_enabled": snapshot["write_operations_enabled"],
    }


@router.put("/topology")
def replace_topology(value: Dict[str, Any]) -> Dict[str, Any]:
    nodes = value.get("nodes", [])
    links = value.get("links", [])
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise HTTPException(status_code=422, detail="topology nodes and links must be lists")
    state.topology = {"nodes": nodes, "links": links}
    return state.topology


@router.get("/predictions")
def predictions(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    records = (
        db.query(PredictionRecord)
        .order_by(PredictionRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "predictions": [{
            "prediction_id": item.prediction_id,
            "label": item.prediction_label,
            "probability": item.probability,
            "component": (item.feature_snapshot or {}).get("component"),
            "timestamp": item.created_at.isoformat() if item.created_at else None,
            "model_name": item.model_name,
            "model_version": (item.feature_snapshot or {}).get("model_version"),
            "input_sample_ref": (item.feature_snapshot or {}).get("input_sample_ref"),
            "observed_features": (item.feature_snapshot or {}).get("observed_features", []),
            "imputed_features": (item.feature_snapshot or {}).get("imputed_features", []),
        } for item in records],
        "count": len(records),
    }


@router.post("/predictions", status_code=201)
def record_prediction(
    prediction: PredictionPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    record = prediction.model_dump() if hasattr(prediction, "model_dump") else prediction.dict()
    timestamp = datetime.now(timezone.utc)
    record.update({
        "prediction_id": f"PRED-{uuid.uuid4().hex[:12].upper()}",
        "timestamp": timestamp.isoformat(),
    })
    db_record = PredictionRecord(
        prediction_id=record["prediction_id"],
        model_name="SelfHealNet RandomForest",
        prediction_label=record["label"],
        probability=record["probability"],
        confidence=record["probability"],
        feature_snapshot={"component": record["component"]},
        created_at=timestamp.replace(tzinfo=None),
    )
    db.add(db_record)
    db.commit()
    state.predictions.append(record)
    return record


@router.get("/faults/active")
def active_faults(db: Session = Depends(get_db)) -> Dict[str, Any]:
    faults = _db_active_faults(db)
    return {"faults": faults, "count": len(faults)}


@router.post("/diagnosis")
def diagnose(request: DiagnosisRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        result = diagnosis_engine.diagnose(
            live_metrics=request.live_metrics,
            ml_prediction=request.ml_prediction,
            topology=request.topology,
            affected_node=request.affected_node,
            affected_link=request.affected_link,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    prediction_label = request.ml_prediction.get("label", request.ml_prediction.get("fault_type"))
    prediction_probability = request.ml_prediction.get(
        "probability",
        request.ml_prediction.get("confidence"),
    )
    if prediction_label is not None and prediction_probability is not None:
        try:
            prediction = PredictionPayload(
                label=str(prediction_label),
                probability=float(prediction_probability),
                component=result["affected_component"],
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid ML prediction: {exc}") from exc
        timestamp = datetime.now(timezone.utc)
        db.add(PredictionRecord(
            prediction_id=f"PRED-{uuid.uuid4().hex[:12].upper()}",
            model_name="SelfHealNet RandomForest",
            prediction_label=prediction.label,
            probability=prediction.probability,
            confidence=prediction.probability,
            feature_snapshot={
                **_ml_input(request.live_metrics),
                "component": result["affected_component"],
            },
            created_at=timestamp.replace(tzinfo=None),
        ))

    if result["fault_type"] != "NORMAL":
        incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
        timestamp = datetime.now(timezone.utc)
        db.add(NetworkIncident(
            incident_id=incident_id,
            timestamp=timestamp.replace(tzinfo=None),
            status="diagnosed",
            affected_node=result["affected_component"],
            affected_component=result["affected_component"],
            incident_type=result["fault_type"],
            description=result["explanation"],
            metrics=request.live_metrics,
            ml_prediction=request.ml_prediction,
            confidence=result["confidence"],
            prediction_confidence=request.ml_prediction.get(
                "probability",
                request.ml_prediction.get("confidence"),
            ),
            predicted_fault=prediction_label,
            root_cause=result["explanation"],
            diagnosis_reasoning=result["supporting_metrics"],
            severity=result["severity"].lower(),
        ))
        result["incident_id"] = incident_id
        result["timestamp"] = timestamp.isoformat()

    db.commit()
    state.faults = [] if result["fault_type"] == "NORMAL" else [result]
    return result


@router.post("/recovery/actions", status_code=201)
def create_recovery_action(
    request: RecoveryActionRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    action = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    action.update({"status": "pending", "created_at": datetime.now(timezone.utc).isoformat()})
    db.add(RecoveryRecord(
        recovery_id=f"REC-{uuid.uuid4().hex[:12].upper()}",
        recommended_action=request.action,
        reason=json.dumps({"target": request.target, "parameters": request.parameters}),
        recovery_action=request.action,
        result="pending",
        safety_check="pending",
        status="pending",
    ))
    db.commit()
    state.recovery_actions.append(action)
    state.recovery_status = _latest_persisted_recovery_status(db)
    return action


@router.post("/recovery/workflow", status_code=201)
def run_recovery_workflow(
    request: RecoveryWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Run and persist one real detect-to-verify recovery workflow."""
    incident_id = f"INC-{uuid.uuid4().hex[:12].upper()}"
    recovery_id = f"REC-{uuid.uuid4().hex[:12].upper()}"
    metrics = dict(request.live_metrics)

    try:
        prediction = predict_from_record(_ml_input(metrics))
    except (FileNotFoundError, KeyError, OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"ML Model Not Available: {exc}") from exc

    state.predictions.append({
        "label": prediction["label"],
        "probability": prediction["probability"],
        "component": request.affected_component,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    db.add(PredictionRecord(
        prediction_id=f"PRED-{uuid.uuid4().hex[:12].upper()}",
        model_name="SelfHealNet RandomForest",
        prediction_label=prediction["label"],
        probability=prediction["probability"],
        confidence=prediction["probability"],
        feature_snapshot={
            **_ml_input(metrics),
            "component": request.affected_component,
        },
    ))
    state.model = {"status": "loaded", "version": config.MODEL_VERSION, "path": config.MODEL_PATH}

    sdn_snapshot = _sdn_status_snapshot()
    diagnosis_topology = (
        sdn_snapshot["topology"]
        if sdn_snapshot["status"] in {"CONNECTED", "SIMULATED"}
        else request.topology
    )
    diagnosis = diagnosis_engine.diagnose(
        live_metrics=metrics,
        ml_prediction=prediction,
        topology=diagnosis_topology,
        affected_node=request.affected_component,
    )
    alternate_path = request.network_state.get("alternate_path_available", False)
    risk = risk_engine.assess_risk(
        diagnosis=diagnosis,
        traffic_impact=_as_number(metrics, ("bandwidth_utilization_pct", "bandwidth_usage", "bandwidth_util")) / 100,
        recovery_action_risk="high",
        alternate_path_available=alternate_path,
        affected_component=request.affected_component,
    )
    decision = decision_engine.decide(diagnosis, risk, metrics, alternate_path_available=alternate_path)
    action = _action_for_decision(decision, request)
    safety = safety_checker.validate_action(
        action,
        request.network_state,
        {"incident_id": incident_id, "affected_nodes": [request.affected_component] if request.affected_component else []},
    )
    orchestrator = RecoveryOrchestrator(
        sdn_controller_url=config.SDN_CONTROLLER_URL,
        safety_checker=safety_checker,
        controller=sdn_controller,
    )
    sdn_available = _sdn_available(orchestrator.sdn_controller)

    execution: Dict[str, Any]
    verification: Dict[str, Any]
    fallback: Optional[Dict[str, Any]] = None
    if not safety["safe"]:
        execution = {"status": "blocked", "reason": "Safety check failed", "actions_executed": [], "errors": safety["administrator_alert"]}
        verification = {"result": "RECOVERY_FAILED", "verified": False, "reason": "Recovery action was blocked by safety validation"}
    elif not sdn_available:
        controller_reason = (
            "Controller monitoring is connected, but switch modifications are disabled in read-only mode."
            if sdn_snapshot["status"] == "CONNECTED"
            else f"SDN Controller {sdn_snapshot['status']}: {sdn_snapshot.get('error') or 'not available'}"
        )
        execution = {
            "status": "blocked",
            "reason": controller_reason,
            "actions_executed": [],
            "errors": [{"action": action["type"], "error": controller_reason}],
        }
        verification = {"result": "RECOVERY_FAILED", "verified": False, "reason": controller_reason}
        fallback = {"status": "blocked", "reason": controller_reason}
    else:
        strategy = {"name": decision["selected_action"], "actions": [action]}
        fallback_strategy = {"name": "alert_operations", "actions": [{"type": "alert_ops", "severity": "critical"}]}

        def verify_attempt(attempt: Dict[str, Any]) -> Dict[str, Any]:
            if not request.post_recovery_metrics:
                return {"success": False, "verified": False, "reason": "Post-recovery telemetry unavailable"}
            return verification_engine.verify_metrics(
                recovery_id=recovery_id,
                incident_id=incident_id,
                pre_recovery_metrics=metrics,
                post_recovery_metrics=request.post_recovery_metrics,
            )

        audit = orchestrator.execute_with_fallback(
            recovery_id=recovery_id,
            incident_id=incident_id,
            primary_strategy=strategy,
            fallback_strategy=fallback_strategy,
            verify_attempt=verify_attempt,
            network_state=request.network_state,
            incident_context={"incident_id": incident_id, "affected_nodes": [request.affected_component] if request.affected_component else []},
        )
        execution = audit
        verification = audit["attempts"][-1]["verification"] if audit["attempts"] else {"result": "RECOVERY_FAILED", "verified": False}
        fallback = audit["attempts"][1] if len(audit["attempts"]) > 1 else None

    final_status = "RESOLVED" if verification.get("verified") else "ESCALATED"
    logger = IncidentLogger(db_session=db)
    incident = logger.create_incident(
        incident_id=incident_id,
        detected_fault=diagnosis["fault_type"],
        affected_component=diagnosis["affected_component"],
        metrics=metrics,
        ml_prediction=prediction,
        confidence=diagnosis["confidence"],
        severity=risk["risk_level"],
        selected_action=decision["selected_action"],
        safety_result=safety,
        recovery_result=execution,
        verification_metrics=verification,
        fallback_action=fallback,
        final_status=final_status,
    )
    incident_row = db.query(NetworkIncident).filter(
        NetworkIncident.incident_id == incident_id
    ).one()
    for attempt in execution.get("attempts", []):
        attempt_execution = attempt.get("execution", {})
        attempt_verification = attempt.get("verification", {})
        attempt_number = attempt.get("attempt", 1)
        verified = bool(attempt_verification.get("verified", attempt_verification.get("success", False)))
        errors = attempt_execution.get("errors", [])
        db.add(RecoveryAttempt(
            recovery_id=f"{recovery_id}-{attempt_number}",
            incident_id=incident_row.id,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            status=attempt_execution.get("status", "unknown"),
            strategy_name=str(attempt.get("strategy", "unknown")),
            is_primary=attempt_number == 1,
            safety_check_passed=bool(safety["safe"]),
            safety_constraints=safety,
            recovery_actions=attempt_execution.get("actions_executed", []),
            verification_metrics=attempt_verification,
            verified=verified,
            success=attempt_execution.get("status") == "success",
            error_message=json.dumps(errors) if errors else None,
        ))
    if not execution.get("attempts"):
        db.add(RecoveryAttempt(
            recovery_id=f"{recovery_id}-1",
            incident_id=incident_row.id,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            status=execution.get("status", "unknown"),
            strategy_name=decision["selected_action"],
            strategy_description=execution.get("reason"),
            is_primary=True,
            safety_check_passed=bool(safety["safe"]),
            safety_constraints=safety,
            recovery_actions=execution.get("actions_executed", []),
            verification_metrics=verification,
            verified=bool(verification.get("verified", False)),
            success=execution.get("status") == "success",
            error_message=execution.get("reason"),
        ))
    db.add(RecoveryRecord(
        recovery_id=recovery_id,
        fault_id=incident_id,
        diagnosis=diagnosis["explanation"],
        recommended_action=decision["selected_action"],
        reason=decision["reason"],
        risk_level=risk["risk_level"].lower(),
        safety_check="passed" if safety["safe"] else "failed",
        recovery_action=action["type"],
        result=verification.get("result", "RECOVERY_FAILED"),
        verification=verification,
        fallback_action=json.dumps(fallback) if fallback is not None else None,
        status=final_status.lower(),
    ))
    alert_message = "Recovery completed and verified." if final_status == "RESOLVED" else (
        f"{execution['reason']} Recovery was not executed."
        if execution.get("status") == "blocked" and execution.get("reason")
        else "Recovery was not verified; administrator escalation required."
    )
    db.add(AlertRecord(
        alert_type="recovery",
        severity="low" if final_status == "RESOLVED" else "critical",
        message=alert_message,
        affected_node=diagnosis["affected_component"],
        status="closed" if final_status == "RESOLVED" else "open",
    ))
    db.add(NotificationRecord(
        user_id=current_user.id,
        type="recovery",
        severity="low" if final_status == "RESOLVED" else "critical",
        message=alert_message,
    ))
    db.commit()
    state.incidents.append(incident)
    state.recovery_status = _latest_persisted_recovery_status(db)
    return {
        "incident_id": incident_id,
        "recovery_id": recovery_id,
        "prediction": prediction,
        "diagnosis": diagnosis,
        "risk": risk,
        "decision": decision,
        "safety": safety,
        "recovery": execution,
        "verification": verification,
        "fallback": fallback,
        "final_status": final_status,
        "sdn_controller": {
            "status": sdn_snapshot["status"],
            "controller_url": sdn_snapshot.get("controller_url"),
            "error": sdn_snapshot.get("error"),
            "write_operations_enabled": sdn_snapshot.get("write_operations_enabled", False),
        },
    }


@router.get("/recovery/status")
def recovery_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _latest_persisted_recovery_status(db)


def _latest_persisted_recovery_status(db: Session) -> Dict[str, Any]:
    latest = db.query(RecoveryRecord).order_by(RecoveryRecord.created_at.desc()).first()
    if latest is None:
        return {"status": "idle", "active_recovery": None}

    incident = db.query(NetworkIncident).filter(
        NetworkIncident.incident_id == latest.fault_id
    ).first()
    attempts = []
    if incident is not None:
        attempts = [{
            "recovery_id": attempt.recovery_id,
            "timestamp": attempt.timestamp.isoformat() if attempt.timestamp else None,
            "status": attempt.status,
            "strategy_name": attempt.strategy_name,
            "is_primary": attempt.is_primary,
            "safety_check_passed": attempt.safety_check_passed,
            "recovery_actions": attempt.recovery_actions,
            "verification_metrics": attempt.verification_metrics,
            "verified": attempt.verified,
            "success": attempt.success,
            "error_message": attempt.error_message,
        } for attempt in db.query(RecoveryAttempt)
            .filter(RecoveryAttempt.incident_id == incident.id)
            .order_by(RecoveryAttempt.timestamp.asc())
            .all()]

    return {
        "status": latest.status,
        "active_recovery": {
            "recovery_id": latest.recovery_id,
            "incident_id": latest.fault_id,
            "status": latest.status,
            "recommended_action": latest.recommended_action,
            "reason": latest.reason,
            "recovery_action": latest.recovery_action,
            "safety_check": latest.safety_check,
            "result": latest.result,
            "verification": latest.verification,
            "fallback_action": latest.fallback_action,
            "attempts": attempts,
        },
    }


@router.get("/incidents")
def incidents(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    records = (
        db.query(NetworkIncident)
        .order_by(NetworkIncident.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {
        "incidents": [{
            "incident_id": item.incident_id,
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "detected_fault": item.incident_type,
            "affected_component": item.affected_component or item.affected_node,
            "selected_action": item.selected_action,
            "final_status": item.final_status,
            "confidence": item.confidence,
            "ml_prediction": item.ml_prediction,
            "safety_result": item.safety_result,
            "recovery_result": item.recovery_result,
            "verification_metrics": item.verification_metrics,
            "fallback_action": item.fallback_action,
        } for item in records],
        "count": len(records),
    }


@router.post("/incidents", status_code=201)
def record_incident(
    incident: IncidentPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    record = incident.model_dump() if hasattr(incident, "model_dump") else incident.dict()
    if db.query(NetworkIncident).filter(NetworkIncident.incident_id == record["incident_id"]).first():
        raise HTTPException(status_code=409, detail="incident_id already exists")
    timestamp = datetime.now(timezone.utc)
    db.add(NetworkIncident(
        incident_id=record["incident_id"],
        timestamp=timestamp.replace(tzinfo=None),
        incident_type=record["detected_fault"],
        affected_node=record["affected_component"],
        affected_component=record["affected_component"],
        metrics=record["metrics"],
        ml_prediction=record["ml_prediction"],
        confidence=record["confidence"],
        severity=record["severity"],
        final_status=record["final_status"],
    ))
    db.commit()
    record["timestamp"] = timestamp.isoformat()
    state.incidents.append(record)
    return record


@router.get("/metrics/history")
def historical_metrics(
    node_id: Optional[str] = None,
    metric_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    records = monitor.get_latest_metrics(node_id=node_id, metric_type=metric_type, limit=limit)
    return {"metrics": list(reversed(records)), "count": len(records)}


@router.get("/ml/model")
def model_information() -> Dict[str, Any]:
    inference_status = get_telemetry_inference_status()
    try:
        model = get_fault_prediction_model()
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return {
            "status": "not_loaded",
            "version": None,
            "prediction_threshold": config.PREDICTION_THRESHOLD,
            "telemetry_inference": inference_status,
        }
    if model.model is None:
        return {
            "status": "not_loaded",
            "version": None,
            "prediction_threshold": config.PREDICTION_THRESHOLD,
            "telemetry_inference": inference_status,
        }
    return {
        "status": "loaded",
        "version": model.model_version,
        "prediction_threshold": config.PREDICTION_THRESHOLD,
        "path": config.MODEL_PATH,
        "metrics": model.metrics,
        "telemetry_inference": inference_status,
    }


@router.websocket("/ws/dashboard")
async def dashboard_updates(
    websocket: WebSocket,
    db: Session = Depends(get_db),
) -> None:
    await websocket.accept()
    try:
        auth_message = await asyncio.wait_for(websocket.receive_text(), timeout=5)
        auth_payload = json.loads(auth_message)
        token = auth_payload.get("token") if isinstance(auth_payload, dict) else None
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        token = None

    if not isinstance(token, str) or not token:
        await websocket.close(code=4401, reason="Authentication required")
        return

    session = db.query(UserSession).filter(
        UserSession.token_hash == _hash_token(token)
    ).first()
    if not session or session.revoked or session.expires_at < datetime.utcnow():
        await websocket.close(code=4401, reason="Session expired or invalid")
        return
    user = db.query(User).filter(
        User.id == session.user_id,
        User.is_active.is_(True),
    ).first()
    if user is None:
        await websocket.close(code=4401, reason="User not found")
        return

    await websocket.send_json({"type": "authenticated"})
    snapshot = state.snapshot()
    snapshot["live_metrics"] = _live_metric_records(db)
    _apply_metric_freshness(snapshot["network_status"], snapshot["live_metrics"])
    snapshot["network_info"] = monitor.get_network_identity()
    snapshot["recovery_status"] = _latest_persisted_recovery_status(db)
    await websocket.send_json(snapshot)
    try:
        while True:
            message = await websocket.receive_text()
            if message.lower() in {"snapshot", "ping", "refresh"}:
                snapshot = state.snapshot()
                snapshot["live_metrics"] = _live_metric_records(db)
                _apply_metric_freshness(snapshot["network_status"], snapshot["live_metrics"])
                snapshot["network_info"] = monitor.get_network_identity()
                snapshot["recovery_status"] = _latest_persisted_recovery_status(db)
                await websocket.send_json(snapshot)
            else:
                await websocket.send_json({"error": "send snapshot, ping, or refresh"})
    except WebSocketDisconnect:
        return

# database/__init__.py - Database initialization and models

from datetime import datetime, timedelta
import enum

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, create_engine, inspect
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

try:
    from backend.config import config
except ImportError:  # pragma: no cover
    from config import config

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, echo=config.DEBUG, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class SeverityLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    DETECTED = "detected"
    DIAGNOSED = "diagnosed"
    ASSESSING = "assessing"
    RECOVERED = "recovered"
    FAILED = "failed"
    FALLBACK = "fallback"


class RecoveryStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    FALLBACK_TRIGGERED = "fallback_triggered"


class IncidentFinalStatus(str, enum.Enum):
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(200), nullable=False)
    username = Column(String(80), unique=True, index=True, nullable=False)
    email = Column(String(180), unique=True, index=True, nullable=False)
    mobile_number = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_login_at = Column(DateTime, nullable=True)
    account_status = Column(String(30), default="active")
    is_active = Column(Boolean, default=True)

    settings = relationship("UserSettings", back_populates="user", uselist=False)
    login_activity = relationship("UserLoginActivity", back_populates="user")
    password_resets = relationship("PasswordResetToken", back_populates="user")
    notifications = relationship("NotificationRecord", back_populates="user")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    refresh_interval = Column(Integer, default=30)
    notification_enabled = Column(Boolean, default=True)
    email_alerts = Column(Boolean, default=True)
    push_notifications = Column(Boolean, default=True)
    monitoring_settings = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="settings")


class UserLoginActivity(Base):
    __tablename__ = "user_login_activity"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    login_at = Column(DateTime, default=datetime.utcnow, index=True)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(255), nullable=True)
    success = Column(Boolean, default=True)

    user = relationship("User", back_populates="login_activity")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token_hash = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_used_at = Column(DateTime, default=datetime.utcnow, index=True)
    revoked = Column(Boolean, default=False)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(255), nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    otp_hash = Column(String(128), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    verified_at = Column(DateTime, nullable=True)
    reset_token_hash = Column(String(64), nullable=True)

    user = relationship("User", back_populates="password_resets")


class NetworkMetric(Base):
    __tablename__ = "network_metrics"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    node_id = Column(String(255), index=True)
    interface_id = Column(String(255), nullable=True)
    metric_type = Column(String(50), index=True)
    value = Column(Float)
    unit = Column(String(20))


class NetworkNode(Base):
    __tablename__ = "network_nodes"

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    node_type = Column(String(50), default="switch")
    status = Column(String(50), default="healthy")
    node_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class NetworkLink(Base):
    __tablename__ = "network_links"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(String(255), unique=True, index=True, nullable=False)
    source = Column(String(255), nullable=False)
    target = Column(String(255), nullable=False)
    status = Column(String(50), default="active")
    capacity = Column(String(50), nullable=True)
    link_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class NetworkHistoryEntry(Base):
    __tablename__ = "network_history"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    metric_type = Column(String(80), nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(50), default="")
    node_id = Column(String(255), nullable=True)
    source = Column(String(50), default="system")
    history_metadata = Column(JSON, default=dict)


class FaultRecord(Base):
    __tablename__ = "fault_records"

    id = Column(Integer, primary_key=True, index=True)
    fault_id = Column(String(255), unique=True, index=True, nullable=False)
    fault_type = Column(String(100), nullable=False)
    affected_node = Column(String(255), nullable=True)
    affected_component = Column(String(255), nullable=True)
    severity = Column(String(30), default="medium")
    status = Column(String(30), default="open")
    root_cause = Column(Text, nullable=True)
    detection_time = Column(DateTime, default=datetime.utcnow, index=True)
    summary = Column(Text, nullable=True)
    fault_metadata = Column(JSON, default=dict)


class PredictionRecord(Base):
    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True, index=True)
    prediction_id = Column(String(255), unique=True, index=True, nullable=False)
    model_name = Column(String(100), default="RandomForest")
    prediction_label = Column(String(100), nullable=False)
    probability = Column(Float, default=0.0)
    confidence = Column(Float, default=0.0)
    feature_snapshot = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RecoveryRecord(Base):
    __tablename__ = "recovery_records"

    id = Column(Integer, primary_key=True, index=True)
    recovery_id = Column(String(255), unique=True, index=True, nullable=False)
    fault_id = Column(String(255), nullable=True)
    diagnosis = Column(Text, nullable=True)
    recommended_action = Column(String(200), nullable=True)
    reason = Column(Text, nullable=True)
    risk_level = Column(String(30), default="medium")
    safety_check = Column(String(30), default="pending")
    recovery_action = Column(String(200), nullable=True)
    result = Column(String(50), default="pending")
    verification = Column(JSON, default=dict)
    fallback_action = Column(String(200), nullable=True)
    status = Column(String(30), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AlertRecord(Base):
    __tablename__ = "alert_records"

    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String(100), nullable=False)
    severity = Column(String(30), default="medium")
    message = Column(Text, nullable=False)
    affected_node = Column(String(255), nullable=True)
    status = Column(String(30), default="open")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_at = Column(DateTime, nullable=True)


class NotificationRecord(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    type = Column(String(80), default="info")
    severity = Column(String(30), default="medium")
    message = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="notifications")


class NetworkIncident(Base):
    __tablename__ = "network_incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(String(255), unique=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(30), default="detected")
    affected_node = Column(String(255), index=True)
    affected_component = Column(String(255), nullable=True, index=True)
    incident_type = Column(String(100), nullable=True)
    description = Column(Text)
    metrics = Column(JSON, nullable=True)
    prediction_confidence = Column(Float, nullable=True)
    predicted_fault = Column(String(255), nullable=True)
    ml_prediction = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    root_cause = Column(Text, nullable=True)
    affected_services = Column(JSON, nullable=True)
    topology_impact = Column(JSON, nullable=True)
    severity = Column(String(30), default="medium")
    risk_score = Column(Float, nullable=True)
    prediction_explanation = Column(JSON, nullable=True)
    diagnosis_reasoning = Column(JSON, nullable=True)
    selected_action = Column(String(255), nullable=True)
    safety_result = Column(JSON, nullable=True)
    recovery_result = Column(JSON, nullable=True)
    verification_metrics = Column(JSON, nullable=True)
    fallback_action = Column(JSON, nullable=True)
    final_status = Column(String(20), nullable=True, index=True)
    recovery_attempts = relationship("RecoveryAttempt", back_populates="incident")
    resolved_at = Column(DateTime, nullable=True)


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id = Column(Integer, primary_key=True, index=True)
    recovery_id = Column(String(255), unique=True, index=True)
    incident_id = Column(Integer, ForeignKey("network_incidents.id"), index=True)
    incident = relationship("NetworkIncident", back_populates="recovery_attempts")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    status = Column(String(30), default="pending")
    strategy_name = Column(String(255))
    strategy_description = Column(Text)
    is_primary = Column(Boolean, default=True)
    safety_check_passed = Column(Boolean, nullable=True)
    safety_constraints = Column(JSON, nullable=True)
    recovery_actions = Column(JSON)
    rollback_actions = Column(JSON, nullable=True)
    verification_metrics = Column(JSON, nullable=True)
    verified = Column(Boolean, default=False)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    success = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    event_type = Column(String(50), index=True)
    component = Column(String(100))
    action = Column(String(255))
    details = Column(JSON, nullable=True)
    incident_id = Column(String(255), nullable=True, index=True)


class MLModel(Base):
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, index=True)
    model_version = Column(String(50), unique=True)
    model_type = Column(String(50))
    training_date = Column(DateTime, default=datetime.utcnow)
    train_samples = Column(Integer)
    test_samples = Column(Integer)
    precision = Column(Float)
    recall = Column(Float)
    f1_score = Column(Float)
    roc_auc = Column(Float)
    model_path = Column(String(255))
    feature_list = Column(JSON)
    hyperparameters = Column(JSON)
    is_active = Column(Boolean, default=False)


def create_tables():
    Base.metadata.create_all(bind=engine)
    _ensure_password_reset_columns(engine)
    _seed_demo_data()


def _seed_demo_data():
    """Populate the local SQLite database with a minimal demo topology and telemetry.

    This makes the dashboard usable immediately in a fresh environment without any
    external monitoring or ML pipeline already running.
    """
    db = SessionLocal()
    try:
        has_nodes = db.query(NetworkNode).first() is not None
        has_faults = db.query(FaultRecord).first() is not None
        has_incidents = db.query(NetworkIncident).first() is not None
        if has_nodes and (has_faults or has_incidents):
            return

        now = datetime.utcnow()
        nodes = [
            ("web-01", "Web Frontend", "host", "healthy", {"role": "edge"}),
            ("edge-sw-01", "Edge Switch", "switch", "healthy", {"role": "access"}),
            ("core-rtr-01", "Core Router", "router", "degraded", {"role": "core"}),
            ("db-01", "Database", "host", "healthy", {"role": "database"}),
        ]
        for node_id, name, node_type, status, metadata in nodes:
            db.add(NetworkNode(
                node_id=node_id,
                name=name,
                node_type=node_type,
                status=status,
                node_metadata=metadata,
            ))

        links = [
            ("lnk-web-edge", "web-01", "edge-sw-01", "active", "1 Gbps", {"latency_ms": 4}),
            ("lnk-edge-core", "edge-sw-01", "core-rtr-01", "active", "1 Gbps", {"latency_ms": 8}),
            ("lnk-core-db", "core-rtr-01", "db-01", "active", "2 Gbps", {"latency_ms": 12}),
        ]
        for link_id, source, target, status, capacity, metadata in links:
            db.add(NetworkLink(
                link_id=link_id,
                source=source,
                target=target,
                status=status,
                capacity=capacity,
                link_metadata=metadata,
            ))

        base_metrics = [
            ("web-01", "latency_ms", 31.2, "ms", -1),
            ("edge-sw-01", "latency_ms", 36.8, "ms", -2),
            ("core-rtr-01", "latency_ms", 68.4, "ms", -3),
            ("core-rtr-01", "packet_loss_pct", 1.8, "%", -4),
            ("core-rtr-01", "bandwidth_utilization_pct", 81.2, "%", -5),
            ("db-01", "throughput_mbps", 420.5, "Mbps", -6),
            ("web-01", "cpu_utilization_pct", 52.1, "%", -7),
            ("db-01", "memory_utilization_pct", 61.8, "%", -8),
        ]
        for node_id, metric_type, value, unit, minutes_ago in base_metrics:
            db.add(NetworkMetric(
                node_id=node_id,
                metric_type=metric_type,
                value=float(value),
                unit=unit,
                timestamp=now + timedelta(minutes=minutes_ago),
            ))

        db.add(FaultRecord(
            fault_id="FLT-DEM-001",
            fault_type="link_congestion",
            affected_node="core-rtr-01",
            affected_component="core-rtr-01",
            severity="high",
            status="open",
            root_cause="Congested uplink causing elevated latency and packet loss.",
            summary="Core router uplink congestion detected.",
            detection_time=now,
            fault_metadata={"source": "demo_seed"},
        ))

        db.add(NetworkIncident(
            incident_id="INC-DEM-001",
            timestamp=now,
            status="diagnosed",
            affected_node="core-rtr-01",
            affected_component="core-rtr-01",
            incident_type="link_congestion",
            description="Link congestion on core router uplink causing elevated latency.",
            metrics={
                "latency_ms": 68.4,
                "packet_loss_pct": 1.8,
                "bandwidth_utilization_pct": 81.2,
                "source": "demo_seed",
            },
            ml_prediction={"label": "CONGESTION", "probability": 0.89},
            confidence=0.89,
            prediction_confidence=0.89,
            predicted_fault="CONGESTION",
            root_cause="Congested uplink",
            severity="high",
            final_status="ESCALATED",
        ))

        db.add(PredictionRecord(
            prediction_id="PRED-DEM-001",
            model_name="SelfHealNet RandomForest",
            prediction_label="CONGESTION",
            probability=0.89,
            confidence=0.89,
            feature_snapshot={
                "component": "core-rtr-01",
                "latency_ms": 68.4,
                "packet_loss_pct": 1.8,
                "bandwidth_utilization_pct": 81.2,
            },
            created_at=now,
        ))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_password_reset_columns(bind):
    columns = {
        column["name"]
        for column in inspect(bind).get_columns("password_reset_tokens")
    }
    additions = {
        "otp_hash": "VARCHAR(128)",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "verified_at": DateTime().compile(dialect=bind.dialect),
        "reset_token_hash": "VARCHAR(64)",
    }
    with bind.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE password_reset_tokens ADD COLUMN {name} {definition}"
                )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_database():
    Base.metadata.drop_all(bind=engine)
    create_tables()

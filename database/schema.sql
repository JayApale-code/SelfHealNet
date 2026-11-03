CREATE TABLE IF NOT EXISTS network_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_name TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL UNIQUE,
    detected_fault TEXT NOT NULL,
    affected_component TEXT NOT NULL,
    metrics JSON,
    ml_prediction JSON,
    confidence REAL NOT NULL,
    incident_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    selected_action TEXT,
    safety_result JSON,
    recovery_result JSON,
    verification_metrics JSON,
    fallback_action JSON,
    status TEXT NOT NULL,
    final_status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

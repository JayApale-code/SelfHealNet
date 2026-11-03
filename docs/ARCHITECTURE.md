# SelfHealNet Architecture & Design

## System Overview

SelfHealNet is a comprehensive autonomous network management system that implements a complete incident detection-to-recovery pipeline with transparency and safety as core design principles.

## Architecture Layers

### 1. Monitoring Layer
**Components**: `backend/monitoring/`

Continuously collects network metrics from multiple data sources:
- SNMP queries for device metrics
- NetFlow/sFlow for traffic analysis
- Custom probes for application-specific metrics
- Stores time-series data in PostgreSQL

**Key Classes**:
- `NetworkMonitor`: Central monitoring coordinator
- Metric types: latency, packet_loss, bandwidth_utilization, jitter, error_rate

### 2. Detection & Prediction Layer
**Components**: `backend/ml_engine/`

Real-time fault detection using trained ML models:
- **Dataset**: Synthetic network fault data (10,000 samples)
- **Features**: 13 network and topology features
- **Algorithm**: XGBoost gradient boosting classifier
- **Metrics**: Precision, Recall, F1-Score, ROC-AUC
- **Threshold**: 0.7 probability for fault classification

**Training Pipeline**:
1. Generate synthetic dataset with normal and fault scenarios
2. 80/20 train/test split with stratification
3. Feature scaling using StandardScaler
4. Train XGBoost with cross-validation
5. Evaluate on held-out test set
6. Persist model using joblib

### 3. Diagnosis Layer
**Components**: `backend/diagnosis/`

Analyzes incidents to determine root causes:
- Incident type classification
- Root cause hypothesis generation
- Affected service impact assessment
- Service dependency analysis
- Temporal/spatial incident correlation

**Supported Incident Types**:
- Link failure
- Node failure
- Network congestion
- High latency
- Packet loss
- Anomalous behavior

### 4. Risk Assessment Layer
**Components**: `backend/risk_assessment/`

Quantifies incident severity and risk:
- **Risk Score Formula**: Impact × Probability × Criticality
- **Severity Levels**: Low, Medium, High, Critical
- **SLA Impact Analysis**: Estimated MTTR and downtime
- **Recovery Priority**: Immediate, Urgent, High, Normal

**Scoring Matrices**:
- Impact: 1-10 scale
- Probability: 0.1-1.0 scale
- Criticality: 0.5-2.0 scale

### 5. Explainability Layer
**Components**: `backend/explainability/`

Provides transparency into AI/ML decisions:
- **SHAP Integration**: SHapley Additive exPlanations for model predictions
- **Feature Importance**: Ranking of contributing factors
- **Reasoning Chains**: Step-by-step decision justification
- **Alternative Causes**: Secondary hypotheses with confidence levels

**Explanation Types**:
- Prediction explanation: Why was a fault predicted?
- Diagnosis explanation: Why is X the root cause?
- Recovery explanation: Why this specific recovery action?

### 6. Safety & Validation Layer
**Components**: `backend/safety/`

Pre-flight validation before recovery execution:

**Safety Constraints** (7 critical constraints):
1. No single point of failure creation
2. Network connectivity preservation
3. Link capacity headroom (max 85% utilization)
4. BGP stability (prevent flapping)
5. SLA requirement maintenance
6. Routing loop prevention
7. Recovery rate limiting (prevent oscillation)

**Safety Check Process**:
- Validate against all constraints
- Critical violations: block recovery
- Non-critical violations: generate warnings
- Provide remediation recommendations

### 7. Recovery & Orchestration Layer
**Components**: `backend/recovery/`

Executes recovery actions safely and verifiably:
- Recovery strategy planning
- SDN controller integration (OpenFlow)
- Action orchestration
- Rollback capability
- Fallback strategy management

**Recovery Action Types**:
- Route changes/rerouting
- Link up/down
- Traffic engineering
- BGP updates
- Interface reconfiguration
- Service restart

### 8. Verification Layer
**Components**: `backend/verification/`

Validates recovery success:
- Post-recovery metric collection
- Success criteria evaluation
- Automatic fallback triggering if needed
- Recovery time measurement
- Incident resolution confirmation

### 9. Logging & Audit Layer
**Components**: `backend/database/`

Complete audit trail:
- `SystemLog`: All events, decisions, actions
- `NetworkIncident`: Incident lifecycle tracking
- `RecoveryAttempt`: Recovery action history
- `MLModel`: Model training and versioning

### 10. Dashboard & Visualization Layer
**Components**: `frontend/`

Professional web interface:
- Real-time network visualization
- Active incident display
- Recovery history and analytics
- System health metrics
- Alert management

---

## Data Models

### Core Tables

#### NetworkMetric
```
- timestamp: DateTime (indexed)
- node_id: String (indexed)
- interface_id: Optional String
- metric_type: String (latency, packet_loss, bandwidth, jitter, error_rate)
- value: Float
- unit: String (ms, %, Mbps, etc.)
```

#### NetworkIncident
```
- incident_id: Unique String
- timestamp: DateTime
- status: Enum (detected, diagnosed, assessing, recovered, failed, fallback)
- affected_node: String
- incident_type: String
- prediction_confidence: Float (0-1)
- root_cause: Text (diagnosis result)
- severity: Enum (low, medium, high, critical)
- risk_score: Float
- affected_services: JSON array
```

#### RecoveryAttempt
```
- recovery_id: Unique String
- incident_id: Foreign Key (NetworkIncident)
- status: Enum (pending, in_progress, verified, failed, fallback_triggered)
- strategy_name: String
- safety_check_passed: Boolean
- recovery_actions: JSON (list of executed actions)
- verified: Boolean
- success: Boolean
- start_time: DateTime
- end_time: DateTime
```

#### SystemLog
```
- timestamp: DateTime (indexed)
- event_type: String (monitoring, prediction, diagnosis, recovery, verification)
- component: String (which module)
- action: String (what happened)
- details: JSON (additional context)
- incident_id: Optional String (indexed)
```

#### MLModel
```
- model_version: String (unique)
- model_type: String (xgboost, random_forest, etc.)
- training_date: DateTime
- precision, recall, f1_score, roc_auc: Float
- feature_list: JSON array
- hyperparameters: JSON
- is_active: Boolean
```

---

## API Endpoints (v1)

### Health & Status
- `GET /health` - Health check
- `GET /api/v1/status` - API status and modules

### Monitoring
- `POST /api/v1/monitoring/metrics` - Submit metric
- `GET /api/v1/monitoring/metrics` - Retrieve metrics (filtered)
- `GET /api/v1/monitoring/baseline` - Get node baseline

### ML Engine
- `POST /api/v1/ml/train` - Train fault prediction model
- `POST /api/v1/ml/predict` - Predict fault probability
- `GET /api/v1/ml/model` - Get active model info
- `GET /api/v1/ml/models` - List all models

### Incidents
- `POST /api/v1/incidents` - Create incident
- `GET /api/v1/incidents` - List incidents (with filters)
- `GET /api/v1/incidents/{id}` - Get incident details
- `GET /api/v1/incidents/{id}/timeline` - Get incident timeline

### Diagnosis
- `POST /api/v1/diagnosis/diagnose` - Run diagnosis
- `POST /api/v1/diagnosis/correlate` - Correlate incidents
- `GET /api/v1/diagnosis/patterns` - Get incident patterns

### Risk Assessment
- `POST /api/v1/risk/assess` - Assess incident risk
- `GET /api/v1/risk/dashboard` - Risk dashboard data
- `GET /api/v1/risk/sla-impact` - SLA impact analysis

### Explainability
- `GET /api/v1/explain/prediction/{id}` - Explain prediction
- `GET /api/v1/explain/diagnosis/{id}` - Explain diagnosis
- `GET /api/v1/explain/recovery/{id}` - Explain recovery

### Safety
- `POST /api/v1/safety/check` - Run pre-flight safety check
- `GET /api/v1/safety/constraints` - List constraints

### Recovery
- `POST /api/v1/recovery/plan` - Plan recovery strategy
- `POST /api/v1/recovery/execute` - Execute recovery
- `GET /api/v1/recovery/attempts` - List recovery attempts
- `GET /api/v1/recovery/fallback` - Trigger fallback

### Verification
- `POST /api/v1/verification/verify` - Verify recovery
- `GET /api/v1/verification/results` - Get verification results

### Audit & History
- `GET /api/v1/audit/logs` - Audit logs
- `GET /api/v1/audit/incidents` - Incident history
- `GET /api/v1/audit/recoveries` - Recovery history

---

## ML Model Implementation

### Dataset Generation
- **Synthetic data**: 10,000 samples
- **Fault scenarios**: 70% normal, 30% faulty
- **Fault types**: Link failure, congestion, high jitter, high error rate, anomaly

### Features (13 total)
1. latency_mean - Average latency (ms)
2. latency_std - Latency standard deviation
3. latency_p95 - 95th percentile latency
4. packet_loss_mean - Average packet loss rate (%)
5. packet_loss_std - Packet loss std deviation
6. bandwidth_util - Link utilization (%)
7. bandwidth_trend - Utilization trend
8. jitter_mean - Average jitter (ms)
9. jitter_spike_rate - Jitter spike frequency
10. error_rate_trend - Error rate trend
11. node_degree - Network topology degree
12. time_of_day - Hour of day (cyclic)
13. recent_anomalies - Count of recent anomalies

### Model Details
- **Algorithm**: XGBoost (gradient boosting)
- **Parameters**: 100 estimators, max_depth=7, learning_rate=0.1
- **Evaluation**: Test set (20% of data)
- **Metrics Tracked**: Precision, Recall, F1, ROC-AUC, Accuracy
- **Serialization**: joblib for model persistence

### Prediction Pipeline
1. Feature scaling (StandardScaler)
2. XGBoost prediction with probability
3. SHAP value calculation for explainability
4. Confidence thresholding (default: 0.7)
5. Output: {prediction, probability, confidence, shap_values}

---

## Deployment Architecture

### Components
- **Backend**: Python/FastAPI service (REST API)
- **Database**: PostgreSQL (metrics, incidents, logs)
- **Cache**: Redis (session, caching)
- **Monitoring**: Prometheus metrics
- **Frontend**: React.js web dashboard
- **SDN Controller**: OpenFlow compatible (Floodlight, ONOS, etc.)
- **Network Simulator**: Mininet for testing

### Communication Flow
1. Network Monitor → Database (metrics)
2. ML Engine → Monitor (feature extraction)
3. Detection → Diagnosis → Risk Assessment (pipeline)
4. Explainability ← All stages (reasoning)
5. Safety Check → Recovery (validation before execution)
6. Recovery → Verification (post-action validation)
7. All stages → SystemLog (audit trail)
8. Dashboard ← Database/API (visualization)

---

## Security Considerations

1. **Authentication**: JWT tokens for API
2. **Authorization**: Role-based access control (RBAC)
3. **Data Protection**: Encryption in transit (HTTPS)
4. **Audit Trail**: All actions logged with timestamps
5. **Safe Recovery**: Pre-flight checks prevent dangerous actions
6. **Rollback Capability**: Every recovery has rollback plan

---

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Individual module tests
- Mock external dependencies
- Test coverage: >80%

### Integration Tests (`tests/integration/`)
- End-to-end pipeline testing
- Database integration
- API endpoint testing

### Network Simulation (`network_sim/`)
- Mininet-based network simulation
- Fault injection
- Recovery verification in virtual environment

---

## Monitoring & Observability

### Metrics Collected
- Network: latency, packet loss, bandwidth, jitter, errors
- System: CPU, memory, disk usage
- Application: API response time, error rates
- ML: Model accuracy, prediction confidence
- Recovery: Success rate, MTTR (Mean Time To Recovery)

### Alerting
- Threshold-based: Metric thresholds
- Anomaly-based: Deviation from baseline
- Pattern-based: Known bad patterns
- Manual: User-defined alerts

### Dashboards
- Overview: System health, active incidents
- Network: Topology, real-time metrics
- ML: Model performance, predictions
- Incidents: Timeline, root causes, resolutions
- Recovery: Actions, success rates, MTTR

---

## Development Roadmap

### Phase 1: Foundation ✓
- Project structure
- Database schemas
- Monitoring collector
- API skeleton

### Phase 2: ML Implementation (Current)
- Dataset generation
- Feature engineering
- Model training
- Model evaluation & persistence

### Phase 3: Core Analysis
- Diagnosis engine
- Risk assessment
- Explainability integration
- Safety validation

### Phase 4: Recovery System
- SDN integration
- Recovery orchestration
- Verification engine
- Fallback logic

### Phase 5: Dashboard
- Frontend setup
- Real-time visualization
- Analytics
- Incident management UI

### Phase 6: Integration & Testing
- End-to-end tests
- Mininet simulation
- Performance testing
- Documentation

---

## References

- SHAP: https://github.com/slundberg/shap
- XGBoost: https://xgboost.readthedocs.io/
- FastAPI: https://fastapi.tiangolo.com/
- Mininet: http://mininet.org/
- OpenFlow: https://www.opennetworking.org/

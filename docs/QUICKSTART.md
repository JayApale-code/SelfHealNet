# QUICK START GUIDE - SelfHealNet Setup

## Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher  
- Redis 6.0 or higher
- Node.js 14+ (for frontend)
- pip and npm package managers

## Installation & Setup

### 1. Clone and Navigate to Project

```bash
cd "c:\Users\HP\OneDrive\Documents\Desktop\SELF-HEALING"
```

### 2. Set Up Python Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings (database URL, API port, etc.)
# Windows: notepad .env
# macOS/Linux: nano .env
```

### 5. Initialize Database

```bash
# From project root
python -c "from backend.database import create_tables; create_tables()"
```

### 6. Train ML Model

```bash
# From project root
python -c "from backend.ml_engine import train_fault_prediction_model; result = train_fault_prediction_model(); print(result)"
```

This will:
- Generate 10,000 synthetic network fault samples
- Split into 80% training, 20% testing
- Train XGBoost model
- Evaluate metrics (Precision, Recall, F1, ROC-AUC)
- Save model to `data/models/fault_prediction_model.joblib`

### 7. Start Backend API

```bash
# From project root
python -m backend.main
```

API will be available at: `http://localhost:8000`
- Health check: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 8. Set Up Frontend (Optional - Phase 5)

```bash
cd frontend
npm install
npm run dev
```

Frontend will run at: `http://localhost:5173`

### Optional: read-only Ryu SDN monitoring

SelfHealNet reads controller data from the Ryu REST API; it does not send HTTP
requests to the OpenFlow listener. Configure the REST base URL and optional
Basic Auth credentials in the backend environment before starting it:

```powershell
$env:SDN_CONTROLLER_URL = "http://127.0.0.1:8080"
$env:SDN_CONTROLLER_API_TIMEOUT_SECONDS = "2"
# Set these only when the REST API requires Basic Auth:
$env:SDN_CONTROLLER_USERNAME = "your-username"
$env:SDN_CONTROLLER_PASSWORD = "your-password"
```

The backend verifies `/stats/switches`, then reads switch port and flow stats.
Topology links additionally require Ryu's `rest_topology` app. In the Ryu
environment, start the controller with:

```bash
ryu-manager ryu.app.simple_switch_13 ryu.app.ofctl_rest ryu.app.rest_topology
```

The OpenFlow listener (typically TCP 6633) is for switches, not this HTTP API.
The SelfHealNet adapter is read-only: flow modifications remain disabled.
With no `SDN_CONTROLLER_URL`, status is `NOT CONFIGURED`; an unreachable
configured REST endpoint reports `DISCONNECTED`. `SDN_SIMULATION_ENABLED=true`
labels in-process topology as `SIMULATION`, never as a real connection.

## Quick Test

### Test Monitoring Collector

```bash
python -c "
from backend.monitoring import get_monitor
from backend.database import SessionLocal

monitor = get_monitor()

# Collect sample metrics
monitor.collect_metric('router-1', 'latency', 35.5, 'ms')
monitor.collect_metric('router-1', 'packet_loss', 0.05, '%')
monitor.collect_metric('switch-1', 'bandwidth_util', 65.0, '%')

monitor.flush_metrics()

# Retrieve metrics
metrics = monitor.get_latest_metrics('router-1', limit=5)
print('Recent metrics:', metrics)
"
```

### Test ML Model

```bash
python -c "
import pandas as pd
from backend.ml_engine import get_fault_prediction_model

# Load trained model
model = get_fault_prediction_model()

# Create sample feature data
X = pd.DataFrame({
    'latency_mean': [45.0],
    'latency_std': [3.5],
    'latency_p95': [52.0],
    'packet_loss_mean': [0.1],
    'packet_loss_std': [0.02],
    'bandwidth_util': [65.0],
    'bandwidth_trend': [1.0],
    'jitter_mean': [3.0],
    'jitter_spike_rate': [0.02],
    'error_rate_trend': [0.5],
    'node_degree': [8],
    'time_of_day': [14.0],
    'recent_anomalies': [0]
})

# Make prediction
result = model.predict(X)
print('Prediction result:')
print(f\"  Fault probability: {result['fault_probability'][0]:.3f}\")
print(f\"  Confidence: {result['confidence'][0]:.3f}\")
print(f\"  Predicted fault: {result['predictions'][0]}\")
"
```

### Test Full Pipeline (Monitor → Predict → Diagnose)

```bash
python -c "
from backend.monitoring import get_monitor
from backend.diagnosis import get_diagnosis_engine
from backend.risk_assessment import get_risk_assessment_engine

# Simulate incident detection
metrics = {
    'latency_mean': 150.0,
    'packet_loss_mean': 2.5,
    'bandwidth_util': 85.0
}

# Diagnose
diagnosis_engine = get_diagnosis_engine()
diagnosis = diagnosis_engine.diagnose_incident(
    'INC-001',
    'router-1',
    'high_latency',
    metrics
)

print('Diagnosis:', diagnosis)

# Assess risk
risk_engine = get_risk_assessment_engine()
risk = risk_engine.assess_incident(
    'INC-001',
    'high_latency',
    diagnosis,
    metrics
)

print('Risk assessment:', risk)
"
```

## API Examples

### Health Check

```bash
curl http://localhost:8000/health
```

### API Status

```bash
curl http://localhost:8000/api/v1/status
```

### Interactive API Documentation

Open in browser: `http://localhost:8000/docs` (Swagger UI)

## Project Structure

```
selfhealnet/
├── backend/
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Configuration management
│   ├── requirements.txt           # Python dependencies
│   ├── monitoring/               # Network data collection
│   ├── ml_engine/                # Fault prediction model
│   ├── diagnosis/                # Diagnosis engine
│   ├── risk_assessment/          # Risk scoring
│   ├── explainability/           # SHAP explanations
│   ├── safety/                   # Safety validation
│   ├── recovery/                 # Recovery orchestration
│   ├── verification/             # Post-recovery validation
│   ├── database/                 # Database models
│   └── api/                      # API routes (Phase 5)
├── frontend/                     # React dashboard (Phase 5)
├── data/
│   ├── datasets/                # Training datasets
│   ├── models/                  # Saved ML models
│   └── synthetic/               # Synthetic network data
├── network_sim/                 # Mininet simulation
├── tests/
│   ├── unit/                    # Unit tests
│   └── integration/             # Integration tests
├── docs/
│   ├── ARCHITECTURE.md          # Detailed architecture
│   ├── API.md                   # API documentation
│   └── DEPLOYMENT.md            # Deployment guide
└── config/
    ├── logging.yml              # Logging config
    └── network.yml              # Network topology
```

## Troubleshooting

### Database Connection Error

```
Error: psycopg2.OperationalError
Solution: Verify PostgreSQL is running and DATABASE_URL in .env is correct
```

### Model Not Found

```
Error: ML model not found at data/models/...
Solution: Run the ML model training step: python -c "from backend.ml_engine import train_fault_prediction_model; train_fault_prediction_model()"
```

### Port Already in Use

```
Error: Address already in use
Solution: Change API_PORT in .env or kill process using port 8000
```

### Redis Connection Error

```
Error: redis.exceptions.ConnectionError
Solution: Verify Redis is running (redis-server) or disable caching in config
```

## Development Workflow

1. **Make changes** to backend code
2. **Test changes** with provided test scripts
3. **Run API** to verify endpoints
4. **Check logs** in logs/selfhealnet.log
5. **Commit** changes with descriptive messages

## Next Steps

1. ✅ Phase 1: Foundation (Current)
2. **Phase 2**: ML Model Training & Evaluation
3. **Phase 3**: Diagnosis & Analysis Engines
4. **Phase 4**: Recovery & Verification Systems
5. **Phase 5**: Web Dashboard & Visualization
6. **Phase 6**: Integration Testing & Documentation

## Support & Documentation

- Full architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- API reference: [API.md](API.md)
- Deployment guide: [DEPLOYMENT.md](DEPLOYMENT.md)
- Testing guide: [TESTING.md](TESTING.md)

## License

Academic Project - 2024/2025

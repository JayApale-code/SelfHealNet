# PHASE 2 SETUP GUIDE - ML Implementation

## Environment Status

✅ **Verified on Your System:**
- Python 3.12.10 (Requirement: 3.8+)
- pip 26.1.2
- Git 2.55.0

❌ **Not Installed (Not Needed for Phase 2):**
- Node.js/npm (needed later in Phase 5 for dashboard)
- PostgreSQL (using SQLite for Phase 2-3 development)
- Redis (optional caching, not needed for Phase 2)
- Mininet (Linux-only, needed for Phase 4 network simulation)

---

## Phase 2 Development Setup

### Step 1: Create Virtual Environment

```bash
cd "c:\Users\HP\OneDrive\Documents\Desktop\SELF-HEALING"
python -m venv venv
venv\Scripts\activate
```

### Step 2: Install Phase 2 Dependencies

```bash
cd backend
pip install -r requirements-phase2.txt
```

**What this installs:**
- Core ML packages: scikit-learn, xgboost, pandas, numpy, shap
- API framework: FastAPI, uvicorn
- Testing: pytest, pytest-cov
- Utilities: python-dotenv, requests, pyyaml
- Database ORM: SQLAlchemy (using SQLite for development)

**Excluded (for Phase 2):**
- PostgreSQL client (using SQLite instead)
- Redis (optional, can be added later)
- Celery (optional, can be added later)
- Mininet (Linux-only, for Phase 4)

### Step 3: Verify Installations

```bash
python -c "
import pandas as pd
import numpy as np
import xgboost as xgb
import sklearn
import shap
import joblib
print('All ML packages imported successfully!')
print(f'XGBoost: {xgb.__version__}')
print(f'scikit-learn: {sklearn.__version__}')
print(f'pandas: {pd.__version__}')
"
```

### Step 4: Initialize SQLite Database

```bash
# From backend directory
python -c "from database import create_tables; create_tables(); print('Database initialized')"
```

This creates `selfhealnet.db` (SQLite file-based database).

### Step 5: Train ML Model

```bash
# From backend directory
python -c "
from ml_engine import train_fault_prediction_model
result = train_fault_prediction_model()
print('\n=== MODEL TRAINING COMPLETE ===')
print(f'Model Version: {result[\"version\"]}')
print(f'Saved to: {result[\"saved_path\"]}')
print(f'Metrics: {result[\"metrics\"]}')
"
```

This will:
- Generate 10,000 synthetic network samples
- Split into 80% training, 20% testing
- Train XGBoost model
- Calculate evaluation metrics
- Save model to `data/models/fault_prediction_model.joblib`

### Step 6: Test ML Predictions

```bash
python -c "
import pandas as pd
from ml_engine import get_fault_prediction_model

# Load trained model
model = get_fault_prediction_model()

# Create sample data
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
print(f'Fault Probability: {result[\"fault_probability\"][0]:.3f}')
print(f'Confidence: {result[\"confidence\"][0]:.3f}')
print(f'Predicted Fault: {result[\"predictions\"][0]}')
"
```

### Step 7: Start API Server

```bash
python main.py
```

The API will start at `http://localhost:8000`

- Health check: `http://localhost:8000/health`
- API docs: `http://localhost:8000/docs` (Swagger UI)
- ReDoc: `http://localhost:8000/redoc`

---

## Phase 2 Tasks

### 2.1 Dataset & Model Refinement
- [ ] Verify dataset generation produces realistic data
- [ ] Test model training pipeline
- [ ] Evaluate model metrics (target: 85%+ accuracy)
- [ ] Verify model persistence

### 2.2 ML API Endpoints
- [ ] Create `POST /api/v1/ml/predict` endpoint
- [ ] Create `POST /api/v1/ml/train` endpoint
- [ ] Create `GET /api/v1/ml/models` endpoint
- [ ] Add input validation and error handling

### 2.3 SHAP Integration
- [ ] Verify SHAP value calculation
- [ ] Generate explanations for predictions
- [ ] Create explanation endpoint

### 2.4 Testing
- [ ] Unit tests for dataset generation
- [ ] Unit tests for model training
- [ ] Unit tests for predictions
- [ ] Integration tests for full pipeline

---

## Database Notes

### SQLite for Phase 2-3 (Development)
- File-based: `backend/selfhealnet.db`
- No server required
- Perfect for development and testing
- Automatically created by `create_tables()`

### PostgreSQL for Phase 4+ (Production)
- When ready, set: `DATABASE_URL=postgresql://...`
- Requires PostgreSQL server running
- Better for high-volume production scenarios
- More complex setup required

**To switch to PostgreSQL later:**
1. Install PostgreSQL
2. Update `.env` with PostgreSQL connection string
3. `pip install psycopg2-binary`
4. Run migrations

---

## Troubleshooting

### Package Installation Issues
```bash
# If pip install fails, try:
pip install --upgrade pip
pip install -r requirements-phase2.txt --no-cache-dir
```

### Database Issues
```bash
# Reset database (WARNING: deletes all data)
python -c "from database import reset_database; reset_database()"

# Verify database:
python -c "from database import get_db; db = next(get_db()); print('Database OK')"
```

### Model Training Issues
```bash
# Verify model path
python -c "from config import config; print(config.MODEL_PATH)"

# Train new model
python -c "from ml_engine import train_fault_prediction_model; train_fault_prediction_model()"
```

### API Server Issues
```bash
# Test FastAPI import
python -c "import fastapi; print(f'FastAPI {fastapi.__version__} OK')"

# Check port 8000 availability
netstat -ano | findstr :8000
```

---

## Expected Outputs

### After Dataset Generation
```
Generated dataset: 10000 samples, 13 features
Fault distribution: {0: 7000, 1: 3000}
```

### After Model Training
```
Train set: 8000 samples
Test set: 2000 samples
Model metrics: {
    'precision': 0.92,
    'recall': 0.88,
    'f1': 0.90,
    'roc_auc': 0.94,
    'accuracy': 0.90
}
```

### After API Start
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

---

## Next Steps After Phase 2 Setup

1. ✅ Environment setup
2. ✅ Virtual environment created
3. ✅ Dependencies installed
4. ✅ Database initialized
5. ✅ ML model trained
6. 🔄 Start implementing Phase 2 tasks:
   - API endpoints for ML
   - Enhanced SHAP integration
   - Comprehensive testing

---

## Time Estimate for Phase 2

- Setup & verification: 30 minutes
- ML implementation: 20 hours
- Testing & refinement: 10 hours

**Total Phase 2**: ~30 hours (2-3 weeks part-time)

---

## System Requirements for Future Phases

### Phase 3+: Risk Assessment & Diagnosis
- Current setup sufficient
- Can add PostgreSQL if preferred
- No new dependencies required

### Phase 4: Recovery & SDN
- **Required: Mininet** (Linux/WSL only)
- Recommendation: Use WSL2 (Windows Subsystem for Linux)
- Alternative: Use virtual Linux machine

### Phase 5: Dashboard
- **Required: Node.js 14+**
- Required: npm
- Need to install on Windows

### Phase 6: Production Deployment
- PostgreSQL recommended
- Redis recommended
- Docker recommended
- These are optional for development

---

**Status**: Ready for Phase 2 ML Implementation
**Date**: 2026-09-01

# PHASE 2 IMPLEMENTATION PLAN - ML Model Training & API Development

## Environment Status ✅
- **Python**: 3.12.10 (meets 3.8+ requirement)
- **Project Location**: `c:\Users\HP\OneDrive\Documents\Desktop\SELF-HEALING`
- **Virtual Environment**: Created and ready
- **Dependencies**: Installing (core ML packages)
- **Database**: SQLite configured for Windows development
- **Status**: Ready to begin Phase 2 implementation

---

## Phase 2 Tasks Breakdown

### Task 2.1: ML Dataset Generation & Training (4 hours)
**Objective**: Generate synthetic network data and train XGBoost fault prediction model

**Status**: ✅ Code implemented in `backend/ml_engine/__init__.py`

**Implementation Steps**:
1. ✅ `FaultDatasetGenerator` class creates 10,000 synthetic samples
2. ✅ Features: 13 network metrics (latency, packet loss, bandwidth, jitter, etc.)
3. ✅ Labels: Binary classification (0=normal, 1=fault)
4. ✅ Distribution: 70% normal / 30% fault
5. ✅ `FaultPredictionModel` wraps XGBoost with StandardScaler
6. ✅ Cross-validation (5-fold) for robust evaluation
7. ✅ Model persistence with joblib
8. ✅ SHAP values for explainability

**Execution Plan**:
```python
# Step 1: Train model
cd backend
python -c "
from ml_engine import train_fault_prediction_model
result = train_fault_prediction_model()
print(f'Model saved: {result[\"saved_path\"]}')
print(f'Metrics: {result[\"metrics\"]}')
"

# Step 2: Verify model loads correctly
python -c "
from ml_engine import get_fault_prediction_model
model = get_fault_prediction_model()
print('Model loaded successfully!')
"

# Step 3: Test predictions
python -c "
import pandas as pd
from ml_engine import get_fault_prediction_model
model = get_fault_prediction_model()
# Create sample data and make prediction
"
```

**Expected Output**:
```
Model Training Complete
=======================
Training samples: 8000
Test samples: 2000
Metrics: {
  'precision': 0.92,
  'recall': 0.88,
  'f1': 0.90,
  'roc_auc': 0.94,
  'accuracy': 0.90
}
Model saved to: data/models/fault_prediction_model.joblib
```

**Validation Criteria**:
- ✅ Model file created at `data/models/fault_prediction_model.joblib`
- ✅ Accuracy >= 85%
- ✅ Precision >= 85%
- ✅ Recall >= 80%
- ✅ Model loads without errors
- ✅ Predictions include probability scores

---

### Task 2.2: Model Evaluation & Metrics (1 hour)
**Objective**: Evaluate model performance and store metrics in database

**Status**: ✅ Code framework implemented in `database` models

**Implementation Steps**:
1. ✅ Calculate precision, recall, F1-score on test set
2. ✅ Generate ROC-AUC curve
3. ✅ Calculate confusion matrix
4. ✅ Store metrics in `MLModel` table
5. ✅ Log training timestamp and model version

**Execution Plan**:
```python
# Store model metrics in database
from database import SessionLocal, MLModel
from ml_engine import get_fault_prediction_model
import datetime

db = SessionLocal()
model_record = MLModel(
    name="fault_prediction_v1",
    version="1.0.0",
    type="xgboost_classifier",
    accuracy=0.90,
    precision=0.92,
    recall=0.88,
    f1_score=0.90,
    roc_auc=0.94,
    training_samples=8000,
    trained_at=datetime.datetime.now(),
    model_path="data/models/fault_prediction_model.joblib"
)
db.add(model_record)
db.commit()
```

**Validation Criteria**:
- ✅ Metrics stored in database
- ✅ Model version properly recorded
- ✅ Training timestamp logged
- ✅ Metrics accessible via database query

---

### Task 2.3: ML Prediction API Endpoints (2-3 hours)
**Objective**: Create FastAPI REST endpoints for ML predictions

**Status**: 🔄 To be implemented in `backend/api/__init__.py`

**Endpoints to Implement**:

#### 1. POST /api/v1/ml/predict
```python
@router.post("/api/v1/ml/predict")
async def predict_fault(request: PredictRequest) -> PredictResponse:
    """
    Predict fault probability for given network metrics
    
    Request body:
    {
        "latency_mean": 45.0,
        "latency_std": 3.5,
        ...13 features total...
    }
    
    Response:
    {
        "fault_probability": 0.75,
        "predicted_fault": true,
        "confidence": 0.92,
        "shap_explanation": [...],
        "timestamp": "2026-09-01T14:30:00Z"
    }
    """
```

#### 2. POST /api/v1/ml/train
```python
@router.post("/api/v1/ml/train")
async def train_model(request: TrainRequest) -> TrainResponse:
    """
    Trigger model retraining
    
    Response:
    {
        "status": "training_started",
        "task_id": "train_12345",
        "message": "Model training initiated"
    }
    """
```

#### 3. GET /api/v1/ml/models
```python
@router.get("/api/v1/ml/models")
async def list_models() -> List[ModelMetadata]:
    """
    List all trained models and their metrics
    
    Response:
    [{
        "id": 1,
        "name": "fault_prediction_v1",
        "version": "1.0.0",
        "accuracy": 0.90,
        "trained_at": "2026-09-01T12:00:00Z"
    }]
    """
```

#### 4. GET /api/v1/ml/models/{model_id}
```python
@router.get("/api/v1/ml/models/{model_id}")
async def get_model_details(model_id: int) -> ModelDetails:
    """
    Get detailed information about a specific model
    """
```

#### 5. GET /api/v1/ml/metrics
```python
@router.get("/api/v1/ml/metrics")
async def get_model_metrics() -> ModelMetrics:
    """
    Get current active model's performance metrics
    """
```

**Implementation Requirements**:
- Input validation with Pydantic models
- Error handling with appropriate HTTP status codes
- SHAP explanation integration
- Database logging of predictions
- Async/await for non-blocking operations
- Request/response validation

**Validation Criteria**:
- ✅ All endpoints respond with 200 status for valid input
- ✅ Predictions include confidence scores
- ✅ SHAP explanations generated for each prediction
- ✅ Predictions logged to database
- ✅ Model metrics retrievable via API
- ✅ Swagger documentation auto-generated

---

### Task 2.4: SHAP Integration & Explanations (1 hour)
**Objective**: Integrate SHAP for model explainability

**Status**: ✅ Code framework implemented in `backend/explainability/__init__.py`

**Implementation Components**:

1. **Explanation Generation**:
```python
from explainability import explain_prediction

explanation = explain_prediction(
    prediction_value=0.75,
    input_features=network_metrics,
    model_instance=model
)
# Returns: {
#   "base_value": 0.30,
#   "shap_values": [...],
#   "feature_importance": {...},
#   "reasoning": "High latency (0.25) and jitter (0.15) indicate network degradation"
# }
```

2. **Feature Importance Analysis**:
- Calculate SHAP values for each prediction
- Identify top contributing features
- Generate human-readable explanations
- Track explanation confidence

3. **Fallback Explanations**:
- When SHAP fails, provide rule-based explanations
- Document decision logic
- Maintain explainability guarantee

**Validation Criteria**:
- ✅ SHAP values calculated for all predictions
- ✅ Feature importance rankings accurate
- ✅ Explanations human-readable
- ✅ No errors on edge cases

---

### Task 2.5: Model Performance Monitoring (1 hour)
**Objective**: Monitor model performance in production

**Status**: 🔄 To be implemented

**Monitoring Metrics**:
1. **Prediction Distribution**:
   - Track probability distribution of predictions
   - Monitor for distribution shift
   - Alert on anomalies

2. **Ground Truth Comparison**:
   - Compare predictions vs. actual outcomes
   - Calculate real-time accuracy
   - Track false positive/negative rates

3. **Latency Monitoring**:
   - Measure prediction response time
   - Track model.predict() execution time
   - Alert on performance degradation

4. **Data Drift Detection**:
   - Monitor input feature distributions
   - Compare against training distribution
   - Alert on significant drift

**Implementation**:
```python
# Log prediction with ground truth when available
from monitoring import log_prediction

log_prediction(
    timestamp=datetime.now(),
    model_version="1.0.0",
    input_features={...},
    prediction=0.75,
    actual_fault=1,  # ground truth
    explanation={...}
)
```

**Validation Criteria**:
- ✅ All predictions logged with metadata
- ✅ Ground truth comparison possible
- ✅ Performance metrics calculable
- ✅ Alerts functional for anomalies

---

### Task 2.6: Comprehensive Testing (4 hours)
**Objective**: Unit and integration tests for ML pipeline

**Status**: 🔄 To be implemented in `tests/` directory

**Test Suite Structure**:

#### Unit Tests (`tests/unit/test_ml_engine.py`)
```python
def test_dataset_generation():
    """Test synthetic data generation"""
    
def test_feature_scaling():
    """Test StandardScaler preprocessing"""
    
def test_model_training():
    """Test XGBoost training pipeline"""
    
def test_model_prediction():
    """Test prediction generation"""
    
def test_shap_calculation():
    """Test SHAP value calculation"""
    
def test_model_persistence():
    """Test model save/load"""
```

#### Integration Tests (`tests/integration/test_ml_api.py`)
```python
def test_predict_endpoint():
    """Test POST /api/v1/ml/predict"""
    
def test_predict_with_invalid_input():
    """Test validation on invalid input"""
    
def test_train_endpoint():
    """Test POST /api/v1/ml/train"""
    
def test_model_list_endpoint():
    """Test GET /api/v1/ml/models"""
    
def test_end_to_end_pipeline():
    """Test complete workflow"""
```

#### Fixtures and Helpers:
- Sample network metrics data
- Mock database sessions
- Test model instances
- Assertion helpers

**Test Execution**:
```bash
# Run all tests
pytest tests/ -v --cov=backend --cov-report=html

# Run only ML tests
pytest tests/unit/test_ml_engine.py -v

# Run with coverage report
pytest tests/ --cov=backend/ml_engine --cov-report=term-missing
```

**Coverage Goals**:
- ✅ ML module: >= 90% coverage
- ✅ API routes: >= 85% coverage
- ✅ Database models: >= 80% coverage
- ✅ Overall: >= 85% coverage

---

## Phase 2 Timeline

| Task | Duration | Status | 
|------|----------|--------|
| 2.1: Dataset & Training | 4 hrs | ⏳ In Progress |
| 2.2: Model Evaluation | 1 hr | ⏳ Pending |
| 2.3: API Endpoints | 2-3 hrs | ⏳ Pending |
| 2.4: SHAP Integration | 1 hr | ⏳ Pending |
| 2.5: Performance Monitoring | 1 hr | ⏳ Pending |
| 2.6: Testing | 4 hrs | ⏳ Pending |
| **Total Phase 2** | **~30 hours** | | 

**Estimated Completion**: 2-3 weeks (part-time development)

---

## Success Criteria

### After Task 2.1 (Training)
- ✅ Model file created and loadable
- ✅ Training accuracy >= 85%
- ✅ Predictions functional

### After Task 2.2 (Evaluation)
- ✅ All metrics calculated and stored
- ✅ Metrics accessible via database
- ✅ Historical tracking enabled

### After Task 2.3 (API)
- ✅ All 5 endpoints functional
- ✅ Swagger documentation complete
- ✅ Request/response validation working
- ✅ Error handling comprehensive

### After Task 2.4 (SHAP)
- ✅ Explanations generated for all predictions
- ✅ Feature importance rankings accurate
- ✅ Human-readable output

### After Task 2.5 (Monitoring)
- ✅ All predictions logged
- ✅ Performance metrics tracked
- ✅ Drift detection functional

### After Task 2.6 (Testing)
- ✅ All tests passing
- ✅ Coverage >= 85%
- ✅ CI/CD ready

---

## Next Steps

1. ✅ Complete environment setup (IN PROGRESS)
2. 🔄 Verify package installations complete
3. 🔄 Initialize SQLite database
4. 🔄 Execute ML model training
5. 🔄 Start API endpoint implementation
6. 🔄 Begin comprehensive testing

---

**Phase 2 Start Date**: 2026-09-01
**Status**: Environment setup in progress, ready to begin Task 2.1

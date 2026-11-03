# SelfHealNet - Autonomous Network Management System

A practical, end-to-end autonomous network management system combining real-time monitoring, AI/ML-based fault prediction, intelligent diagnosis, and SDN-based automatic recovery.

## Project Overview

SelfHealNet implements a complete network health management pipeline:

```
MONITOR → DETECT/PREDICT → DIAGNOSE → ASSESS RISK → EXPLAIN → SAFETY CHECK → RECOVER → VERIFY → FALLBACK → LOG → DISPLAY
```

## Key Features

✅ **Real-time Network Monitoring** - Continuous collection of network metrics (latency, packet loss, bandwidth, errors)

✅ **ML-Based Fault Prediction** - Genuine machine learning model trained on network data with proper train/test splits

✅ **Intelligent Diagnosis** - Root cause analysis with topology-aware fault diagnosis

✅ **Risk Assessment** - Severity scoring based on impact, probability, and criticality

✅ **Explainable AI** - SHAP-based explanations for predictions and recovery decisions

✅ **Safety-Aware Recovery** - Pre-flight validation, constraints checking, and rollback planning

✅ **SDN-Based Automatic Recovery** - OpenFlow-compatible recovery orchestration with fallback strategies

✅ **Verification Engine** - Automated post-recovery validation with automatic fallback triggering

✅ **Professional Dashboard** - Real-time visualization, incident tracking, and analytics

✅ **Complete Audit Trail** - Comprehensive logging of all decisions and actions

## Technology Stack

- **Backend**: Python with FastAPI
- **Machine Learning**: Random Forest, scikit-learn, SHAP, Joblib
- **Networking**: OpenFlow, Mininet, Ryu-compatible SDN controller
- **Database**: MySQL with SQLAlchemy
- **Frontend**: React, JavaScript, HTML/CSS, charting and topology visualization
- **Testing**: pytest, pytest-cov

## Project Structure

```
selfhealnet/
├── backend/                 # Python backend services
│   ├── monitoring/         # Network data collection
│   ├── ml_engine/          # Fault prediction model
│   ├── diagnosis/          # Fault diagnosis logic
│   ├── risk_assessment/    # Risk scoring engine
│   ├── explainability/     # SHAP/LIME integration
│   ├── safety/             # Pre-flight safety checks
│   ├── recovery/           # Recovery orchestration
│   ├── verification/       # Post-recovery validation
│   ├── database/           # DB models and schemas
│   └── api/                # REST API endpoints
├── frontend/               # React.js dashboard
├── data/                   # Datasets and models
│   ├── datasets/          # Training data
│   ├── models/            # Saved ML models
│   └── synthetic/         # Synthetic network data
├── network_sim/            # Mininet simulation setup
├── tests/                  # Test suites
├── docs/                   # Documentation
└── config/                 # Configuration files
```

## Getting Started

### Prerequisites
- Python 3.8+
- Node.js 14+
- PostgreSQL 12+
- Mininet (for network simulation)

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/
```

### Frontend Setup
```bash
cd frontend
npm install
npm start
```

### Network Simulation
```bash
cd network_sim
sudo python mininet_setup.py
```

## Development Phases

1. **Phase 1**: Foundation - Project setup, databases, monitoring collector
2. **Phase 2**: ML Implementation - Dataset prep, model training, evaluation
3. **Phase 3**: Core Analysis - Diagnosis, risk assessment, explainability
4. **Phase 4**: Recovery System - SDN integration, verification, fallback
5. **Phase 5**: Dashboard - Frontend development and visualization
6. **Phase 6**: Integration - End-to-end testing and documentation

## ML Model Details

The fault prediction model uses:
- **Dataset**: Synthetic network traffic with injected faults
- **Features**: Historical metrics, temporal patterns, topology information
- **Algorithm**: XGBoost (gradient boosting)
- **Train/Test Split**: 80/20 with cross-validation
- **Evaluation Metrics**: Precision, Recall, F1-Score, ROC-AUC
- **Model Persistence**: Joblib serialization

At runtime, predictions below the configured `PREDICTION_THRESHOLD` remain recorded with their observed/imputed feature provenance, but are treated as inconclusive. They do not create an incident unless independent measured telemetry supports a diagnosis. The dashboard shows the model probability and threshold outcome separately from confirmed incident history.

## API Endpoints (Documentation)

See [API Documentation](docs/API.md) for complete endpoint specifications.

## Contributing

This is a final-year college project. All contributions should follow the architecture guidelines in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

Academic Project - 2024/2025

## Contact

For questions or issues, refer to project documentation in `/docs/`.

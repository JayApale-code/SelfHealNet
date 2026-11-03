# SelfHealNet Environment Audit

Date: 2026-09-01

## Operating system
- OS: Microsoft Windows NT 10.0.26200.0

## Runtime and tooling
- Python: 3.12.10
- Node.js: MISSING
- npm: MISSING
- Git: 2.55.0.windows.2

## Network simulation and SDN availability
- Mininet: MISSING
- SDN controller: MISSING
  - Ryu module status: MISSING
  - ryu-manager command: not found

## Database availability
- MySQL: MISSING
  - mysql CLI: not found
  - mysqld: not found

## Required package status
Verified in the project virtual environment at `venv\Scripts\python.exe`.

- fastapi: OK
- uvicorn: OK
- sqlalchemy: OK
- pandas: OK
- numpy: OK
- scikit-learn: OK
- joblib: OK
- shap: OK
- python-dotenv: OK
- pymysql: OK
- ryu: MISSING

## Audit summary
The current environment is suitable for backend and ML development within the existing project venv, but it is not yet configured for full SDN simulation or MySQL-backed runtime testing.

No unnecessary software installation was performed during this audit.

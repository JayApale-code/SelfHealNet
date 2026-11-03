# SelfHealNet Setup Guide

This document records the Phase 0 environment findings and the next setup actions required for the project.

## Current environment status
- OS: Windows 10/Windows Server family
- Python: 3.12.10
- Git: available
- Node.js: missing
- npm: missing
- Mininet: missing
- SDN controller (Ryu): missing
- MySQL: missing

## Already available in the project venv
- FastAPI
- Uvicorn
- SQLAlchemy
- pandas
- numpy
- scikit-learn
- joblib
- SHAP
- python-dotenv
- PyMySQL

## Missing prerequisites for full stack execution
The following components are not available in the current environment and will be required for later phases:

1. Frontend toolchain
   - Install Node.js and npm for React tooling and frontend build steps.

2. SDN simulation stack
   - Install Mininet and Ryu when the environment supports Linux-based SDN testing.
   - A Windows host is not sufficient for full Mininet behavior without WSL or a Linux VM.

3. Database
   - Install and initialize MySQL for the preferred project database stack.

## Recommended approach
- Keep the project venv as the source of Python dependencies for backend and ML work.
- Delay nonessential software installation until a specific phase requires it.
- Use Linux/WSL for Mininet and Ryu tasks if full SDN testing is required.
- Use MySQL for application runtime and production-style integration testing.

## Phase 0 conclusion
The environment is partially ready for backend + ML development, but full SDN and database integration still require the missing operating-system-level tools above.

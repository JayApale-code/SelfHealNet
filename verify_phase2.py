#!/usr/bin/env python
"""Verify the preferred SelfHealNet stack is installed and importable."""

import sys

try:
    from sklearn.ensemble import RandomForestClassifier
    print(f"✓ RandomForestClassifier available: {RandomForestClassifier.__name__}")
except ImportError as e:
    print(f"✗ RandomForestClassifier: {e}")
    sys.exit(1)

try:
    import pandas
    print(f"✓ pandas {pandas.__version__}")
except ImportError as e:
    print(f"✗ pandas: {e}")
    sys.exit(1)

try:
    import numpy
    print(f"✓ numpy {numpy.__version__}")
except ImportError as e:
    print(f"✗ numpy: {e}")
    sys.exit(1)

try:
    import sklearn
    print(f"✓ scikit-learn {sklearn.__version__}")
except ImportError as e:
    print(f"✗ scikit-learn: {e}")
    sys.exit(1)

try:
    import shap
    print(f"✓ SHAP {shap.__version__}")
except ImportError as e:
    print(f"✗ SHAP: {e}")
    sys.exit(1)

try:
    import fastapi
    print(f"✓ FastAPI {fastapi.__version__}")
except ImportError as e:
    print(f"✗ FastAPI: {e}")
    sys.exit(1)

try:
    import sqlalchemy
    print(f"✓ SQLAlchemy {sqlalchemy.__version__}")
except ImportError as e:
    print(f"✗ SQLAlchemy: {e}")
    sys.exit(1)

try:
    import pymysql
    print(f"✓ PyMySQL {pymysql.__version__}")
except ImportError as e:
    print(f"✗ PyMySQL: {e}")
    sys.exit(1)

try:
    import ryu
    print(f"✓ Ryu available")
except ImportError as e:
    print(f"✗ Ryu: {e}")
    sys.exit(1)

print("\n✅ Preferred stack dependencies are installed and ready.")

# backend/__init__.py

"""SelfHealNet Backend Package."""

__version__ = "1.0.0"
__author__ = "SelfHealNet Development Team"
__description__ = "Autonomous Network Management System Backend"

try:
    from .config import config
except ImportError:  # pragma: no cover - compatibility fallback for test imports
    config = None

__all__ = ["config"]

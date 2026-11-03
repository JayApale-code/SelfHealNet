# config.py - Application Configuration

import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Config:
    """Base configuration"""
    
    # Application
    APP_NAME = "SelfHealNet"
    APP_VERSION = "1.0.0"
    DEBUG = False
    
    # Default to SQLite for local development so the project can run in a standard
    # developer environment without requiring a MySQL service. MySQL remains available
    # as an override through the DATABASE_URL environment variable.
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "sqlite:///./selfhealnet.db"
    )
    
    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # API
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", 8000))
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    
    # Monitoring
    MONITORING_INTERVAL = int(os.getenv("MONITORING_INTERVAL", 30))  # seconds
    BACKGROUND_WORKERS_ENABLED = os.getenv("BACKGROUND_WORKERS_ENABLED", "true").lower() == "true"
    METRIC_RETENTION_DAYS = int(os.getenv("METRIC_RETENTION_DAYS", 30))
    MONITORED_NETWORK_NAME = os.getenv("MONITORED_NETWORK_NAME") or None
    MONITORING_SOURCE = os.getenv("MONITORING_SOURCE") or None
    MONITORING_INTERFACE = os.getenv("MONITORING_INTERFACE") or None
    MONITORING_TARGET = os.getenv("MONITORING_TARGET", "8.8.8.8") or None
    MONITORING_TARGET_PORT = int(os.getenv("MONITORING_TARGET_PORT", 443))
    
    # ML Model
    MODEL_PATH = os.getenv(
        "MODEL_PATH",
        str(PROJECT_ROOT / "ml" / "model" / "fault_prediction_model.joblib"),
    )
    LEGACY_MODEL_PATH = str(PROJECT_ROOT / "data" / "models" / "backend_fault_prediction_model.joblib")
    MODEL_VERSION = "1.0.0"
    PREDICTION_THRESHOLD = float(os.getenv("PREDICTION_THRESHOLD", 0.7))
    
    # Recovery
    RECOVERY_TIMEOUT = int(os.getenv("RECOVERY_TIMEOUT", 300))  # seconds
    FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"
    SAFETY_CHECK_ENABLED = os.getenv("SAFETY_CHECK_ENABLED", "true").lower() == "true"
    
    # SDN Controller
    SDN_WSL_DISTRIBUTION = os.getenv("SDN_WSL_DISTRIBUTION", "Ubuntu-22.04").strip() or "Ubuntu-22.04"
    SDN_CONTROLLER_REST_HOST = os.getenv("SDN_CONTROLLER_REST_HOST", "127.0.0.1").strip() or "127.0.0.1"
    SDN_CONTROLLER_REST_PORT = int(os.getenv("SDN_CONTROLLER_REST_PORT", "8080"))
    SDN_CONTROLLER_URL = os.getenv(
        "SDN_CONTROLLER_URL",
        f"http://{SDN_CONTROLLER_REST_HOST}:{SDN_CONTROLLER_REST_PORT}",
    ).strip().rstrip("/") or None
    SDN_CONTROLLER_TYPE = os.getenv("SDN_CONTROLLER_TYPE", "ryu").strip().lower() or "ryu"
    SDN_PROTOCOL = os.getenv("SDN_PROTOCOL", "openflow")
    SDN_OPENFLOW_HOST = os.getenv("SDN_OPENFLOW_HOST", "127.0.0.1").strip() or "127.0.0.1"
    SDN_OPENFLOW_PORT = int(os.getenv("SDN_OPENFLOW_PORT", "6633"))
    SDN_OPENFLOW_VERSION = os.getenv("SDN_OPENFLOW_VERSION", "OpenFlow13").strip() or "OpenFlow13"
    SDN_CONTROLLER_USERNAME = os.getenv("SDN_CONTROLLER_USERNAME") or None
    SDN_CONTROLLER_PASSWORD = os.getenv("SDN_CONTROLLER_PASSWORD") or None
    SDN_CONTROLLER_API_TIMEOUT_SECONDS = float(os.getenv("SDN_CONTROLLER_API_TIMEOUT_SECONDS", "2"))
    SDN_RETRY_INTERVAL_SECONDS = float(os.getenv("SDN_RETRY_INTERVAL_SECONDS", "5"))
    SDN_SIMULATION_ENABLED = os.getenv("SDN_SIMULATION_ENABLED", "false").lower() == "true"
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/selfhealnet.log")
    
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    LOG_LEVEL = "WARNING"


class TestingConfig(Config):
    """Testing configuration"""
    DATABASE_URL = "sqlite:///./test.db"
    DEBUG = True
    TESTING = True


def get_config() -> Config:
    """Get configuration based on environment"""
    env = os.getenv("ENVIRONMENT", "development").lower()
    
    config_map = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }
    
    return config_map.get(env, DevelopmentConfig)()


# Export active config
config = get_config()

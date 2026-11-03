# main.py - FastAPI Application Entry Point

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
from contextlib import asynccontextmanager
try:
    from .config import config
except ImportError:
    from config import config

try:
    from .monitoring import initialize_monitoring, shutdown_monitoring
except ImportError:
    initialize_monitoring = None
    shutdown_monitoring = None

try:
    from .ml_engine.telemetry_pipeline import (
        initialize_telemetry_inference,
        shutdown_telemetry_inference,
    )
except ImportError:
    initialize_telemetry_inference = None
    shutdown_telemetry_inference = None

try:
    from .database import create_tables
except ImportError:
    create_tables = None

try:
    from .api.routes import router as api_router
except ImportError:
    from api.routes import router as api_router

# Configure logging
logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== Lifespan Events ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("🚀 SelfHealNet starting up...")
    if create_tables is not None:
        create_tables()
    if config.BACKGROUND_WORKERS_ENABLED:
        if initialize_monitoring is not None:
            initialize_monitoring()
        if initialize_telemetry_inference is not None:
            initialize_telemetry_inference()
    else:
        logger.info("Background monitoring and telemetry inference are disabled")
    logger.info("✅ SelfHealNet ready")
    
    yield
    
    # Shutdown
    logger.info("🛑 SelfHealNet shutting down...")
    if config.BACKGROUND_WORKERS_ENABLED:
        if shutdown_telemetry_inference is not None:
            shutdown_telemetry_inference()
        if shutdown_monitoring is not None:
            shutdown_monitoring()
    logger.info("✅ SelfHealNet shutdown complete")


# ==================== FastAPI App ====================

app = FastAPI(
    title="SelfHealNet",
    description="Autonomous Network Management System",
    version=config.APP_VERSION,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.exception_handler(RequestValidationError)
async def auth_validation_error_handler(request: Request, exc: RequestValidationError):
    sensitive_path = request.url.path.startswith("/api/v1/auth/") or request.url.path in {
        "/api/v1/users/me",
        "/api/v1/users/change-password",
    }
    errors = exc.errors()
    if sensitive_path:
        errors = [{key: value for key, value in error.items() if key != "input"} for error in errors]
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(errors)},
    )


# ==================== Health Check ====================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "application": config.APP_NAME,
        "version": config.APP_VERSION
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to SelfHealNet",
        "endpoints": {
            "health": "/health",
            "api": "/api/v1",
            "docs": "/docs"
        }
    }


# ==================== API Routes (Placeholder) ====================

@app.get("/api/v1/status")
async def api_status():
    """API status endpoint"""
    return {
        "api_version": "v1",
        "modules": [
            "monitoring",
            "ml_engine",
            "diagnosis",
            "risk_assessment",
            "recovery",
            "verification"
        ],
        "status": "operational"
    }


# ==================== Exception Handlers ====================

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# ==================== Startup/Shutdown Hooks ====================

@app.on_event("startup")
async def startup_event():
    """Application startup event"""
    logger.info("Application startup event triggered")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown event"""
    logger.info("Application shutdown event triggered")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "backend.main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower()
    )

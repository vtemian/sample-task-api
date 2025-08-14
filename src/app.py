"""
FastAPI Main Application Module

Production-ready FastAPI application with comprehensive middleware,
routing, error handling, and lifecycle management.
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# Import API routers and database dependencies
from api.users import router as users_router
from api.tasks import router as tasks_router
from core.database import database_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Response Models
class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    timestamp: datetime
    version: str

class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str
    detail: str
    correlation_id: str
    timestamp: datetime

# Application Lifespan Management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager for startup and shutdown events.
    
    Handles database connections and other resources that need to be
    initialized on startup and cleaned up on shutdown.
    """
    # Startup events
    logger.info("Starting up FastAPI application...")
    
    try:
        # Initialize database connection
        await database_manager.connect()
        logger.info("Database connection established successfully")
        
        # Add any other startup tasks here
        # e.g., initialize cache, load ML models, etc.
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {str(e)}")
        raise
    
    yield  # Application runs here
    
    # Shutdown events
    logger.info("Shutting down FastAPI application...")
    
    try:
        # Close database connection
        await database_manager.disconnect()
        logger.info("Database connection closed successfully")
        
        # Add any other cleanup tasks here
        
    except Exception as e:
        logger.error(f"Error during application shutdown: {str(e)}")

# Custom Middleware Functions
async def logging_middleware(request: Request, call_next) -> Response:
    """
    Request/Response logging middleware.
    
    Logs HTTP method, URL, status code, response time, and correlation ID
    for all requests to aid in debugging and monitoring.
    """
    # Generate correlation ID for request tracing
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    
    # Log incoming request
    start_time = time.time()
    logger.info(
        f"Request started - Method: {request.method}, "
        f"URL: {request.url}, Correlation ID: {correlation_id}"
    )
    
    try:
        # Process request
        response = await call_next(request)
        
        # Calculate response time
        process_time = time.time() - start_time
        
        # Log response
        logger.info(
            f"Request completed - Method: {request.method}, "
            f"URL: {request.url}, Status: {response.status_code}, "
            f"Time: {process_time:.4f}s, Correlation ID: {correlation_id}"
        )
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response
        
    except Exception as e:
        # Log error and re-raise
        process_time = time.time() - start_time
        logger.error(
            f"Request failed - Method: {request.method}, "
            f"URL: {request.url}, Error: {str(e)}, "
            f"Time: {process_time:.4f}s, Correlation ID: {correlation_id}"
        )
        raise

# FastAPI Application Initialization
app = FastAPI(
    title="Task Management API",
    description="A comprehensive task management system with user authentication and task operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Middleware Configuration
# Note: CORS middleware must be added before other middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React development server
        "http://localhost:8080",  # Vue development server
        "https://yourdomain.com", # Production frontend
        "https://www.yourdomain.com"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "X-Correlation-ID"
    ],
)

# Custom Logging Middleware
# Note: Custom middleware should be added after CORS middleware
@app.middleware("http")
async def add_logging_middleware(request: Request, call_next):
    """Add logging middleware to the application."""
    return await logging_middleware(request, call_next)

# API Router Inclusion
app.include_router(
    users_router,
    prefix="/api/v1/users",
    tags=["users"],
    responses={
        404: {"description": "User not found"},
        422: {"description": "Validation error"}
    }
)

app.include_router(
    tasks_router,
    prefix="/api/v1/tasks",
    tags=["tasks"],
    responses={
        404: {"description": "Task not found"},
        422: {"description": "Validation error"}
    }
)

# Global Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions with consistent error response format.
    """
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    logger.warning(
        f"HTTP Exception - Status: {exc.status_code}, "
        f"Detail: {exc.detail}, Correlation ID: {correlation_id}"
    )
    
    error_response = ErrorResponse(
        error="HTTP Exception",
        detail=str(exc.detail),
        correlation_id=correlation_id,
        timestamp=datetime.utcnow()
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.dict(),
        headers={"X-Correlation-ID": correlation_id}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle request validation errors with detailed error information.
    """
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    logger.warning(
        f"Validation Error - Detail: {exc.errors()}, "
        f"Correlation ID: {correlation_id}"
    )
    
    error_response = ErrorResponse(
        error="Validation Error",
        detail=f"Request validation failed: {exc.errors()}",
        correlation_id=correlation_id,
        timestamp=datetime.utcnow()
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.dict(),
        headers={"X-Correlation-ID": correlation_id}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all other exceptions with generic error response.
    """
    correlation_id = getattr(request.state, 'correlation_id', str(uuid.uuid4()))
    
    logger.error(
        f"Unhandled Exception - Type: {type(exc).__name__}, "
        f"Detail: {str(exc)}, Correlation ID: {correlation_id}",
        exc_info=True
    )
    
    error_response = ErrorResponse(
        error="Internal Server Error",
        detail="An unexpected error occurred. Please try again later.",
        correlation_id=correlation_id,
        timestamp=datetime.utcnow()
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.dict(),
        headers={"X-Correlation-ID": correlation_id}
    )

# Health Check Endpoint
@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check",
    description="Returns the current health status of the application"
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint for monitoring and load balancer health checks.
    
    Returns:
        HealthResponse: Current application health status and metadata
    """
    try:
        # Check database connectivity
        is_db_healthy = await database_manager.health_check()
        
        if not is_db_healthy:
            logger.warning("Health check failed - Database connectivity issue")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connectivity issue"
            )
        
        return HealthResponse(
            status="healthy",
            timestamp=datetime.utcnow(),
            version="1.0.0"
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Health check failed: {str(e)}"
        )

# Root endpoint
@app.get(
    "/",
    summary="Root Endpoint",
    description="Returns basic API information"
)
async def root() -> Dict[str, Any]:
    """
    Root endpoint providing basic API information.
    
    Returns:
        Dict containing API name, version, and documentation links
    """
    return {
        "name": "Task Management API",
        "version": "1.0.0",
        "description": "A comprehensive task management system",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_check": "/health"
    }

# Application entry point for development
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
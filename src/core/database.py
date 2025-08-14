"""
Core database connection and session management module for FastAPI applications.

This module provides async database connectivity using SQLAlchemy 2.0+ with support
for PostgreSQL, MySQL, and SQLite databases. It includes connection pooling,
health checks, and FastAPI dependency injection.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Union
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi import HTTPException, status
from pydantic import BaseSettings, validator
from sqlalchemy import event, text
from sqlalchemy.exc import (
    DatabaseError,
    DisconnectionError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, QueuePool

# Configure logging
logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database-related errors."""
    pass


class ConnectionError(DatabaseError):
    """Exception raised when database connection fails."""
    pass


class SessionError(DatabaseError):
    """Exception raised when database session operations fail."""
    pass


class HealthCheckError(DatabaseError):
    """Exception raised when database health check fails."""
    pass


class DatabaseSettings(BaseSettings):
    """Database configuration settings using Pydantic BaseSettings."""
    
    database_url: str
    db_pool_size: int = 20
    db_max_overflow: int = 0
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_echo: bool = False
    db_echo_pool: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = False
    
    @validator("database_url")
    def validate_database_url(cls, v: str) -> str:
        """Validate database URL format and supported schemes."""
        if not v:
            raise ValueError("DATABASE_URL is required")
        
        parsed = urlparse(v)
        supported_schemes = {
            "postgresql+asyncpg",
            "mysql+aiomysql",
            "sqlite+aiosqlite",
        }
        
        if parsed.scheme not in supported_schemes:
            raise ValueError(
                f"Unsupported database scheme: {parsed.scheme}. "
                f"Supported schemes: {', '.join(supported_schemes)}"
            )
        
        return v
    
    @validator("db_pool_size")
    def validate_pool_size(cls, v: int) -> int:
        """Validate pool size is within reasonable bounds."""
        if v < 5:
            logger.warning("Pool size is below recommended minimum of 5")
        if v > 50:
            logger.warning("Pool size is above recommended maximum of 50")
        return v


class DatabaseManager:
    """
    Database manager class handling engine creation, session management,
    and health checks.
    """
    
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._is_initialized = False
    
    async def initialize(self) -> None:
        """Initialize database engine and session factory."""
        if self._is_initialized:
            logger.warning("Database manager already initialized")
            return
        
        try:
            await self._create_engine()
            self._create_session_factory()
            await self._verify_connection()
            self._is_initialized = True
            logger.info("Database manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database manager: {e}")
            raise ConnectionError(f"Database initialization failed: {e}") from e
    
    async def _create_engine(self) -> None:
        """Create async SQLAlchemy engine with appropriate configuration."""
        parsed_url = urlparse(self.settings.database_url)
        
        # Configure engine parameters based on database type
        engine_kwargs = {
            "echo": self.settings.db_echo,
            "echo_pool": self.settings.db_echo_pool,
            "future": True,
        }
        
        # SQLite doesn't support connection pooling
        if parsed_url.scheme == "sqlite+aiosqlite":
            engine_kwargs.update({
                "poolclass": NullPool,
                "connect_args": {"check_same_thread": False},
            })
        else:
            engine_kwargs.update({
                "poolclass": QueuePool,
                "pool_size": self.settings.db_pool_size,
                "max_overflow": self.settings.db_max_overflow,
                "pool_timeout": self.settings.db_pool_timeout,
                "pool_recycle": self.settings.db_pool_recycle,
                "pool_pre_ping": self.settings.db_pool_pre_ping,
            })
        
        self.engine = create_async_engine(
            self.settings.database_url,
            **engine_kwargs
        )
        
        # Add event listeners for connection monitoring
        self._setup_event_listeners()
    
    def _create_session_factory(self) -> None:
        """Create async session factory."""
        if not self.engine:
            raise ConnectionError("Engine not initialized")
        
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=True,
            autocommit=False,
        )
    
    def _setup_event_listeners(self) -> None:
        """Setup SQLAlchemy event listeners for monitoring."""
        if not self.engine:
            return
        
        @event.listens_for(self.engine.sync_engine, "connect")
        def on_connect(dbapi_connection, connection_record):
            logger.debug("Database connection established")
        
        @event.listens_for(self.engine.sync_engine, "disconnect")
        def on_disconnect(dbapi_connection, connection_record):
            logger.debug("Database connection closed")
        
        @event.listens_for(self.engine.sync_engine, "handle_error")
        def on_handle_error(exception_context):
            logger.error(
                f"Database error occurred: {exception_context.original_exception}"
            )
    
    async def _verify_connection(self) -> None:
        """Verify database connection is working."""
        if not self.engine:
            raise ConnectionError("Engine not initialized")
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.info("Database connection verified")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    raise ConnectionError(f"Connection verification failed: {e}") from e
                
                logger.warning(
                    f"Connection verification attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {retry_delay} seconds..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get database session with automatic cleanup.
        
        Yields:
            AsyncSession: Database session
            
        Raises:
            SessionError: If session creation or management fails
        """
        if not self._is_initialized or not self.session_factory:
            raise SessionError("Database manager not initialized")
        
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Session error, rolling back: {e}")
            raise SessionError(f"Database session error: {e}") from e
        finally:
            await session.close()
    
    async def health_check(self) -> dict[str, Union[str, bool, int]]:
        """
        Perform database health check.
        
        Returns:
            dict: Health check results
            
        Raises:
            HealthCheckError: If health check fails
        """
        if not self._is_initialized or not self.engine:
            raise HealthCheckError("Database manager not initialized")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(text("SELECT 1 as health_check"))
                row = result.fetchone()
                
                if not row or row[0] != 1:
                    raise HealthCheckError("Health check query returned unexpected result")
            
            response_time = round((asyncio.get_event_loop().time() - start_time) * 1000, 2)
            
            # Get pool status for non-SQLite databases
            pool_info = {}
            if hasattr(self.engine.pool, 'size'):
                pool_info = {
                    "pool_size": self.engine.pool.size(),
                    "checked_in": self.engine.pool.checkedin(),
                    "checked_out": self.engine.pool.checkedout(),
                }
            
            return {
                "status": "healthy",
                "database": "connected",
                "response_time_ms": response_time,
                **pool_info,
            }
            
        except (OperationalError, DatabaseError, TimeoutError) as e:
            logger.error(f"Database health check failed: {e}")
            raise HealthCheckError(f"Health check failed: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during health check: {e}")
            raise HealthCheckError(f"Health check error: {e}") from e
    
    async def close(self) -> None:
        """Close database connections and cleanup resources."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connections closed")
        
        self._is_initialized = False
        self.engine = None
        self.session_factory = None


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


# Global database manager instance
settings = DatabaseSettings()
db_manager = DatabaseManager(settings)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency function to get database session.
    
    Yields:
        AsyncSession: Database session
        
    Raises:
        HTTPException: If database session cannot be created
    """
    try:
        async with db_manager.get_session() as session:
            yield session
    except SessionError as e:
        logger.error(f"Failed to create database session: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable"
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error in get_db: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        ) from e


async def check_database_health() -> dict[str, Union[str, bool, int]]:
    """
    Check database health status.
    
    Returns:
        dict: Health check results
        
    Raises:
        HTTPException: If health check fails
    """
    try:
        return await db_manager.health_check()
    except HealthCheckError as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database health check failed"
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error during health check: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check error"
        ) from e


def run_migrations() -> None:
    """
    Run Alembic database migrations.
    
    Raises:
        DatabaseError: If migration fails
    """
    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", "").replace("+aiomysql", "").replace("+aiosqlite", ""))
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise DatabaseError(f"Migration failed: {e}") from e


async def initialize_database() -> None:
    """
    Initialize database manager and run migrations.
    
    This function should be called during application startup.
    """
    try:
        await db_manager.initialize()
        logger.info("Database initialization completed")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def close_database() -> None:
    """
    Close database connections.
    
    This function should be called during application shutdown.
    """
    try:
        await db_manager.close()
        logger.info("Database connections closed successfully")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")


# Context manager for database lifecycle management
@asynccontextmanager
async def database_lifespan():
    """
    Context manager for database lifecycle management.
    
    Use this in FastAPI lifespan events.
    """
    try:
        await initialize_database()
        yield
    finally:
        await close_database()
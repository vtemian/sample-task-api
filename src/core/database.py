"""
Core database module with SQLAlchemy 2.x async support and Alembic integration.

This module provides database connection management, session handling, and migration
support for FastAPI applications using PostgreSQL with asyncpg driver.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from pydantic import BaseSettings, Field, validator
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError, TimeoutError as SQLTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, QueuePool
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

# Configure logging
logger = logging.getLogger(__name__)


class DatabaseSettings(BaseSettings):
    """Database configuration settings with validation."""
    
    database_url: str = Field(..., env="DATABASE_URL")
    db_pool_size: int = Field(20, env="DB_POOL_SIZE", ge=1, le=100)
    db_max_overflow: int = Field(0, env="DB_MAX_OVERFLOW", ge=0, le=50)
    db_pool_timeout: int = Field(30, env="DB_POOL_TIMEOUT", ge=5, le=300)
    db_pool_recycle: int = Field(3600, env="DB_POOL_RECYCLE", ge=300, le=7200)
    db_echo: bool = Field(False, env="DB_ECHO")
    db_echo_pool: bool = Field(False, env="DB_ECHO_POOL")
    
    @validator("database_url")
    def validate_database_url(cls, v: str) -> str:
        """Ensure database URL uses asyncpg driver for PostgreSQL."""
        if not v:
            raise ValueError("DATABASE_URL is required")
        
        # Convert postgresql:// to postgresql+asyncpg:// if needed
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use PostgreSQL with asyncpg driver "
                "(postgresql+asyncpg://...)"
            )
        
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


class DatabaseManager:
    """Manages database connections, sessions, and health checks."""
    
    def __init__(self, settings: Optional[DatabaseSettings] = None):
        self.settings = settings or DatabaseSettings()
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._is_initialized = False
    
    @property
    def engine(self) -> AsyncEngine:
        """Get the database engine, initializing if necessary."""
        if not self._engine:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine
    
    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get the session factory, initializing if necessary."""
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._session_factory
    
    def initialize(self) -> None:
        """Initialize database engine and session factory."""
        if self._is_initialized:
            logger.warning("Database already initialized")
            return
        
        try:
            # Create async engine with connection pooling
            self._engine = create_async_engine(
                self.settings.database_url,
                poolclass=QueuePool,
                pool_size=self.settings.db_pool_size,
                max_overflow=self.settings.db_max_overflow,
                pool_timeout=self.settings.db_pool_timeout,
                pool_recycle=self.settings.db_pool_recycle,
                pool_pre_ping=True,  # Validate connections before use
                echo=self.settings.db_echo,
                echo_pool=self.settings.db_echo_pool,
                future=True,
            )
            
            # Create session factory
            self._session_factory = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=True,
                autocommit=False,
            )
            
            # Add connection event listeners
            self._setup_event_listeners()
            
            self._is_initialized = True
            logger.info("Database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
    def _setup_event_listeners(self) -> None:
        """Setup SQLAlchemy event listeners for connection monitoring."""
        
        @event.listens_for(self._engine.sync_engine, "connect")
        def receive_connect(dbapi_connection, connection_record):
            """Log successful connections."""
            logger.debug("Database connection established")
        
        @event.listens_for(self._engine.sync_engine, "disconnect")
        def receive_disconnect(dbapi_connection, connection_record):
            """Log disconnections."""
            logger.debug("Database connection closed")
        
        @event.listens_for(self._engine.sync_engine, "handle_error")
        def receive_error(exception_context):
            """Log connection errors."""
            logger.error(f"Database error: {exception_context.original_exception}")
    
    async def close(self) -> None:
        """Close database connections and cleanup resources."""
        if self._engine:
            await self._engine.dispose()
            logger.info("Database connections closed")
        
        self._engine = None
        self._session_factory = None
        self._is_initialized = False
    
    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Async context manager for database sessions with proper cleanup.
        
        Yields:
            AsyncSession: Database session
            
        Raises:
            SQLAlchemyError: For database-related errors
            ConnectionError: For connection issues
        """
        if not self._is_initialized:
            raise RuntimeError("Database not initialized")
        
        session = self.session_factory()
        try:
            # Test connection before yielding session
            await session.execute(text("SELECT 1"))
            yield session
            await session.commit()
            
        except (SQLAlchemyError, ConnectionError, SQLTimeoutError) as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        except Exception as e:
            await session.rollback()
            logger.error(f"Unexpected error in database session: {e}")
            raise
        finally:
            await session.close()
    
    async def health_check(self, timeout: float = 5.0) -> dict:
        """
        Perform database health check with connection validation.
        
        Args:
            timeout: Maximum time to wait for health check
            
        Returns:
            dict: Health check results
        """
        start_time = time.time()
        
        try:
            async with asyncio.timeout(timeout):
                async with self.get_session() as session:
                    # Test basic connectivity
                    result = await session.execute(text("SELECT 1 as health_check"))
                    row = result.fetchone()
                    
                    if row and row.health_check == 1:
                        elapsed = time.time() - start_time
                        return {
                            "status": "healthy",
                            "response_time": round(elapsed * 1000, 2),  # ms
                            "database": "postgresql",
                            "pool_size": self.settings.db_pool_size,
                            "pool_checked_out": self.engine.pool.checkedout(),
                            "pool_overflow": self.engine.pool.overflow(),
                        }
                    else:
                        raise RuntimeError("Health check query returned unexpected result")
                        
        except asyncio.TimeoutError:
            return {
                "status": "unhealthy",
                "error": f"Health check timed out after {timeout}s",
                "response_time": timeout * 1000,
            }
        except (SQLAlchemyError, ConnectionError) as e:
            return {
                "status": "unhealthy",
                "error": f"Database connection error: {str(e)}",
                "response_time": (time.time() - start_time) * 1000,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": f"Unexpected error: {str(e)}",
                "response_time": (time.time() - start_time) * 1000,
            }
    
    async def retry_connection(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> bool:
        """
        Retry database connection with exponential backoff.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay between retries in seconds
            max_delay: Maximum delay between retries in seconds
            
        Returns:
            bool: True if connection successful, False otherwise
        """
        for attempt in range(max_retries + 1):
            try:
                health = await self.health_check()
                if health["status"] == "healthy":
                    logger.info(f"Database connection successful on attempt {attempt + 1}")
                    return True
                    
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries:
                # Exponential backoff with jitter
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.info(f"Retrying connection in {delay:.1f} seconds...")
                await asyncio.sleep(delay)
        
        logger.error(f"Failed to establish database connection after {max_retries + 1} attempts")
        return False


class AlembicManager:
    """Manages Alembic migrations and database schema operations."""
    
    def __init__(self, alembic_cfg_path: str = "alembic.ini"):
        self.alembic_cfg_path = alembic_cfg_path
        self._config: Optional[Config] = None
    
    @property
    def config(self) -> Config:
        """Get Alembic configuration."""
        if not self._config:
            if not os.path.exists(self.alembic_cfg_path):
                raise FileNotFoundError(f"Alembic config file not found: {self.alembic_cfg_path}")
            
            self._config = Config(self.alembic_cfg_path)
            
            # Override database URL from environment if available
            db_url = os.getenv("DATABASE_URL")
            if db_url:
                # Convert async URL to sync for Alembic
                if "postgresql+asyncpg://" in db_url:
                    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
                self._config.set_main_option("sqlalchemy.url", db_url)
        
        return self._config
    
    def upgrade(self, revision: str = "head") -> None:
        """
        Run database migrations up to specified revision.
        
        Args:
            revision: Target revision (default: "head")
        """
        try:
            logger.info(f"Running database migrations to {revision}")
            command.upgrade(self.config, revision)
            logger.info("Database migrations completed successfully")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise
    
    def downgrade(self, revision: str) -> None:
        """
        Downgrade database to specified revision.
        
        Args:
            revision: Target revision
        """
        try:
            logger.info(f"Downgrading database to {revision}")
            command.downgrade(self.config, revision)
            logger.info("Database downgrade completed successfully")
        except Exception as e:
            logger.error(f"Downgrade failed: {e}")
            raise
    
    def current_revision(self) -> Optional[str]:
        """
        Get current database revision.
        
        Returns:
            str: Current revision or None if not versioned
        """
        try:
            script = ScriptDirectory.from_config(self.config)
            
            def get_rev(rev, context):
                return rev
            
            with self.config.attributes.get("connection", None) or \
                 script.env_py_location.create_engine().connect() as connection:
                context = MigrationContext.configure(connection)
                return context.get_current_revision()
                
        except Exception as e:
            logger.error(f"Failed to get current revision: {e}")
            return None
    
    def create_migration(self, message: str, autogenerate: bool = True) -> None:
        """
        Create a new migration file.
        
        Args:
            message: Migration message
            autogenerate: Whether to auto-generate migration content
        """
        try:
            logger.info(f"Creating migration: {message}")
            command.revision(
                self.config,
                message=message,
                autogenerate=autogenerate
            )
            logger.info("Migration file created successfully")
        except Exception as e:
            logger.error(f"Failed to create migration: {e}")
            raise


# Global database manager instance
db_manager = DatabaseManager()
alembic_manager = AlembicManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.
    
    Yields:
        AsyncSession: Database session
        
    Raises:
        HTTPException: For database connection errors
    """
    try:
        async with db_manager.get_session() as session:
            yield session
    except (SQLAlchemyError, ConnectionError) as e:
        logger.error(f"Database dependency error: {e}")
        # Re-raise to let FastAPI handle the HTTP response
        raise


async def init_database() -> None:
    """Initialize database connection and run migrations."""
    try:
        # Initialize database manager
        db_manager.initialize()
        
        # Test connection with retries
        if not await db_manager.retry_connection():
            raise ConnectionError("Failed to establish database connection")
        
        # Run migrations
        alembic_manager.upgrade()
        
        logger.info("Database initialization completed successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def close_database() -> None:
    """Close database connections and cleanup resources."""
    await db_manager.close()
    logger.info("Database cleanup completed")


# Convenience functions for direct access
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session outside of FastAPI context."""
    async with db_manager.get_session() as session:
        yield session


async def health_check() -> dict:
    """Perform database health check."""
    return await db_manager.health_check()


def run_migrations(revision: str = "head") -> None:
    """Run database migrations."""
    alembic_manager.upgrade(revision)


def create_migration(message: str, autogenerate: bool = True) -> None:
    """Create new migration file."""
    alembic_manager.create_migration(message, autogenerate)


# Export public interface
__all__ = [
    "Base",
    "DatabaseManager",
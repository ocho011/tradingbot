"""
Database engine configuration and session management.

This module provides async SQLAlchemy engine setup, session factory,
and connection pool management for the trading bot database.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, QueuePool

from src.database.models import Base

logger = logging.getLogger(__name__)


# Global engine and session factory
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_database_url() -> str:
    """
    Get database URL from environment or use default SQLite.

    Returns:
        Database connection URL

    Environment Variables:
        DATABASE_URL: Full database connection string
        DB_PATH: Path to SQLite database file (default: ./data/tradingbot.db)
    """
    # Check for full DATABASE_URL first
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        # Convert postgresql:// to postgresql+asyncpg:// if needed
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return db_url

    # Default to SQLite with aiosqlite driver
    db_path = os.getenv("DB_PATH", "./data/tradingbot.db")

    # Ensure data directory exists
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "./data", exist_ok=True)

    return f"sqlite+aiosqlite:///{db_path}"


def create_engine(
    database_url: Optional[str] = None,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """
    Create async SQLAlchemy engine with connection pooling.

    Args:
        database_url: Database connection URL (uses get_database_url() if None)
        echo: Enable SQL query logging
        pool_size: Number of connections to maintain in pool
        max_overflow: Maximum overflow connections beyond pool_size
        pool_pre_ping: Enable connection health checks

    Returns:
        Configured async SQLAlchemy engine
    """
    if database_url is None:
        database_url = get_database_url()

    # SQLite doesn't support connection pooling
    if database_url.startswith("sqlite"):
        engine = create_async_engine(
            database_url,
            echo=echo,
            poolclass=NullPool,  # No pooling for SQLite
            connect_args={"check_same_thread": False},  # Allow multi-threaded access
        )
        logger.info(f"Created SQLite async engine: {database_url}")
    else:
        # PostgreSQL or other databases with connection pooling
        engine = create_async_engine(
            database_url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=pool_pre_ping,
            poolclass=QueuePool,
        )
        logger.info(f"Created async engine with pooling: {database_url}")

    return engine


def get_engine() -> AsyncEngine:
    """
    Get or create the global database engine.

    Returns:
        Global async engine instance

    Raises:
        RuntimeError: If engine hasn't been initialized
    """
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the global session factory.

    Returns:
        Global async session factory

    Raises:
        RuntimeError: If session factory hasn't been initialized
    """
    if _session_factory is None:
        raise RuntimeError("Session factory not initialized. Call init_db() first.")
    return _session_factory


async def init_db(
    database_url: Optional[str] = None,
    echo: bool = False,
    create_tables: bool = True,
) -> None:
    """
    Initialize database engine, session factory, and optionally create tables.

    This should be called once at application startup.

    Args:
        database_url: Database connection URL (uses get_database_url() if None)
        echo: Enable SQL query logging
        create_tables: Whether to create all tables on initialization

    Example:
        >>> await init_db(echo=True, create_tables=True)
    """
    global _engine, _session_factory

    # Create engine
    _engine = create_engine(database_url, echo=echo)

    # Create session factory
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Don't expire objects after commit
        autocommit=False,
        autoflush=False,
    )

    logger.info("Database engine and session factory initialized")

    # Create tables if requested
    if create_tables:
        await create_all_tables()


async def create_all_tables() -> None:
    """
    Create all database tables based on SQLAlchemy models.

    This uses the Base metadata to create all tables defined in models.py.
    Safe to call multiple times - only creates tables that don't exist.

    Raises:
        RuntimeError: If engine hasn't been initialized
    """
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables created successfully")


async def drop_all_tables() -> None:
    """
    Drop all database tables.

    ⚠️ WARNING: This will delete all data in the database!
    Only use for testing or complete database reset.

    Raises:
        RuntimeError: If engine hasn't been initialized
    """
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    logger.warning("All database tables dropped")


async def close_db() -> None:
    """
    Close database engine and cleanup resources.

    This should be called on application shutdown.
    """
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine closed and resources cleaned up")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get async database session with automatic cleanup.

    This is an async context manager that provides a session and
    handles commit/rollback automatically.

    Yields:
        AsyncSession instance

    Example:
        >>> async with get_session() as session:
        ...     result = await session.execute(select(Trade))
        ...     trades = result.scalars().all()

    Raises:
        RuntimeError: If session factory hasn't been initialized
    """
    factory = get_session_factory()
    session = factory()

    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def health_check() -> bool:
    """
    Check database connection health.

    Returns:
        True if database is accessible, False otherwise
    """
    try:
        from sqlalchemy import text

        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

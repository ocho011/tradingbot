"""
Pytest fixtures for database DAO tests.

Provides shared fixtures for setting up test database, sessions,
and common test data for DAO testing.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.constants import TimeFrame
from src.database.dao import (
    BacktestResultDAO,
    PositionDAO,
    StatisticsDAO,
    TradeDAO,
)
from src.database.models import BacktestResult, Base, Position, Statistics, Trade


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Get test database URL (in-memory SQLite)."""
    return "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine(test_db_url: str):
    """Create async engine for tests."""
    engine = create_async_engine(
        test_db_url,
        echo=False,
        poolclass=None,  # No pooling for SQLite
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async session for tests."""
    SessionFactory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with SessionFactory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def trade_dao(session: AsyncSession) -> TradeDAO:
    """Create TradeDAO instance."""
    return TradeDAO(session)


@pytest_asyncio.fixture
async def position_dao(session: AsyncSession) -> PositionDAO:
    """Create PositionDAO instance."""
    return PositionDAO(session)


@pytest_asyncio.fixture
async def statistics_dao(session: AsyncSession) -> StatisticsDAO:
    """Create StatisticsDAO instance."""
    return StatisticsDAO(session)


@pytest_asyncio.fixture
async def backtest_dao(session: AsyncSession) -> BacktestResultDAO:
    """Create BacktestResultDAO instance."""
    return BacktestResultDAO(session)


@pytest_asyncio.fixture
async def sample_trade(session: AsyncSession) -> Trade:
    """Create a sample trade for testing."""
    trade = Trade(
        symbol="BTCUSDT",
        strategy="MACD",
        timeframe=TimeFrame.H1,
        entry_time=datetime.utcnow(),
        entry_price=Decimal("50000.00"),
        quantity=Decimal("0.1"),
        leverage=1,
        side="LONG",
        status="OPEN",
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade)
    return trade


@pytest_asyncio.fixture
async def sample_closed_trade(session: AsyncSession) -> Trade:
    """Create a sample closed trade for testing."""
    entry_time = datetime.utcnow() - timedelta(hours=2)
    exit_time = datetime.utcnow() - timedelta(hours=1)

    trade = Trade(
        symbol="BTCUSDT",
        strategy="MACD",
        timeframe=TimeFrame.H1,
        entry_time=entry_time,
        entry_price=Decimal("50000.00"),
        exit_time=exit_time,
        exit_price=Decimal("55000.00"),
        quantity=Decimal("0.1"),
        leverage=1,
        side="LONG",
        status="CLOSED",
        pnl=Decimal("500.00"),
        pnl_percent=10.0,
        fees=Decimal("10.00"),
        exit_reason="TP",
    )
    session.add(trade)
    await session.commit()
    await session.refresh(trade)
    return trade


@pytest_asyncio.fixture
async def sample_position(session: AsyncSession) -> Position:
    """Create a sample position for testing."""
    position = Position(
        symbol="BTCUSDT",
        strategy="MACD",
        timeframe=TimeFrame.H1,
        side="LONG",
        size=Decimal("0.1"),
        entry_price=Decimal("50000.00"),
        leverage=1,
        status="OPEN",
        opened_at=datetime.utcnow(),
    )
    session.add(position)
    await session.commit()
    await session.refresh(position)
    return position


@pytest_asyncio.fixture
async def sample_statistics(session: AsyncSession) -> Statistics:
    """Create sample statistics for testing."""
    stats = Statistics(
        strategy="MACD",
        period_type="DAILY",
        period_start=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
        period_end=datetime.utcnow().replace(hour=23, minute=59, second=59, microsecond=999999),
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        win_rate=60.0,
        total_pnl=Decimal("1000.00"),
        gross_profit=Decimal("1500.00"),
        gross_loss=Decimal("-500.00"),
        profit_factor=3.0,
    )
    session.add(stats)
    await session.commit()
    await session.refresh(stats)
    return stats


@pytest_asyncio.fixture
async def sample_backtest(session: AsyncSession) -> BacktestResult:
    """Create sample backtest result for testing."""
    backtest = BacktestResult(
        name="MACD Test 1",
        strategy="MACD",
        symbol="BTCUSDT",
        timeframe=TimeFrame.H1,
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        total_trades=100,
        winning_trades=60,
        losing_trades=40,
        win_rate=60.0,
        initial_capital=Decimal("10000.00"),
        final_capital=Decimal("15000.00"),
        total_return=50.0,
        total_pnl=Decimal("5000.00"),
        sharpe_ratio=2.5,
        max_drawdown=-15.0,
        configuration='{"macd_fast": 12, "macd_slow": 26, "macd_signal": 9}',
    )
    session.add(backtest)
    await session.commit()
    await session.refresh(backtest)
    return backtest

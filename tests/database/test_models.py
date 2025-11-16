"""
Tests for database models and schema validation.

Tests table creation, constraints, indexes, and data integrity.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from src.core.constants import TimeFrame
from src.database import (
    BacktestResult,
    Position,
    Statistics,
    Trade,
    close_db,
    create_all_tables,
    drop_all_tables,
    get_session,
    init_db,
)


@pytest.fixture(scope="function", autouse=True)
async def db_session():
    """Initialize test database and provide session for each test."""
    # Close any existing database connections
    try:
        await close_db()
    except Exception:
        pass

    # Use shared cache in-memory SQLite for tests
    # The '?cache=shared' parameter allows multiple connections to share the same in-memory database
    await init_db(
        database_url="sqlite+aiosqlite:///:memory:?cache=shared&uri=true",
        create_tables=False,  # Don't create tables yet
    )

    # Drop and recreate tables for each test to ensure clean state
    await drop_all_tables()
    await create_all_tables()

    yield

    # Cleanup
    await close_db()


@pytest.mark.unit
class TestDatabaseSchema:
    """Test database schema creation and structure."""

    async def test_tables_created(self, db_session):
        """Test that all tables are created."""
        from src.database.engine import get_engine

        engine = get_engine()

        def get_tables(sync_conn):
            inspector = inspect(sync_conn)
            return inspector.get_table_names()

        async with engine.connect() as conn:
            tables = await conn.run_sync(get_tables)

        expected_tables = {"trades", "positions", "statistics", "backtest_results"}
        assert expected_tables.issubset(
            set(tables)
        ), f"Missing tables: {expected_tables - set(tables)}"

    async def test_trade_table_columns(self, db_session):
        """Test Trade table has required columns."""
        from src.database.engine import get_engine

        engine = get_engine()

        def get_columns(sync_conn):
            inspector = inspect(sync_conn)
            return {col["name"] for col in inspector.get_columns("trades")}

        async with engine.connect() as conn:
            columns = await conn.run_sync(get_columns)

        required_columns = {
            "id",
            "symbol",
            "strategy",
            "timeframe",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "quantity",
            "leverage",
            "side",
            "pnl",
            "pnl_percent",
            "fees",
            "status",
            "exit_reason",
            "created_at",
            "updated_at",
            "position_id",
        }

        assert required_columns.issubset(columns), f"Missing columns: {required_columns - columns}"

    async def test_trade_indexes_created(self, db_session):
        """Test that indexes are created for Trade table."""
        from src.database.engine import get_engine

        engine = get_engine()

        def get_indexes(sync_conn):
            inspector = inspect(sync_conn)
            return {idx["name"] for idx in inspector.get_indexes("trades")}

        async with engine.connect() as conn:
            indexes = await conn.run_sync(get_indexes)

        # Check that our custom indexes exist
        expected_indexes = {
            "idx_trade_symbol_strategy",
            "idx_trade_entry_time",
            "idx_trade_status",
        }

        assert expected_indexes.issubset(indexes), f"Missing indexes: {expected_indexes - indexes}"


@pytest.mark.unit
class TestTradeModel:
    """Test Trade model CRUD operations and constraints."""

    async def test_create_trade(self, db_session):
        """Test creating a valid trade record."""
        async with get_session() as session:
            trade = Trade(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.M15,
                entry_time=datetime.now(timezone.utc),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("0.1"),
                leverage=10,
                side="LONG",
                status="OPEN",
            )

            session.add(trade)
            await session.commit()

            assert trade.id is not None
            assert trade.created_at is not None
            assert trade.updated_at is not None

    async def test_trade_quantity_constraint(self, db_session):
        """Test that quantity must be positive."""
        from src.database.engine import get_session_factory

        factory = get_session_factory()
        session = factory()

        try:
            trade = Trade(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.M15,
                entry_time=datetime.now(timezone.utc),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("-0.1"),  # Invalid: negative quantity
                leverage=10,
                side="LONG",
                status="OPEN",
            )

            session.add(trade)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()

    async def test_trade_leverage_constraint(self, db_session):
        """Test that leverage must be positive."""
        from src.database.engine import get_session_factory

        factory = get_session_factory()
        session = factory()

        try:
            trade = Trade(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.M15,
                entry_time=datetime.now(timezone.utc),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("0.1"),
                leverage=0,  # Invalid: zero leverage
                side="LONG",
                status="OPEN",
            )

            session.add(trade)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()

    async def test_trade_invalid_side(self, db_session):
        """Test that side must be LONG or SHORT."""
        from src.database.engine import get_session_factory

        factory = get_session_factory()
        session = factory()

        try:
            trade = Trade(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.M15,
                entry_time=datetime.now(timezone.utc),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("0.1"),
                leverage=10,
                side="INVALID",  # Invalid side
                status="OPEN",
            )

            session.add(trade)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()

    async def test_query_trades_by_symbol(self, db_session):
        """Test querying trades by symbol."""
        async with get_session() as session:
            # Create test trades
            trades = [
                Trade(
                    symbol="BTCUSDT",
                    strategy="test",
                    timeframe=TimeFrame.M15,
                    entry_time=datetime.now(timezone.utc),
                    entry_price=Decimal("50000"),
                    quantity=Decimal("0.1"),
                    leverage=10,
                    side="LONG",
                    status="OPEN",
                ),
                Trade(
                    symbol="ETHUSDT",
                    strategy="test",
                    timeframe=TimeFrame.M15,
                    entry_time=datetime.now(timezone.utc),
                    entry_price=Decimal("3000"),
                    quantity=Decimal("1.0"),
                    leverage=10,
                    side="LONG",
                    status="OPEN",
                ),
            ]

            for trade in trades:
                session.add(trade)
            await session.commit()

            # Query BTC trades
            result = await session.execute(select(Trade).where(Trade.symbol == "BTCUSDT"))
            btc_trades = result.scalars().all()

            assert len(btc_trades) == 1
            assert btc_trades[0].symbol == "BTCUSDT"


@pytest.mark.unit
class TestPositionModel:
    """Test Position model CRUD operations and constraints."""

    async def test_create_position(self, db_session):
        """Test creating a valid position record."""
        async with get_session() as session:
            position = Position(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.H1,
                side="LONG",
                size=Decimal("0.5"),
                entry_price=Decimal("50000.00"),
                leverage=10,
                status="OPEN",
                opened_at=datetime.now(timezone.utc),
            )

            session.add(position)
            await session.commit()

            assert position.id is not None
            assert position.unrealized_pnl == 0

    async def test_position_size_constraint(self, db_session):
        """Test that position size must be positive."""
        from src.database.engine import get_session_factory

        factory = get_session_factory()
        session = factory()

        try:
            position = Position(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.H1,
                side="LONG",
                size=Decimal("0"),  # Invalid: zero size
                entry_price=Decimal("50000.00"),
                leverage=10,
                status="OPEN",
                opened_at=datetime.now(timezone.utc),
            )

            session.add(position)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()

    async def test_position_with_trades(self, db_session):
        """Test position with related trades."""
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            position = Position(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.H1,
                side="LONG",
                size=Decimal("0.5"),
                entry_price=Decimal("50000.00"),
                leverage=10,
                status="OPEN",
                opened_at=datetime.now(timezone.utc),
            )

            session.add(position)
            await session.flush()  # Get position.id

            # Add trades to position
            trade = Trade(
                symbol="BTCUSDT",
                strategy="test_strategy",
                timeframe=TimeFrame.H1,
                entry_time=datetime.now(timezone.utc),
                entry_price=Decimal("50000"),
                quantity=Decimal("0.5"),
                leverage=10,
                side="LONG",
                status="OPEN",
                position_id=position.id,
            )

            session.add(trade)
            await session.commit()

            # Query with eager loading to load relationships
            result = await session.execute(
                select(Position)
                .where(Position.id == position.id)
                .options(selectinload(Position.trades))
            )
            loaded_position = result.scalar_one()

            # Verify relationship
            assert len(loaded_position.trades) == 1
            assert loaded_position.trades[0].symbol == "BTCUSDT"


@pytest.mark.unit
class TestStatisticsModel:
    """Test Statistics model CRUD operations and constraints."""

    async def test_create_statistics(self, db_session):
        """Test creating statistics record."""
        async with get_session() as session:
            stats = Statistics(
                strategy="test_strategy",
                period_type="DAILY",
                period_start=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0),
                period_end=datetime.now(timezone.utc).replace(hour=23, minute=59, second=59),
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                total_pnl=Decimal("5000.00"),
                gross_profit=Decimal("8000.00"),
                gross_loss=Decimal("-3000.00"),
            )

            session.add(stats)
            await session.commit()

            assert stats.id is not None
            assert stats.total_trades == 100

    async def test_statistics_unique_constraint(self, db_session):
        """Test that duplicate period statistics are prevented."""
        from src.database.engine import get_session_factory

        period_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)

        # Create first statistics record
        async with get_session() as session:
            stats1 = Statistics(
                strategy="test_strategy",
                period_type="DAILY",
                period_start=period_start,
                period_end=datetime.now(timezone.utc),
                total_trades=100,
            )
            session.add(stats1)
            await session.commit()

        # Try to create duplicate - use manual session management
        factory = get_session_factory()
        session = factory()

        try:
            stats2 = Statistics(
                strategy="test_strategy",
                period_type="DAILY",
                period_start=period_start,  # Same period
                period_end=datetime.now(timezone.utc),
                total_trades=200,
            )
            session.add(stats2)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()


@pytest.mark.unit
class TestBacktestResultModel:
    """Test BacktestResult model CRUD operations and constraints."""

    async def test_create_backtest_result(self, db_session):
        """Test creating backtest result record."""
        async with get_session() as session:
            backtest = BacktestResult(
                name="Test Backtest 1",
                strategy="test_strategy",
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                initial_capital=Decimal("10000.00"),
                final_capital=Decimal("15000.00"),
                total_return=50.0,
                total_pnl=Decimal("5000.00"),
                total_trades=250,
                winning_trades=150,
                losing_trades=100,
                configuration='{"param1": 10, "param2": 20}',
            )

            session.add(backtest)
            await session.commit()

            assert backtest.id is not None
            assert backtest.total_return == 50.0

    async def test_backtest_capital_constraint(self, db_session):
        """Test that initial capital must be positive."""
        from src.database.engine import get_session_factory

        factory = get_session_factory()
        session = factory()

        try:
            backtest = BacktestResult(
                name="Invalid Backtest",
                strategy="test_strategy",
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end_date=datetime(2024, 12, 31, tzinfo=timezone.utc),
                initial_capital=Decimal("-1000.00"),  # Invalid: negative capital
                final_capital=Decimal("0.00"),
                total_return=0.0,
                total_pnl=Decimal("0.00"),
                configuration="{}",
            )

            session.add(backtest)

            with pytest.raises(IntegrityError):
                await session.commit()
        finally:
            await session.close()


@pytest.mark.integration
class TestDatabasePerformance:
    """Test database performance with bulk operations."""

    async def test_bulk_insert_trades(self, db_session):
        """Test inserting 1000 trade records."""
        import time

        start_time = time.time()

        async with get_session() as session:
            trades = []
            for i in range(1000):
                trade = Trade(
                    symbol="BTCUSDT",
                    strategy="test_strategy",
                    timeframe=TimeFrame.M15,
                    entry_time=datetime.now(timezone.utc),
                    entry_price=Decimal("50000.00") + Decimal(i),
                    quantity=Decimal("0.1"),
                    leverage=10,
                    side="LONG",
                    status="CLOSED",
                    exit_time=datetime.now(timezone.utc),
                    exit_price=Decimal("50100.00") + Decimal(i),
                    pnl=Decimal("10.00"),
                )
                trades.append(trade)

            session.add_all(trades)
            await session.commit()

        elapsed_time = time.time() - start_time

        # Verify all trades inserted
        async with get_session() as session:
            result = await session.execute(select(Trade))
            all_trades = result.scalars().all()
            assert len(all_trades) == 1000

        # Performance check: should complete in reasonable time
        assert elapsed_time < 10.0, f"Bulk insert took too long: {elapsed_time:.2f}s"

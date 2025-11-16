"""
Unit tests for BaseDAO generic CRUD operations.

Tests the base functionality that all DAO classes inherit.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from src.core.constants import TimeFrame


@pytest.mark.asyncio
class TestBaseDAO:
    """Test suite for BaseDAO generic operations."""

    async def test_create(self, session, trade_dao):
        """Test creating a new record."""
        trade = await trade_dao.create(
            symbol="ETHUSDT",
            strategy="RSI",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("3000.00"),
            quantity=Decimal("1.0"),
            leverage=1,
            side="LONG",
            status="OPEN",
        )

        assert trade.id is not None
        assert trade.symbol == "ETHUSDT"
        assert trade.strategy == "RSI"
        assert trade.status == "OPEN"

    async def test_get_by_id(self, session, trade_dao, sample_trade):
        """Test retrieving a record by ID."""
        trade = await trade_dao.get_by_id(sample_trade.id)

        assert trade is not None
        assert trade.id == sample_trade.id
        assert trade.symbol == sample_trade.symbol

    async def test_get_by_id_not_found(self, session, trade_dao):
        """Test retrieving non-existent record returns None."""
        trade = await trade_dao.get_by_id(99999)
        assert trade is None

    async def test_get_all(self, session, trade_dao):
        """Test retrieving all records."""
        # Create multiple trades
        for i in range(3):
            await trade_dao.create(
                symbol=f"BTC{i}USDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow(),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="OPEN",
            )

        trades = await trade_dao.get_all()
        assert len(trades) >= 3

    async def test_get_all_with_limit(self, session, trade_dao):
        """Test retrieving records with pagination."""
        # Create multiple trades
        for i in range(5):
            await trade_dao.create(
                symbol=f"BTC{i}USDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow(),
                entry_price=Decimal("50000.00"),
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="OPEN",
            )

        trades = await trade_dao.get_all(limit=3)
        assert len(trades) == 3

    async def test_get_all_with_ordering(self, session, trade_dao):
        """Test retrieving records with ordering."""
        # Create trades with different prices
        await trade_dao.create(
            symbol="BTC1USDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="LONG",
            status="OPEN",
        )
        await trade_dao.create(
            symbol="BTC2USDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("60000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="LONG",
            status="OPEN",
        )

        # Ascending order
        trades = await trade_dao.get_all(order_by="entry_price")
        assert trades[0].entry_price < trades[1].entry_price

        # Descending order
        trades = await trade_dao.get_all(order_by="-entry_price")
        assert trades[0].entry_price > trades[1].entry_price

    async def test_get_by_filter(self, session, trade_dao):
        """Test retrieving records with filters."""
        # Create trades with different strategies
        await trade_dao.create(
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
        await trade_dao.create(
            symbol="BTCUSDT",
            strategy="RSI",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="LONG",
            status="OPEN",
        )

        trades = await trade_dao.get_by_filter({"strategy": "MACD"})
        assert all(t.strategy == "MACD" for t in trades)

    async def test_update(self, session, trade_dao, sample_trade):
        """Test updating a record."""
        updated = await trade_dao.update(
            sample_trade.id,
            status="CLOSED",
            exit_price=Decimal("55000.00"),
        )

        assert updated is not None
        assert updated.status == "CLOSED"
        assert updated.exit_price == Decimal("55000.00")

    async def test_update_not_found(self, session, trade_dao):
        """Test updating non-existent record returns None."""
        result = await trade_dao.update(99999, status="CLOSED")
        assert result is None

    async def test_delete(self, session, trade_dao, sample_trade):
        """Test deleting a record."""
        deleted = await trade_dao.delete(sample_trade.id)
        assert deleted is True

        # Verify deletion
        trade = await trade_dao.get_by_id(sample_trade.id)
        assert trade is None

    async def test_delete_not_found(self, session, trade_dao):
        """Test deleting non-existent record returns False."""
        deleted = await trade_dao.delete(99999)
        assert deleted is False

    async def test_count(self, session, trade_dao):
        """Test counting records."""
        # Create multiple trades
        for i in range(3):
            await trade_dao.create(
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

        count = await trade_dao.count()
        assert count >= 3

    async def test_count_with_filter(self, session, trade_dao):
        """Test counting records with filter."""
        # Create trades with different statuses
        await trade_dao.create(
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
        await trade_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="LONG",
            status="CLOSED",
        )

        open_count = await trade_dao.count({"status": "OPEN"})
        assert open_count >= 1

    async def test_exists(self, session, trade_dao, sample_trade):
        """Test checking record existence."""
        exists = await trade_dao.exists(sample_trade.id)
        assert exists is True

        not_exists = await trade_dao.exists(99999)
        assert not_exists is False

    async def test_bulk_create(self, session, trade_dao):
        """Test bulk creating records."""
        items = [
            {
                "symbol": f"BTC{i}USDT",
                "strategy": "MACD",
                "timeframe": TimeFrame.H1,
                "entry_time": datetime.utcnow(),
                "entry_price": Decimal("50000.00"),
                "quantity": Decimal("0.1"),
                "leverage": 1,
                "side": "LONG",
                "status": "OPEN",
            }
            for i in range(5)
        ]

        trades = await trade_dao.bulk_create(items)
        assert len(trades) == 5
        assert all(t.id is not None for t in trades)

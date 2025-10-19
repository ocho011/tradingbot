"""
Unit tests for PositionDAO specialized operations.

Tests position management, unrealized P&L updates, and risk tracking.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from src.core.constants import TimeFrame


@pytest.mark.asyncio
class TestPositionDAO:
    """Test suite for PositionDAO operations."""

    async def test_get_current_positions(self, session, position_dao):
        """Test getting all currently open positions."""
        await position_dao.create(
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

        positions = await position_dao.get_current_positions()
        assert len(positions) >= 1
        assert all(p.status == "OPEN" for p in positions)

    async def test_get_current_positions_with_filters(self, session, position_dao):
        """Test getting positions with strategy and symbol filters."""
        await position_dao.create(
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
        await position_dao.create(
            symbol="ETHUSDT",
            strategy="RSI",
            timeframe=TimeFrame.H1,
            side="LONG",
            size=Decimal("1.0"),
            entry_price=Decimal("3000.00"),
            leverage=1,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )

        macd_positions = await position_dao.get_current_positions(strategy="MACD")
        assert all(p.strategy == "MACD" for p in macd_positions)

        btc_positions = await position_dao.get_current_positions(symbol="BTCUSDT")
        assert all(p.symbol == "BTCUSDT" for p in btc_positions)

    async def test_get_position_by_symbol_strategy(self, session, position_dao):
        """Test getting specific position by symbol and strategy."""
        await position_dao.create(
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

        position = await position_dao.get_position_by_symbol_strategy(
            "BTCUSDT",
            "MACD"
        )
        assert position is not None
        assert position.symbol == "BTCUSDT"
        assert position.strategy == "MACD"

    async def test_update_unrealized_pnl_long(self, session, position_dao):
        """Test updating unrealized P&L for LONG position."""
        position = await position_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            side="LONG",
            size=Decimal("0.1"),
            entry_price=Decimal("50000.00"),
            leverage=2,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )

        current_price = Decimal("55000.00")
        updated = await position_dao.update_unrealized_pnl(position.id, current_price)

        assert updated.current_price == current_price
        # Unrealized P&L = (55000 - 50000) * 0.1 * 2 = 1000
        assert updated.unrealized_pnl == Decimal("1000.00")
        assert updated.unrealized_pnl_percent == 10.0

    async def test_update_unrealized_pnl_short(self, session, position_dao):
        """Test updating unrealized P&L for SHORT position."""
        position = await position_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            side="SHORT",
            size=Decimal("0.1"),
            entry_price=Decimal("50000.00"),
            leverage=1,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )

        current_price = Decimal("48000.00")
        updated = await position_dao.update_unrealized_pnl(position.id, current_price)

        # Unrealized P&L for SHORT = -(48000 - 50000) * 0.1 * 1 = 200
        assert updated.unrealized_pnl == Decimal("200.00")
        assert updated.unrealized_pnl_percent == 4.0

    async def test_close_position(self, session, position_dao, sample_position):
        """Test closing a position."""
        closed_at = datetime.utcnow()
        realized_pnl = Decimal("500.00")

        closed = await position_dao.close_position(
            sample_position.id,
            closed_at,
            realized_pnl
        )

        assert closed.status == "CLOSED"
        assert closed.closed_at == closed_at
        assert closed.realized_pnl == realized_pnl
        assert closed.unrealized_pnl == Decimal("0")

    async def test_get_positions_by_date_range(self, session, position_dao):
        """Test getting positions within date range."""
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now

        await position_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            side="LONG",
            size=Decimal("0.1"),
            entry_price=Decimal("50000.00"),
            leverage=1,
            status="OPEN",
            opened_at=now - timedelta(days=3),
        )

        positions = await position_dao.get_positions_by_date_range(start, end)
        assert len(positions) >= 1
        assert all(start <= p.opened_at <= end for p in positions)

    async def test_calculate_total_exposure(self, session, position_dao):
        """Test calculating total exposure for open positions."""
        # Create long position
        await position_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            side="LONG",
            size=Decimal("0.1"),
            entry_price=Decimal("50000.00"),
            leverage=2,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )

        # Create short position
        await position_dao.create(
            symbol="ETHUSDT",
            strategy="RSI",
            timeframe=TimeFrame.H1,
            side="SHORT",
            size=Decimal("1.0"),
            entry_price=Decimal("3000.00"),
            leverage=1,
            status="OPEN",
            opened_at=datetime.utcnow(),
        )

        exposure = await position_dao.calculate_total_exposure()

        # Long exposure = 0.1 * 50000 * 2 = 10000
        assert exposure['total_long_exposure'] == Decimal("10000.00")
        # Short exposure = 1.0 * 3000 * 1 = 3000
        assert exposure['total_short_exposure'] == Decimal("3000.00")
        # Net = 10000 - 3000 = 7000
        assert exposure['net_exposure'] == Decimal("7000.00")
        # Total = 10000 + 3000 = 13000
        assert exposure['total_absolute_exposure'] == Decimal("13000.00")

    async def test_get_positions_at_risk(self, session, position_dao):
        """Test getting positions with losses exceeding threshold."""
        # Create position with loss
        position = await position_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            side="LONG",
            size=Decimal("0.1"),
            entry_price=Decimal("50000.00"),
            leverage=1,
            status="OPEN",
            opened_at=datetime.utcnow(),
            unrealized_pnl=Decimal("-600.00"),
            unrealized_pnl_percent=-12.0,
        )

        at_risk = await position_dao.get_positions_at_risk(risk_threshold=-10.0)
        assert len(at_risk) >= 1
        assert all(p.unrealized_pnl_percent <= -10.0 for p in at_risk)

    async def test_update_stop_loss_take_profit(self, session, position_dao, sample_position):
        """Test updating stop loss and take profit levels."""
        stop_loss = Decimal("48000.00")
        take_profit = Decimal("60000.00")

        updated = await position_dao.update_stop_loss_take_profit(
            sample_position.id,
            stop_loss=stop_loss,
            take_profit=take_profit
        )

        assert updated.stop_loss == stop_loss
        assert updated.take_profit == take_profit

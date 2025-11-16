"""
Unit tests for TradeDAO specialized operations.

Tests trade-specific queries, P&L calculations, and strategy analysis.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.core.constants import TimeFrame


@pytest.mark.asyncio
class TestTradeDAO:
    """Test suite for TradeDAO operations."""

    async def test_get_trades_by_strategy(self, session, trade_dao):
        """Test getting trades filtered by strategy."""
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

        trades = await trade_dao.get_trades_by_strategy("MACD")
        assert len(trades) >= 1
        assert all(t.strategy == "MACD" for t in trades)

    async def test_get_trades_by_strategy_with_filters(self, session, trade_dao):
        """Test getting trades with multiple filters."""
        # Create trades
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
            symbol="ETHUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow(),
            entry_price=Decimal("3000.00"),
            quantity=Decimal("1.0"),
            leverage=1,
            side="LONG",
            status="CLOSED",
        )

        trades = await trade_dao.get_trades_by_strategy("MACD", status="OPEN", symbol="BTCUSDT")
        assert len(trades) >= 1
        assert all(t.status == "OPEN" and t.symbol == "BTCUSDT" for t in trades)

    async def test_get_open_trades(self, session, trade_dao):
        """Test getting all open trades."""
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

        open_trades = await trade_dao.get_open_trades()
        assert len(open_trades) >= 1
        assert all(t.status == "OPEN" for t in open_trades)

    async def test_get_closed_trades_by_date_range(self, session, trade_dao):
        """Test getting closed trades within date range."""
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now

        # Create closed trade
        await trade_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=now - timedelta(hours=2),
            entry_price=Decimal("50000.00"),
            exit_time=now - timedelta(hours=1),
            exit_price=Decimal("55000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="LONG",
            status="CLOSED",
            pnl=Decimal("500.00"),
        )

        trades = await trade_dao.get_closed_trades_by_date_range(start, end)
        assert len(trades) >= 1
        assert all(t.status == "CLOSED" for t in trades)
        assert all(start <= t.exit_time <= end for t in trades if t.exit_time)

    async def test_calculate_strategy_pnl(self, session, trade_dao):
        """Test calculating P&L statistics for a strategy."""
        # Create winning trades
        for i in range(3):
            await trade_dao.create(
                symbol="BTCUSDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow() - timedelta(hours=2),
                entry_price=Decimal("50000.00"),
                exit_time=datetime.utcnow() - timedelta(hours=1),
                exit_price=Decimal("55000.00"),
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="CLOSED",
                pnl=Decimal("500.00"),
                fees=Decimal("10.00"),
            )

        # Create losing trades
        for i in range(2):
            await trade_dao.create(
                symbol="BTCUSDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow() - timedelta(hours=2),
                entry_price=Decimal("50000.00"),
                exit_time=datetime.utcnow() - timedelta(hours=1),
                exit_price=Decimal("48000.00"),
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="CLOSED",
                pnl=Decimal("-200.00"),
                fees=Decimal("10.00"),
            )

        stats = await trade_dao.calculate_strategy_pnl("MACD")

        assert stats["total_trades"] == 5
        assert stats["winning_trades"] == 3
        assert stats["losing_trades"] == 2
        assert stats["win_rate"] == 60.0
        assert stats["total_pnl"] == Decimal("1100.00")  # 3*500 + 2*(-200)
        assert stats["total_fees"] == Decimal("50.00")  # 5*10

    async def test_calculate_strategy_pnl_empty(self, session, trade_dao):
        """Test calculating P&L for strategy with no trades."""
        stats = await trade_dao.calculate_strategy_pnl("NONEXISTENT")

        assert stats["total_trades"] == 0
        assert stats["total_pnl"] == Decimal("0")
        assert stats["win_rate"] == 0.0

    async def test_get_best_trades(self, session, trade_dao):
        """Test getting best performing trades."""
        # Create trades with different P&L
        pnls = [Decimal("100"), Decimal("500"), Decimal("300"), Decimal("200")]
        for pnl in pnls:
            await trade_dao.create(
                symbol="BTCUSDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow() - timedelta(hours=2),
                entry_price=Decimal("50000.00"),
                exit_time=datetime.utcnow() - timedelta(hours=1),
                exit_price=Decimal("50000.00") + pnl * 100,
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="CLOSED",
                pnl=pnl,
            )

        best = await trade_dao.get_best_trades(limit=2)
        assert len(best) == 2
        assert best[0].pnl >= best[1].pnl
        assert best[0].pnl == Decimal("500")

    async def test_get_worst_trades(self, session, trade_dao):
        """Test getting worst performing trades."""
        # Create trades with different P&L
        pnls = [Decimal("-100"), Decimal("-500"), Decimal("-300"), Decimal("200")]
        for pnl in pnls:
            await trade_dao.create(
                symbol="BTCUSDT",
                strategy="MACD",
                timeframe=TimeFrame.H1,
                entry_time=datetime.utcnow() - timedelta(hours=2),
                entry_price=Decimal("50000.00"),
                exit_time=datetime.utcnow() - timedelta(hours=1),
                exit_price=Decimal("50000.00") + pnl * 100,
                quantity=Decimal("0.1"),
                leverage=1,
                side="LONG",
                status="CLOSED",
                pnl=pnl,
            )

        worst = await trade_dao.get_worst_trades(limit=2)
        assert len(worst) == 2
        assert worst[0].pnl <= worst[1].pnl
        assert worst[0].pnl == Decimal("-500")

    async def test_close_trade_long(self, session, trade_dao):
        """Test closing a LONG trade with P&L calculation."""
        # Create open trade
        trade = await trade_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow() - timedelta(hours=1),
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.1"),
            leverage=2,
            side="LONG",
            status="OPEN",
        )

        exit_time = datetime.utcnow()
        exit_price = Decimal("55000.00")

        closed = await trade_dao.close_trade(
            trade.id, exit_price, exit_time, "TP", fees=Decimal("25.00")
        )

        assert closed.status == "CLOSED"
        assert closed.exit_price == exit_price
        assert closed.exit_reason == "TP"
        # P&L = (55000 - 50000) * 0.1 * 2 - 25 = 1000 - 25 = 975
        assert closed.pnl == Decimal("975.00")
        assert closed.fees == Decimal("25.00")

    async def test_close_trade_short(self, session, trade_dao):
        """Test closing a SHORT trade with P&L calculation."""
        # Create open short trade
        trade = await trade_dao.create(
            symbol="BTCUSDT",
            strategy="MACD",
            timeframe=TimeFrame.H1,
            entry_time=datetime.utcnow() - timedelta(hours=1),
            entry_price=Decimal("50000.00"),
            quantity=Decimal("0.1"),
            leverage=1,
            side="SHORT",
            status="OPEN",
        )

        exit_time = datetime.utcnow()
        exit_price = Decimal("48000.00")

        closed = await trade_dao.close_trade(
            trade.id, exit_price, exit_time, "TP", fees=Decimal("10.00")
        )

        assert closed.status == "CLOSED"
        # P&L for SHORT = -(48000 - 50000) * 0.1 * 1 - 10 = 200 - 10 = 190
        assert closed.pnl == Decimal("190.00")

    async def test_close_trade_not_found(self, session, trade_dao):
        """Test closing non-existent trade returns None."""
        result = await trade_dao.close_trade(99999, Decimal("55000.00"), datetime.utcnow(), "TP")
        assert result is None

    async def test_close_trade_already_closed(self, session, trade_dao, sample_closed_trade):
        """Test closing already closed trade doesn't modify it."""
        result = await trade_dao.close_trade(
            sample_closed_trade.id, Decimal("60000.00"), datetime.utcnow(), "MANUAL"
        )

        assert result.status == "CLOSED"
        # Should keep original values
        assert result.exit_price == sample_closed_trade.exit_price

"""
Unit tests for StatisticsDAO specialized operations.

Tests statistics aggregation, performance analysis, and trend tracking.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from src.database.models import Statistics


@pytest.mark.asyncio
class TestStatisticsDAO:
    """Test suite for StatisticsDAO operations."""

    async def test_get_daily_stats(self, session, statistics_dao):
        """Test getting daily statistics for a strategy."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)

        # Create daily stats
        for i in range(3):
            await statistics_dao.create(
                strategy="MACD",
                period_type="DAILY",
                period_start=start + timedelta(days=i),
                period_end=start + timedelta(days=i, hours=23, minutes=59),
                total_trades=10 + i,
                winning_trades=6,
                losing_trades=4,
                win_rate=60.0,
                total_pnl=Decimal("1000.00") * (i + 1),
            )

        stats = await statistics_dao.get_daily_stats("MACD", start, end)
        assert len(stats) == 3
        assert all(s.period_type == "DAILY" for s in stats)

    async def test_get_monthly_stats(self, session, statistics_dao):
        """Test getting monthly statistics for a strategy."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)

        # Create monthly stats
        for i in range(3):
            await statistics_dao.create(
                strategy="MACD",
                period_type="MONTHLY",
                period_start=datetime(2024, i + 1, 1),
                period_end=datetime(2024, i + 1, 28),
                total_trades=100 + i * 10,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                total_pnl=Decimal("5000.00") * (i + 1),
            )

        stats = await statistics_dao.get_monthly_stats("MACD", start, end)
        assert len(stats) >= 3
        assert all(s.period_type == "MONTHLY" for s in stats)

    async def test_get_latest_stats(self, session, statistics_dao):
        """Test getting latest statistics."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Create multiple stats
        for i in range(5):
            await statistics_dao.create(
                strategy="MACD",
                period_type="DAILY",
                period_start=start - timedelta(days=i),
                period_end=start - timedelta(days=i) + timedelta(hours=23),
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
                win_rate=60.0,
                total_pnl=Decimal("1000.00"),
            )

        latest = await statistics_dao.get_latest_stats("MACD", limit=3)
        assert len(latest) == 3
        # Should be ordered by most recent first
        assert latest[0].period_start >= latest[1].period_start

    async def test_get_strategy_comparison(self, session, statistics_dao):
        """Test comparing performance across multiple strategies."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        strategies = ["MACD", "RSI", "BBands"]
        for strategy in strategies:
            for i in range(3):
                await statistics_dao.create(
                    strategy=strategy,
                    period_type="DAILY",
                    period_start=start - timedelta(days=i),
                    period_end=start - timedelta(days=i) + timedelta(hours=23),
                    total_trades=10 * (strategies.index(strategy) + 1),
                    winning_trades=6,
                    losing_trades=4,
                    win_rate=60.0,
                    total_pnl=Decimal("1000.00") * (strategies.index(strategy) + 1),
                    sharpe_ratio=2.0 + strategies.index(strategy) * 0.5,
                )

        comparison = await statistics_dao.get_strategy_comparison(
            strategies,
            start_date=start - timedelta(days=7)
        )

        assert len(comparison) == 3
        assert "MACD" in comparison
        assert comparison["MACD"]["total_trades"] >= 30
        assert comparison["MACD"]["periods_count"] == 3

    async def test_get_best_performing_period(self, session, statistics_dao):
        """Test getting best performing periods."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        pnls = [Decimal("1000"), Decimal("2000"), Decimal("500"), Decimal("1500")]
        for i, pnl in enumerate(pnls):
            await statistics_dao.create(
                strategy="MACD",
                period_type="DAILY",
                period_start=start - timedelta(days=i),
                period_end=start - timedelta(days=i) + timedelta(hours=23),
                total_trades=10,
                winning_trades=6,
                losing_trades=4,
                win_rate=60.0,
                total_pnl=pnl,
            )

        best = await statistics_dao.get_best_performing_period(
            "MACD",
            metric="total_pnl",
            limit=2
        )

        assert len(best) == 2
        assert best[0].total_pnl >= best[1].total_pnl
        assert best[0].total_pnl == Decimal("2000")

    async def test_get_performance_trend(self, session, statistics_dao):
        """Test analyzing performance trend."""
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Create improving trend (better performance in recent periods)
        for i in range(10):
            pnl = Decimal("500") if i < 5 else Decimal("1500")  # 2nd half better
            win_rate = 50.0 if i < 5 else 70.0

            await statistics_dao.create(
                strategy="MACD",
                period_type="DAILY",
                period_start=start - timedelta(days=9 - i),
                period_end=start - timedelta(days=9 - i) + timedelta(hours=23),
                total_trades=10,
                winning_trades=5 if i < 5 else 7,
                losing_trades=5 if i < 5 else 3,
                win_rate=win_rate,
                total_pnl=pnl,
            )

        trend = await statistics_dao.get_performance_trend("MACD", lookback_periods=10)

        assert len(trend['periods']) == 10
        assert trend['pnl_trend'] in ['improving', 'declining', 'stable']
        assert trend['win_rate_trend'] in ['improving', 'declining', 'stable']
        assert trend['total_pnl'] > 0

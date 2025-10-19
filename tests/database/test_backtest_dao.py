"""
Unit tests for BacktestResultDAO specialized operations.

Tests backtest result storage, strategy comparisons, and optimization analysis.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
import json

from src.core.constants import TimeFrame


@pytest.mark.asyncio
class TestBacktestResultDAO:
    """Test suite for BacktestResultDAO operations."""

    async def test_get_results_by_strategy(self, session, backtest_dao):
        """Test getting backtest results for specific strategy."""
        # Create backtest results
        for i in range(3):
            await backtest_dao.create(
                name=f"MACD Test {i+1}",
                strategy="MACD",
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                initial_capital=Decimal("10000"),
                final_capital=Decimal("15000"),
                total_return=50.0,
                total_pnl=Decimal("5000"),
                configuration='{"param": 1}',
            )

        results = await backtest_dao.get_results_by_strategy("MACD")
        assert len(results) >= 3
        assert all(r.strategy == "MACD" for r in results)

    async def test_get_results_with_symbol_filter(self, session, backtest_dao):
        """Test filtering backtest results by symbol."""
        await backtest_dao.create(
            name="MACD BTC Test",
            strategy="MACD",
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            win_rate=60.0,
            initial_capital=Decimal("10000"),
            final_capital=Decimal("15000"),
            total_return=50.0,
            total_pnl=Decimal("5000"),
            configuration='{}',
        )

        results = await backtest_dao.get_results_by_strategy("MACD", symbol="BTCUSDT")
        assert all(r.symbol == "BTCUSDT" for r in results)

    async def test_get_best_results(self, session, backtest_dao):
        """Test getting best performing backtest results."""
        # Create results with different Sharpe ratios
        sharpe_ratios = [1.5, 3.0, 2.0, 2.5]
        for i, sharpe in enumerate(sharpe_ratios):
            await backtest_dao.create(
                name=f"Test {i+1}",
                strategy="MACD",
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                initial_capital=Decimal("10000"),
                final_capital=Decimal("15000"),
                total_return=50.0,
                total_pnl=Decimal("5000"),
                sharpe_ratio=sharpe,
                configuration='{}',
            )

        best = await backtest_dao.get_best_results(metric="sharpe_ratio", limit=2)
        assert len(best) == 2
        assert best[0].sharpe_ratio >= best[1].sharpe_ratio
        assert best[0].sharpe_ratio == 3.0

    async def test_compare_strategies(self, session, backtest_dao):
        """Test comparing multiple strategies."""
        strategies = ["MACD", "RSI", "BBands"]

        for strategy in strategies:
            for i in range(3):
                await backtest_dao.create(
                    name=f"{strategy} Test {i+1}",
                    strategy=strategy,
                    symbol="BTCUSDT",
                    timeframe=TimeFrame.H1,
                    start_date=datetime(2024, 1, 1),
                    end_date=datetime(2024, 12, 31),
                    total_trades=100,
                    winning_trades=60,
                    losing_trades=40,
                    win_rate=60.0,
                    initial_capital=Decimal("10000"),
                    final_capital=Decimal("15000"),
                    total_return=50.0 * (strategies.index(strategy) + 1),
                    total_pnl=Decimal("5000") * (strategies.index(strategy) + 1),
                    sharpe_ratio=2.0 + strategies.index(strategy) * 0.5,
                    configuration='{}',
                )

        comparison = await backtest_dao.compare_strategies(strategies)

        assert len(comparison) == 3
        assert "MACD" in comparison
        assert comparison["MACD"]["total_backtests"] == 3
        assert comparison["BBands"]["avg_return"] > comparison["MACD"]["avg_return"]

    async def test_get_results_by_date_range(self, session, backtest_dao):
        """Test getting backtest results within date range."""
        await backtest_dao.create(
            name="Q1 Test",
            strategy="MACD",
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 31),
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            win_rate=60.0,
            initial_capital=Decimal("10000"),
            final_capital=Decimal("15000"),
            total_return=50.0,
            total_pnl=Decimal("5000"),
            configuration='{}',
        )

        results = await backtest_dao.get_results_by_date_range(
            datetime(2024, 1, 1),
            datetime(2024, 6, 30)
        )
        assert len(results) >= 1

    async def test_create_with_config(self, session, backtest_dao):
        """Test creating backtest result with configuration dictionary."""
        config = {
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "stop_loss": 2.0,
        }

        result = await backtest_dao.create_with_config(
            config=config,
            name="MACD Config Test",
            strategy="MACD",
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            win_rate=60.0,
            initial_capital=Decimal("10000"),
            final_capital=Decimal("15000"),
            total_return=50.0,
            total_pnl=Decimal("5000"),
        )

        assert result.id is not None
        # Verify configuration is stored as JSON
        parsed_config = json.loads(result.configuration)
        assert parsed_config["macd_fast"] == 12
        assert parsed_config["macd_slow"] == 26

    async def test_get_configuration(self, session, backtest_dao, sample_backtest):
        """Test retrieving parsed configuration."""
        config = await backtest_dao.get_configuration(sample_backtest.id)

        assert config is not None
        assert "macd_fast" in config
        assert config["macd_fast"] == 12

    async def test_get_optimization_history(self, session, backtest_dao):
        """Test getting optimization history for strategy."""
        configs = [
            {"macd_fast": 10, "macd_slow": 24},
            {"macd_fast": 12, "macd_slow": 26},
            {"macd_fast": 14, "macd_slow": 28},
        ]

        sharpe_ratios = [2.0, 2.5, 1.8]

        for i, (config, sharpe) in enumerate(zip(configs, sharpe_ratios)):
            await backtest_dao.create_with_config(
                config=config,
                name=f"MACD Optimization {i+1}",
                strategy="MACD",
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                initial_capital=Decimal("10000"),
                final_capital=Decimal("15000"),
                total_return=50.0,
                total_pnl=Decimal("5000"),
                sharpe_ratio=sharpe,
            )

        history = await backtest_dao.get_optimization_history(
            "MACD",
            "BTCUSDT",
            metric="sharpe_ratio",
            limit=10
        )

        assert len(history) >= 3
        assert "configuration" in history[0]
        assert "sharpe_ratio" in history[0]
        # Should be ordered by Sharpe ratio (best first)
        assert history[0]["sharpe_ratio"] >= history[1]["sharpe_ratio"]

    async def test_get_statistics_summary(self, session, backtest_dao):
        """Test getting aggregate statistics."""
        strategies = ["MACD", "RSI"]

        for strategy in strategies:
            await backtest_dao.create(
                name=f"{strategy} Test",
                strategy=strategy,
                symbol="BTCUSDT",
                timeframe=TimeFrame.H1,
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 12, 31),
                total_trades=100,
                winning_trades=60,
                losing_trades=40,
                win_rate=60.0,
                initial_capital=Decimal("10000"),
                final_capital=Decimal("15000"),
                total_return=50.0 if strategy == "MACD" else 30.0,
                total_pnl=Decimal("5000"),
                sharpe_ratio=2.5,
                configuration='{}',
            )

        summary = await backtest_dao.get_statistics_summary()

        assert summary["total_backtests"] >= 2
        assert summary["strategies_tested"] >= 2
        assert "avg_return" in summary
        assert "best_return" in summary
        assert summary["best_return"] == 50.0

    async def test_get_statistics_summary_with_filter(self, session, backtest_dao):
        """Test getting statistics summary with strategy filter."""
        await backtest_dao.create(
            name="MACD Test",
            strategy="MACD",
            symbol="BTCUSDT",
            timeframe=TimeFrame.H1,
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            win_rate=60.0,
            initial_capital=Decimal("10000"),
            final_capital=Decimal("15000"),
            total_return=50.0,
            total_pnl=Decimal("5000"),
            configuration='{}',
        )

        summary = await backtest_dao.get_statistics_summary(strategy="MACD")

        assert summary["strategies_tested"] >= 1
        assert summary["total_backtests"] >= 1

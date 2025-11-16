"""
Statistics Data Access Object for performance statistics operations.

This module provides specialized database operations for Statistics records
including daily/monthly aggregations, performance tracking, and trend analysis.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dao.base import BaseDAO
from src.database.models import Statistics

logger = logging.getLogger(__name__)


class StatisticsDAO(BaseDAO[Statistics]):
    """
    Data Access Object for Statistics model with specialized query methods.

    Provides CRUD operations plus complex queries for performance analysis,
    trend tracking, and statistical aggregations.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize StatisticsDAO with database session.

        Args:
            session: Async database session
        """
        super().__init__(Statistics, session)

    async def get_daily_stats(
        self,
        strategy: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Statistics]:
        """
        Get daily statistics for a strategy within date range.

        Args:
            strategy: Strategy name
            start_date: Start date
            end_date: End date

        Returns:
            List of daily Statistics instances

        Example:
            >>> stats = await stats_dao.get_daily_stats(
            ...     'MACD',
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 31)
            ... )
        """
        try:
            query = (
                select(Statistics)
                .where(
                    and_(
                        Statistics.strategy == strategy,
                        Statistics.period_type == "DAILY",
                        Statistics.period_start >= start_date,
                        Statistics.period_start <= end_date,
                    )
                )
                .order_by(Statistics.period_start.asc())
            )

            result = await self.session.execute(query)
            stats = result.scalars().all()
            logger.debug(
                f"Retrieved {len(stats)} daily stats for strategy '{strategy}' "
                f"between {start_date} and {end_date}"
            )
            return list(stats)
        except SQLAlchemyError as e:
            logger.error(f"Error getting daily stats for strategy '{strategy}': {e}")
            raise

    async def get_monthly_stats(
        self,
        strategy: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Statistics]:
        """
        Get monthly statistics for a strategy within date range.

        Args:
            strategy: Strategy name
            start_date: Start date
            end_date: End date

        Returns:
            List of monthly Statistics instances

        Example:
            >>> stats = await stats_dao.get_monthly_stats(
            ...     'MACD',
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 12, 31)
            ... )
        """
        try:
            query = (
                select(Statistics)
                .where(
                    and_(
                        Statistics.strategy == strategy,
                        Statistics.period_type == "MONTHLY",
                        Statistics.period_start >= start_date,
                        Statistics.period_start <= end_date,
                    )
                )
                .order_by(Statistics.period_start.asc())
            )

            result = await self.session.execute(query)
            stats = result.scalars().all()
            logger.debug(
                f"Retrieved {len(stats)} monthly stats for strategy '{strategy}' "
                f"between {start_date} and {end_date}"
            )
            return list(stats)
        except SQLAlchemyError as e:
            logger.error(f"Error getting monthly stats for strategy '{strategy}': {e}")
            raise

    async def get_latest_stats(
        self,
        strategy: str,
        period_type: str = "DAILY",
        limit: int = 30,
    ) -> List[Statistics]:
        """
        Get latest statistics for a strategy.

        Args:
            strategy: Strategy name
            period_type: 'DAILY' or 'MONTHLY'
            limit: Maximum number of records to return

        Returns:
            List of recent Statistics instances

        Example:
            >>> recent = await stats_dao.get_latest_stats('MACD', limit=7)
        """
        try:
            query = (
                select(Statistics)
                .where(
                    and_(
                        Statistics.strategy == strategy,
                        Statistics.period_type == period_type,
                    )
                )
                .order_by(Statistics.period_start.desc())
                .limit(limit)
            )

            result = await self.session.execute(query)
            stats = result.scalars().all()
            logger.debug(
                f"Retrieved {len(stats)} latest {period_type} stats " f"for strategy '{strategy}'"
            )
            return list(stats)
        except SQLAlchemyError as e:
            logger.error(f"Error getting latest stats for strategy '{strategy}': {e}")
            raise

    async def calculate_daily_stats(
        self,
        strategy: str,
        date: datetime,
    ) -> Dict[str, Any]:
        """
        Create or update daily statistics for a strategy on a specific date.

        This method should be called at the end of each trading day to
        aggregate that day's trading performance.

        Args:
            strategy: Strategy name
            date: Date to calculate stats for

        Returns:
            Dictionary with calculated statistics

        Note:
            This is a helper method that would typically integrate with
            TradeDAO to calculate stats from actual trades. Implementation
            would query trades for the day and aggregate metrics.

        Example:
            >>> stats = await stats_dao.calculate_daily_stats('MACD', datetime.now())
        """
        # This is a placeholder that demonstrates the structure
        # In a real implementation, this would:
        # 1. Query all closed trades for the day
        # 2. Calculate all metrics
        # 3. Create or update Statistics record
        logger.info(f"Calculate daily stats called for strategy '{strategy}' on {date}")
        raise NotImplementedError("calculate_daily_stats requires integration with TradeDAO")

    async def get_strategy_comparison(
        self,
        strategies: List[str],
        period_type: str = "DAILY",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare performance metrics across multiple strategies.

        Args:
            strategies: List of strategy names to compare
            period_type: 'DAILY' or 'MONTHLY'
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary mapping strategy names to aggregated metrics

        Example:
            >>> comparison = await stats_dao.get_strategy_comparison(
            ...     ['MACD', 'RSI', 'BBands'],
            ...     start_date=datetime(2024, 1, 1)
            ... )
        """
        try:
            results = {}

            for strategy in strategies:
                query = select(Statistics).where(
                    and_(
                        Statistics.strategy == strategy,
                        Statistics.period_type == period_type,
                    )
                )

                if start_date:
                    query = query.where(Statistics.period_start >= start_date)
                if end_date:
                    query = query.where(Statistics.period_start <= end_date)

                result = await self.session.execute(query)
                stats_list = result.scalars().all()

                if not stats_list:
                    results[strategy] = None
                    continue

                # Aggregate metrics
                total_trades = sum(s.total_trades for s in stats_list)
                total_pnl = sum(s.total_pnl for s in stats_list)
                winning_trades = sum(s.winning_trades for s in stats_list)

                results[strategy] = {
                    "total_trades": total_trades,
                    "total_pnl": total_pnl,
                    "win_rate": (
                        (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
                    ),
                    "avg_pnl_per_period": (
                        total_pnl / len(stats_list) if stats_list else Decimal("0")
                    ),
                    "periods_count": len(stats_list),
                    "best_sharpe": max(
                        (s.sharpe_ratio for s in stats_list if s.sharpe_ratio), default=None
                    ),
                    "max_drawdown": min(
                        (s.max_drawdown for s in stats_list if s.max_drawdown), default=None
                    ),
                }

            logger.debug(f"Compared {len(strategies)} strategies")
            return results
        except SQLAlchemyError as e:
            logger.error(f"Error comparing strategies: {e}")
            raise

    async def get_best_performing_period(
        self,
        strategy: str,
        period_type: str = "DAILY",
        metric: str = "total_pnl",
        limit: int = 1,
    ) -> List[Statistics]:
        """
        Get best performing periods by a specific metric.

        Args:
            strategy: Strategy name
            period_type: 'DAILY' or 'MONTHLY'
            metric: Metric to sort by (total_pnl, win_rate, sharpe_ratio, etc.)
            limit: Number of periods to return

        Returns:
            List of best performing Statistics instances

        Example:
            >>> best_days = await stats_dao.get_best_performing_period(
            ...     'MACD',
            ...     metric='sharpe_ratio',
            ...     limit=5
            ... )
        """
        try:
            query = select(Statistics).where(
                and_(
                    Statistics.strategy == strategy,
                    Statistics.period_type == period_type,
                )
            )

            # Sort by specified metric
            if hasattr(Statistics, metric):
                column = getattr(Statistics, metric)
                query = query.order_by(column.desc())
            else:
                logger.warning(f"Invalid metric '{metric}', using total_pnl")
                query = query.order_by(Statistics.total_pnl.desc())

            query = query.limit(limit)

            result = await self.session.execute(query)
            stats = result.scalars().all()
            logger.debug(
                f"Retrieved {len(stats)} best performing {period_type} periods "
                f"for strategy '{strategy}' by {metric}"
            )
            return list(stats)
        except SQLAlchemyError as e:
            logger.error(f"Error getting best performing periods: {e}")
            raise

    async def get_performance_trend(
        self,
        strategy: str,
        period_type: str = "DAILY",
        lookback_periods: int = 30,
    ) -> Dict[str, Any]:
        """
        Analyze performance trend over recent periods.

        Args:
            strategy: Strategy name
            period_type: 'DAILY' or 'MONTHLY'
            lookback_periods: Number of recent periods to analyze

        Returns:
            Dictionary with trend analysis:
                - periods: List of period statistics
                - avg_pnl: Average P&L per period
                - pnl_trend: 'improving', 'declining', or 'stable'
                - win_rate_trend: Win rate trend direction
                - total_pnl: Cumulative P&L over period

        Example:
            >>> trend = await stats_dao.get_performance_trend('MACD', lookback_periods=14)
        """
        try:
            stats = await self.get_latest_stats(strategy, period_type, limit=lookback_periods)

            if not stats:
                return {
                    "periods": [],
                    "avg_pnl": Decimal("0"),
                    "pnl_trend": "stable",
                    "win_rate_trend": "stable",
                    "total_pnl": Decimal("0"),
                }

            # Reverse to chronological order
            stats = list(reversed(stats))

            total_pnl = sum(s.total_pnl for s in stats)
            avg_pnl = total_pnl / len(stats)

            # Simple trend analysis (compare first half vs second half)
            mid = len(stats) // 2
            first_half_pnl = sum(s.total_pnl for s in stats[:mid]) / mid if mid > 0 else 0
            second_half_pnl = sum(s.total_pnl for s in stats[mid:]) / (len(stats) - mid)

            pnl_trend = (
                "improving"
                if second_half_pnl > first_half_pnl * Decimal("1.1")
                else "declining" if second_half_pnl < first_half_pnl * Decimal("0.9") else "stable"
            )

            # Win rate trend
            first_half_wr = sum(s.win_rate or 0 for s in stats[:mid]) / mid if mid > 0 else 0
            second_half_wr = sum(s.win_rate or 0 for s in stats[mid:]) / (len(stats) - mid)

            win_rate_trend = (
                "improving"
                if second_half_wr > first_half_wr * 1.05
                else "declining" if second_half_wr < first_half_wr * 0.95 else "stable"
            )

            result = {
                "periods": [
                    {
                        "date": s.period_start,
                        "pnl": s.total_pnl,
                        "win_rate": s.win_rate,
                        "trades": s.total_trades,
                    }
                    for s in stats
                ],
                "avg_pnl": avg_pnl,
                "pnl_trend": pnl_trend,
                "win_rate_trend": win_rate_trend,
                "total_pnl": total_pnl,
            }

            logger.debug(
                f"Analyzed performance trend for strategy '{strategy}': "
                f"PNL {pnl_trend}, Win Rate {win_rate_trend}"
            )
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error analyzing performance trend: {e}")
            raise

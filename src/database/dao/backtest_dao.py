"""
BacktestResult Data Access Object for backtest result operations.

This module provides specialized database operations for BacktestResult records
including strategy comparisons, historical analysis, and performance tracking.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import json
import logging

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from src.database.models import BacktestResult
from src.database.dao.base import BaseDAO


logger = logging.getLogger(__name__)


class BacktestResultDAO(BaseDAO[BacktestResult]):
    """
    Data Access Object for BacktestResult model with specialized query methods.

    Provides CRUD operations plus complex queries for backtest analysis,
    strategy optimization, and performance comparisons.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize BacktestResultDAO with database session.

        Args:
            session: Async database session
        """
        super().__init__(BacktestResult, session)

    async def get_results_by_strategy(
        self,
        strategy: str,
        symbol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[BacktestResult]:
        """
        Get backtest results for a specific strategy.

        Args:
            strategy: Strategy name
            symbol: Optional symbol filter
            limit: Maximum number of results to return

        Returns:
            List of BacktestResult instances

        Example:
            >>> results = await backtest_dao.get_results_by_strategy(
            ...     'MACD',
            ...     symbol='BTCUSDT',
            ...     limit=10
            ... )
        """
        try:
            query = select(BacktestResult).where(
                BacktestResult.strategy == strategy
            )

            if symbol:
                query = query.where(BacktestResult.symbol == symbol)

            query = query.order_by(BacktestResult.created_at.desc())

            if limit:
                query = query.limit(limit)

            result = await self.session.execute(query)
            results = result.scalars().all()
            logger.debug(
                f"Retrieved {len(results)} backtest results for strategy '{strategy}'"
            )
            return list(results)
        except SQLAlchemyError as e:
            logger.error(
                f"Error getting backtest results for strategy '{strategy}': {e}"
            )
            raise

    async def get_best_results(
        self,
        metric: str = 'sharpe_ratio',
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 10,
    ) -> List[BacktestResult]:
        """
        Get best performing backtest results by a specific metric.

        Args:
            metric: Metric to sort by (sharpe_ratio, total_return, profit_factor, etc.)
            strategy: Optional strategy filter
            symbol: Optional symbol filter
            limit: Maximum number of results to return

        Returns:
            List of best performing BacktestResult instances

        Example:
            >>> best = await backtest_dao.get_best_results(
            ...     metric='sharpe_ratio',
            ...     limit=5
            ... )
        """
        try:
            query = select(BacktestResult)

            if strategy:
                query = query.where(BacktestResult.strategy == strategy)
            if symbol:
                query = query.where(BacktestResult.symbol == symbol)

            # Sort by specified metric
            if hasattr(BacktestResult, metric):
                column = getattr(BacktestResult, metric)
                query = query.order_by(column.desc())
            else:
                logger.warning(f"Invalid metric '{metric}', using sharpe_ratio")
                query = query.order_by(BacktestResult.sharpe_ratio.desc())

            query = query.limit(limit)

            result = await self.session.execute(query)
            results = result.scalars().all()
            logger.debug(
                f"Retrieved {len(results)} best backtest results by {metric}"
            )
            return list(results)
        except SQLAlchemyError as e:
            logger.error(f"Error getting best backtest results: {e}")
            raise

    async def compare_strategies(
        self,
        strategies: List[str],
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare backtest performance across multiple strategies.

        Args:
            strategies: List of strategy names to compare
            symbol: Optional symbol filter
            start_date: Optional filter for backtest start_date
            end_date: Optional filter for backtest end_date

        Returns:
            Dictionary mapping strategy names to performance metrics

        Example:
            >>> comparison = await backtest_dao.compare_strategies(
            ...     ['MACD', 'RSI', 'BBands'],
            ...     symbol='BTCUSDT'
            ... )
        """
        try:
            results = {}

            for strategy in strategies:
                query = select(BacktestResult).where(
                    BacktestResult.strategy == strategy
                )

                if symbol:
                    query = query.where(BacktestResult.symbol == symbol)
                if start_date:
                    query = query.where(BacktestResult.start_date >= start_date)
                if end_date:
                    query = query.where(BacktestResult.end_date <= end_date)

                result = await self.session.execute(query)
                backtest_list = result.scalars().all()

                if not backtest_list:
                    results[strategy] = None
                    continue

                # Calculate aggregate metrics
                sharpe_count = len([b for b in backtest_list if b.sharpe_ratio])
                wr_count = len([b for b in backtest_list if b.win_rate])
                dd_count = len([b for b in backtest_list if b.max_drawdown])

                results[strategy] = {
                    'total_backtests': len(backtest_list),
                    'avg_return': sum(b.total_return for b in backtest_list) / len(backtest_list),
                    'avg_sharpe': sum(
                        b.sharpe_ratio for b in backtest_list if b.sharpe_ratio
                    ) / sharpe_count if sharpe_count > 0 else 0,
                    'avg_win_rate': sum(
                        b.win_rate for b in backtest_list if b.win_rate
                    ) / wr_count if wr_count > 0 else 0,
                    'best_return': max(b.total_return for b in backtest_list),
                    'worst_return': min(b.total_return for b in backtest_list),
                    'avg_max_drawdown': sum(
                        b.max_drawdown for b in backtest_list if b.max_drawdown
                    ) / dd_count if dd_count > 0 else 0,
                }

            logger.debug(f"Compared {len(strategies)} strategies")
            return results
        except SQLAlchemyError as e:
            logger.error(f"Error comparing strategies: {e}")
            raise

    async def get_results_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[BacktestResult]:
        """
        Get backtest results within a date range.

        Args:
            start_date: Start date for backtest period
            end_date: End date for backtest period
            strategy: Optional strategy filter
            symbol: Optional symbol filter

        Returns:
            List of BacktestResult instances in date range

        Example:
            >>> results = await backtest_dao.get_results_by_date_range(
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 12, 31)
            ... )
        """
        try:
            query = select(BacktestResult).where(
                and_(
                    BacktestResult.start_date >= start_date,
                    BacktestResult.end_date <= end_date,
                )
            )

            if strategy:
                query = query.where(BacktestResult.strategy == strategy)
            if symbol:
                query = query.where(BacktestResult.symbol == symbol)

            query = query.order_by(BacktestResult.start_date.asc())

            result = await self.session.execute(query)
            results = result.scalars().all()
            logger.debug(
                f"Retrieved {len(results)} backtest results "
                f"between {start_date} and {end_date}"
            )
            return list(results)
        except SQLAlchemyError as e:
            logger.error(f"Error getting backtest results by date range: {e}")
            raise

    async def create_with_config(
        self,
        config: Dict[str, Any],
        **kwargs
    ) -> BacktestResult:
        """
        Create a backtest result with configuration serialized to JSON.

        Args:
            config: Configuration dictionary to serialize
            **kwargs: Other backtest result fields

        Returns:
            Created BacktestResult instance

        Example:
            >>> result = await backtest_dao.create_with_config(
            ...     config={'param1': 10, 'param2': 0.5},
            ...     name='MACD Test 1',
            ...     strategy='MACD',
            ...     symbol='BTCUSDT',
            ...     ...
            ... )
        """
        try:
            # Serialize configuration to JSON string
            config_json = json.dumps(config, default=str)
            kwargs['configuration'] = config_json

            result = await self.create(**kwargs)
            logger.info(f"Created backtest result with id={result.id}")
            return result
        except (SQLAlchemyError, json.JSONDecodeError) as e:
            logger.error(f"Error creating backtest result with config: {e}")
            raise

    async def get_configuration(
        self,
        backtest_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Get parsed configuration for a backtest result.

        Args:
            backtest_id: Backtest result ID

        Returns:
            Parsed configuration dictionary or None if not found

        Example:
            >>> config = await backtest_dao.get_configuration(42)
            >>> print(config['param1'])
        """
        try:
            result = await self.get_by_id(backtest_id)
            if not result or not result.configuration:
                return None

            config = json.loads(result.configuration)
            return config
        except (SQLAlchemyError, json.JSONDecodeError) as e:
            logger.error(
                f"Error getting configuration for backtest {backtest_id}: {e}"
            )
            raise

    async def find_similar_configurations(
        self,
        config: Dict[str, Any],
        strategy: str,
        symbol: Optional[str] = None,
        tolerance: float = 0.1,
    ) -> List[BacktestResult]:
        """
        Find backtest results with similar configurations.

        This is a helper method that would compare configuration parameters
        to find similar backtests. Implementation depends on specific
        configuration structure.

        Args:
            config: Configuration to match against
            strategy: Strategy name
            symbol: Optional symbol filter
            tolerance: Tolerance for numeric parameter matching (10% by default)

        Returns:
            List of BacktestResult instances with similar configs

        Note:
            This is a placeholder. Full implementation would parse and
            compare JSON configurations based on specific parameter structure.

        Example:
            >>> similar = await backtest_dao.find_similar_configurations(
            ...     {'macd_fast': 12, 'macd_slow': 26},
            ...     'MACD'
            ... )
        """
        logger.info(
            f"Finding similar configurations for strategy '{strategy}' "
            f"(tolerance: {tolerance})"
        )
        # This would require custom logic based on configuration structure
        raise NotImplementedError(
            "find_similar_configurations requires configuration-specific logic"
        )

    async def get_optimization_history(
        self,
        strategy: str,
        symbol: str,
        metric: str = 'sharpe_ratio',
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get backtest history for strategy optimization analysis.

        Returns backtest results with their configurations for analyzing
        parameter optimization effectiveness.

        Args:
            strategy: Strategy name
            symbol: Trading symbol
            metric: Metric to sort by
            limit: Maximum number of results

        Returns:
            List of dictionaries with backtest data and parsed configs

        Example:
            >>> history = await backtest_dao.get_optimization_history(
            ...     'MACD',
            ...     'BTCUSDT',
            ...     metric='sharpe_ratio'
            ... )
        """
        try:
            results = await self.get_best_results(
                metric=metric,
                strategy=strategy,
                symbol=symbol,
                limit=limit
            )

            history = []
            for result in results:
                try:
                    config = json.loads(result.configuration)
                except json.JSONDecodeError:
                    config = {}

                history.append({
                    'id': result.id,
                    'name': result.name,
                    'created_at': result.created_at,
                    'total_return': result.total_return,
                    'sharpe_ratio': result.sharpe_ratio,
                    'max_drawdown': result.max_drawdown,
                    'win_rate': result.win_rate,
                    'total_trades': result.total_trades,
                    'configuration': config,
                })

            logger.debug(
                f"Retrieved optimization history for {strategy}/{symbol}: "
                f"{len(history)} results"
            )
            return history
        except SQLAlchemyError as e:
            logger.error(f"Error getting optimization history: {e}")
            raise

    async def get_statistics_summary(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for all backtests.

        Args:
            strategy: Optional strategy filter
            symbol: Optional symbol filter

        Returns:
            Dictionary with aggregate statistics

        Example:
            >>> summary = await backtest_dao.get_statistics_summary(strategy='MACD')
        """
        try:
            query = select(BacktestResult)

            if strategy:
                query = query.where(BacktestResult.strategy == strategy)
            if symbol:
                query = query.where(BacktestResult.symbol == symbol)

            result = await self.session.execute(query)
            results = result.scalars().all()

            if not results:
                return {
                    'total_backtests': 0,
                    'strategies_tested': 0,
                    'symbols_tested': 0,
                }

            sharpe_count = len([r for r in results if r.sharpe_ratio])
            wr_count = len([r for r in results if r.win_rate])

            summary = {
                'total_backtests': len(results),
                'strategies_tested': len(set(r.strategy for r in results)),
                'symbols_tested': len(set(r.symbol for r in results)),
                'avg_return': sum(r.total_return for r in results) / len(results),
                'best_return': max(r.total_return for r in results),
                'worst_return': min(r.total_return for r in results),
                'avg_sharpe': sum(
                    r.sharpe_ratio for r in results if r.sharpe_ratio
                ) / sharpe_count if sharpe_count > 0 else 0,
                'avg_win_rate': sum(
                    r.win_rate for r in results if r.win_rate
                ) / wr_count if wr_count > 0 else 0,
                'total_trades_simulated': sum(r.total_trades for r in results),
            }

            logger.debug(f"Calculated backtest statistics summary: {summary}")
            return summary
        except SQLAlchemyError as e:
            logger.error(f"Error getting statistics summary: {e}")
            raise

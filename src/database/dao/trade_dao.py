"""
Trade Data Access Object for trade-specific database operations.

This module provides specialized database operations for Trade records
including strategy-based queries, P&L calculations, and performance metrics.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dao.base import BaseDAO
from src.database.models import Trade

logger = logging.getLogger(__name__)


class TradeDAO(BaseDAO[Trade]):
    """
    Data Access Object for Trade model with specialized query methods.

    Provides CRUD operations plus complex queries for trade analysis,
    strategy performance, and P&L calculations.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize TradeDAO with database session.

        Args:
            session: Async database session
        """
        super().__init__(Trade, session)

    async def get_trades_by_strategy(
        self,
        strategy: str,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Trade]:
        """
        Get trades filtered by strategy with optional criteria.

        Args:
            strategy: Strategy name to filter by
            status: Optional trade status (OPEN, CLOSED, CANCELLED)
            symbol: Optional symbol to filter by
            start_date: Optional start date for entry_time filter
            end_date: Optional end date for entry_time filter
            limit: Maximum number of trades to return

        Returns:
            List of Trade instances matching criteria

        Example:
            >>> trades = await trade_dao.get_trades_by_strategy(
            ...     'MACD',
            ...     status='CLOSED',
            ...     symbol='BTCUSDT',
            ...     start_date=datetime(2024, 1, 1)
            ... )
        """
        try:
            query = select(Trade).where(Trade.strategy == strategy)

            if status:
                query = query.where(Trade.status == status)
            if symbol:
                query = query.where(Trade.symbol == symbol)
            if start_date:
                query = query.where(Trade.entry_time >= start_date)
            if end_date:
                query = query.where(Trade.entry_time <= end_date)

            query = query.order_by(Trade.entry_time.desc())

            if limit:
                query = query.limit(limit)

            result = await self.session.execute(query)
            trades = result.scalars().all()
            logger.debug(f"Retrieved {len(trades)} trades for strategy '{strategy}'")
            return list(trades)
        except SQLAlchemyError as e:
            logger.error(f"Error getting trades by strategy '{strategy}': {e}")
            raise

    async def get_open_trades(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Trade]:
        """
        Get all currently open trades.

        Args:
            strategy: Optional strategy name filter
            symbol: Optional symbol filter

        Returns:
            List of open Trade instances

        Example:
            >>> open_trades = await trade_dao.get_open_trades(strategy='MACD')
        """
        try:
            query = select(Trade).where(Trade.status == "OPEN")

            if strategy:
                query = query.where(Trade.strategy == strategy)
            if symbol:
                query = query.where(Trade.symbol == symbol)

            query = query.order_by(Trade.entry_time.desc())

            result = await self.session.execute(query)
            trades = result.scalars().all()
            logger.debug(f"Retrieved {len(trades)} open trades")
            return list(trades)
        except SQLAlchemyError as e:
            logger.error(f"Error getting open trades: {e}")
            raise

    async def get_closed_trades_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Trade]:
        """
        Get closed trades within a date range.

        Args:
            start_date: Start date for exit_time filter
            end_date: End date for exit_time filter
            strategy: Optional strategy name filter
            symbol: Optional symbol filter

        Returns:
            List of closed Trade instances in date range

        Example:
            >>> trades = await trade_dao.get_closed_trades_by_date_range(
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 31),
            ...     strategy='MACD'
            ... )
        """
        try:
            query = select(Trade).where(
                and_(
                    Trade.status == "CLOSED",
                    Trade.exit_time >= start_date,
                    Trade.exit_time <= end_date,
                )
            )

            if strategy:
                query = query.where(Trade.strategy == strategy)
            if symbol:
                query = query.where(Trade.symbol == symbol)

            query = query.order_by(Trade.exit_time.desc())

            result = await self.session.execute(query)
            trades = result.scalars().all()
            logger.debug(
                f"Retrieved {len(trades)} closed trades " f"between {start_date} and {end_date}"
            )
            return list(trades)
        except SQLAlchemyError as e:
            logger.error(f"Error getting closed trades by date range: {e}")
            raise

    async def calculate_strategy_pnl(
        self,
        strategy: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Calculate P&L statistics for a strategy.

        Args:
            strategy: Strategy name
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary with P&L statistics:
                - total_pnl: Total profit/loss
                - total_trades: Number of trades
                - winning_trades: Number of winning trades
                - losing_trades: Number of losing trades
                - win_rate: Win rate percentage
                - avg_pnl: Average P&L per trade
                - avg_win: Average winning trade
                - avg_loss: Average losing trade
                - total_fees: Total fees paid

        Example:
            >>> stats = await trade_dao.calculate_strategy_pnl('MACD')
            >>> print(f"Win rate: {stats['win_rate']}%")
        """
        try:
            query = select(Trade).where(
                and_(
                    Trade.strategy == strategy,
                    Trade.status == "CLOSED",
                )
            )

            if start_date:
                query = query.where(Trade.exit_time >= start_date)
            if end_date:
                query = query.where(Trade.exit_time <= end_date)

            result = await self.session.execute(query)
            trades = result.scalars().all()

            if not trades:
                return {
                    "total_pnl": Decimal("0"),
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "avg_pnl": Decimal("0"),
                    "avg_win": Decimal("0"),
                    "avg_loss": Decimal("0"),
                    "total_fees": Decimal("0"),
                }

            winning_trades = [t for t in trades if t.pnl and t.pnl > 0]
            losing_trades = [t for t in trades if t.pnl and t.pnl < 0]

            total_pnl = sum(t.pnl for t in trades if t.pnl) or Decimal("0")
            total_fees = sum(t.fees for t in trades if t.fees) or Decimal("0")

            avg_win = (
                sum(t.pnl for t in winning_trades) / len(winning_trades)
                if winning_trades
                else Decimal("0")
            )
            avg_loss = (
                sum(t.pnl for t in losing_trades) / len(losing_trades)
                if losing_trades
                else Decimal("0")
            )

            stats = {
                "total_pnl": total_pnl,
                "total_trades": len(trades),
                "winning_trades": len(winning_trades),
                "losing_trades": len(losing_trades),
                "win_rate": (len(winning_trades) / len(trades) * 100) if trades else 0.0,
                "avg_pnl": total_pnl / len(trades) if trades else Decimal("0"),
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "total_fees": total_fees,
            }

            logger.debug(f"Calculated P&L stats for strategy '{strategy}': {stats}")
            return stats
        except SQLAlchemyError as e:
            logger.error(f"Error calculating strategy P&L: {e}")
            raise

    async def get_best_trades(
        self,
        limit: int = 10,
        strategy: Optional[str] = None,
    ) -> List[Trade]:
        """
        Get best performing trades by P&L.

        Args:
            limit: Maximum number of trades to return
            strategy: Optional strategy filter

        Returns:
            List of top performing Trade instances

        Example:
            >>> best_trades = await trade_dao.get_best_trades(limit=5, strategy='MACD')
        """
        try:
            query = select(Trade).where(
                and_(
                    Trade.status == "CLOSED",
                    Trade.pnl.isnot(None),
                )
            )

            if strategy:
                query = query.where(Trade.strategy == strategy)

            query = query.order_by(Trade.pnl.desc()).limit(limit)

            result = await self.session.execute(query)
            trades = result.scalars().all()
            logger.debug(f"Retrieved {len(trades)} best trades")
            return list(trades)
        except SQLAlchemyError as e:
            logger.error(f"Error getting best trades: {e}")
            raise

    async def get_worst_trades(
        self,
        limit: int = 10,
        strategy: Optional[str] = None,
    ) -> List[Trade]:
        """
        Get worst performing trades by P&L.

        Args:
            limit: Maximum number of trades to return
            strategy: Optional strategy filter

        Returns:
            List of worst performing Trade instances

        Example:
            >>> worst_trades = await trade_dao.get_worst_trades(limit=5)
        """
        try:
            query = select(Trade).where(
                and_(
                    Trade.status == "CLOSED",
                    Trade.pnl.isnot(None),
                )
            )

            if strategy:
                query = query.where(Trade.strategy == strategy)

            query = query.order_by(Trade.pnl.asc()).limit(limit)

            result = await self.session.execute(query)
            trades = result.scalars().all()
            logger.debug(f"Retrieved {len(trades)} worst trades")
            return list(trades)
        except SQLAlchemyError as e:
            logger.error(f"Error getting worst trades: {e}")
            raise

    async def close_trade(
        self,
        trade_id: int,
        exit_price: Decimal,
        exit_time: datetime,
        exit_reason: str,
        fees: Optional[Decimal] = None,
    ) -> Optional[Trade]:
        """
        Close an open trade and calculate P&L.

        Args:
            trade_id: Trade ID to close
            exit_price: Exit price
            exit_time: Exit timestamp
            exit_reason: Reason for exit (TP, SL, MANUAL, SIGNAL)
            fees: Optional exit fees

        Returns:
            Updated Trade instance with calculated P&L

        Example:
            >>> trade = await trade_dao.close_trade(
            ...     42,
            ...     Decimal('55000'),
            ...     datetime.now(),
            ...     'TP'
            ... )
        """
        try:
            trade = await self.get_by_id(trade_id)
            if not trade:
                logger.warning(f"Trade {trade_id} not found for closing")
                return None

            if trade.status != "OPEN":
                logger.warning(f"Trade {trade_id} is not open (status: {trade.status})")
                return trade

            # Calculate P&L
            price_diff = exit_price - trade.entry_price
            if trade.side == "SHORT":
                price_diff = -price_diff

            pnl = price_diff * trade.quantity * trade.leverage
            if fees:
                pnl -= fees

            pnl_percent = (price_diff / trade.entry_price * 100) if trade.entry_price else 0

            # Update trade
            trade.exit_price = exit_price
            trade.exit_time = exit_time
            trade.exit_reason = exit_reason
            trade.pnl = pnl
            trade.pnl_percent = float(pnl_percent)
            trade.status = "CLOSED"

            if fees:
                trade.fees = (trade.fees or Decimal("0")) + fees

            await self.session.flush()
            await self.session.refresh(trade)

            logger.info(
                f"Closed trade {trade_id}: "
                f"P&L={pnl}, exit_price={exit_price}, reason={exit_reason}"
            )
            return trade
        except SQLAlchemyError as e:
            logger.error(f"Error closing trade {trade_id}: {e}")
            raise

"""
Position Data Access Object for position-specific database operations.

This module provides specialized database operations for Position records
including current position tracking, unrealized P&L updates, and risk management.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dao.base import BaseDAO
from src.database.models import Position

logger = logging.getLogger(__name__)


class PositionDAO(BaseDAO[Position]):
    """
    Data Access Object for Position model with specialized query methods.

    Provides CRUD operations plus complex queries for position management,
    unrealized P&L tracking, and risk monitoring.
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize PositionDAO with database session.

        Args:
            session: Async database session
        """
        super().__init__(Position, session)

    async def get_current_positions(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[Position]:
        """
        Get all currently open positions.

        Args:
            strategy: Optional strategy name filter
            symbol: Optional symbol filter

        Returns:
            List of open Position instances

        Example:
            >>> positions = await position_dao.get_current_positions(strategy='MACD')
        """
        try:
            query = select(Position).where(Position.status == "OPEN")

            if strategy:
                query = query.where(Position.strategy == strategy)
            if symbol:
                query = query.where(Position.symbol == symbol)

            query = query.order_by(Position.opened_at.desc())

            result = await self.session.execute(query)
            positions = result.scalars().all()
            logger.debug(f"Retrieved {len(positions)} current open positions")
            return list(positions)
        except SQLAlchemyError as e:
            logger.error(f"Error getting current positions: {e}")
            raise

    async def get_position_by_symbol_strategy(
        self,
        symbol: str,
        strategy: str,
    ) -> Optional[Position]:
        """
        Get the current open position for a specific symbol and strategy.

        Args:
            symbol: Trading symbol
            strategy: Strategy name

        Returns:
            Open Position instance or None

        Example:
            >>> position = await position_dao.get_position_by_symbol_strategy(
            ...     'BTCUSDT',
            ...     'MACD'
            ... )
        """
        try:
            query = (
                select(Position)
                .where(
                    and_(
                        Position.symbol == symbol,
                        Position.strategy == strategy,
                        Position.status == "OPEN",
                    )
                )
                .order_by(Position.opened_at.desc())
                .limit(1)
            )

            result = await self.session.execute(query)
            position = result.scalar_one_or_none()

            if position:
                logger.debug(f"Retrieved open position for {symbol} with strategy '{strategy}'")
            return position
        except SQLAlchemyError as e:
            logger.error(f"Error getting position for {symbol} with strategy '{strategy}': {e}")
            raise

    async def update_unrealized_pnl(
        self,
        position_id: int,
        current_price: Decimal,
    ) -> Optional[Position]:
        """
        Update position with current price and recalculate unrealized P&L.

        Args:
            position_id: Position ID
            current_price: Current market price

        Returns:
            Updated Position instance

        Example:
            >>> position = await position_dao.update_unrealized_pnl(
            ...     42,
            ...     Decimal('55000')
            ... )
        """
        try:
            position = await self.get_by_id(position_id)
            if not position:
                logger.warning(f"Position {position_id} not found for P&L update")
                return None

            if position.status != "OPEN":
                logger.warning(f"Position {position_id} is not open (status: {position.status})")
                return position

            # Calculate unrealized P&L
            price_diff = current_price - position.entry_price
            if position.side == "SHORT":
                price_diff = -price_diff

            unrealized_pnl = price_diff * position.size * position.leverage
            unrealized_pnl_percent = (
                (price_diff / position.entry_price * 100) if position.entry_price else 0
            )

            # Update position
            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            position.unrealized_pnl_percent = float(unrealized_pnl_percent)

            await self.session.flush()
            await self.session.refresh(position)

            logger.debug(
                f"Updated position {position_id} unrealized P&L: "
                f"{unrealized_pnl} ({unrealized_pnl_percent:.2f}%)"
            )
            return position
        except SQLAlchemyError as e:
            logger.error(f"Error updating unrealized P&L for position {position_id}: {e}")
            raise

    async def close_position(
        self,
        position_id: int,
        closed_at: datetime,
        realized_pnl: Decimal,
    ) -> Optional[Position]:
        """
        Close a position and record realized P&L.

        Args:
            position_id: Position ID to close
            closed_at: Closing timestamp
            realized_pnl: Final realized P&L

        Returns:
            Updated closed Position instance

        Example:
            >>> position = await position_dao.close_position(
            ...     42,
            ...     datetime.now(),
            ...     Decimal('500')
            ... )
        """
        try:
            position = await self.get_by_id(position_id)
            if not position:
                logger.warning(f"Position {position_id} not found for closing")
                return None

            if position.status != "OPEN":
                logger.warning(
                    f"Position {position_id} is already closed (status: {position.status})"
                )
                return position

            # Close position
            position.status = "CLOSED"
            position.closed_at = closed_at
            position.realized_pnl = realized_pnl
            position.unrealized_pnl = Decimal("0")
            position.unrealized_pnl_percent = 0.0

            await self.session.flush()
            await self.session.refresh(position)

            logger.info(
                f"Closed position {position_id}: "
                f"realized_pnl={realized_pnl}, closed_at={closed_at}"
            )
            return position
        except SQLAlchemyError as e:
            logger.error(f"Error closing position {position_id}: {e}")
            raise

    async def get_positions_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        strategy: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Position]:
        """
        Get positions opened within a date range.

        Args:
            start_date: Start date for opened_at filter
            end_date: End date for opened_at filter
            strategy: Optional strategy name filter
            status: Optional status filter (OPEN, CLOSED)

        Returns:
            List of Position instances in date range

        Example:
            >>> positions = await position_dao.get_positions_by_date_range(
            ...     datetime(2024, 1, 1),
            ...     datetime(2024, 1, 31),
            ...     strategy='MACD'
            ... )
        """
        try:
            query = select(Position).where(
                and_(
                    Position.opened_at >= start_date,
                    Position.opened_at <= end_date,
                )
            )

            if strategy:
                query = query.where(Position.strategy == strategy)
            if status:
                query = query.where(Position.status == status)

            query = query.order_by(Position.opened_at.desc())

            result = await self.session.execute(query)
            positions = result.scalars().all()
            logger.debug(
                f"Retrieved {len(positions)} positions " f"between {start_date} and {end_date}"
            )
            return list(positions)
        except SQLAlchemyError as e:
            logger.error(f"Error getting positions by date range: {e}")
            raise

    async def calculate_total_exposure(
        self,
        strategy: Optional[str] = None,
    ) -> Dict[str, Decimal]:
        """
        Calculate total exposure (position value) for open positions.

        Args:
            strategy: Optional strategy filter

        Returns:
            Dictionary with exposure metrics:
                - total_long_exposure: Total long position value
                - total_short_exposure: Total short position value
                - net_exposure: Net exposure (long - short)
                - total_absolute_exposure: Sum of all positions

        Example:
            >>> exposure = await position_dao.calculate_total_exposure('MACD')
            >>> print(f"Net exposure: {exposure['net_exposure']}")
        """
        try:
            query = select(Position).where(Position.status == "OPEN")

            if strategy:
                query = query.where(Position.strategy == strategy)

            result = await self.session.execute(query)
            positions = result.scalars().all()

            long_exposure = Decimal("0")
            short_exposure = Decimal("0")

            for pos in positions:
                position_value = pos.size * pos.entry_price * pos.leverage
                if pos.side == "LONG":
                    long_exposure += position_value
                else:
                    short_exposure += position_value

            exposure = {
                "total_long_exposure": long_exposure,
                "total_short_exposure": short_exposure,
                "net_exposure": long_exposure - short_exposure,
                "total_absolute_exposure": long_exposure + short_exposure,
            }

            logger.debug(f"Calculated total exposure: {exposure}")
            return exposure
        except SQLAlchemyError as e:
            logger.error(f"Error calculating total exposure: {e}")
            raise

    async def get_positions_at_risk(
        self,
        risk_threshold: float = -5.0,
    ) -> List[Position]:
        """
        Get positions with unrealized loss exceeding risk threshold.

        Args:
            risk_threshold: P&L percentage threshold (negative value)

        Returns:
            List of Position instances at risk

        Example:
            >>> at_risk = await position_dao.get_positions_at_risk(risk_threshold=-10.0)
        """
        try:
            query = (
                select(Position)
                .where(
                    and_(
                        Position.status == "OPEN",
                        Position.unrealized_pnl_percent.isnot(None),
                        Position.unrealized_pnl_percent <= risk_threshold,
                    )
                )
                .order_by(Position.unrealized_pnl_percent.asc())
            )

            result = await self.session.execute(query)
            positions = result.scalars().all()
            logger.debug(
                f"Retrieved {len(positions)} positions at risk " f"(threshold: {risk_threshold}%)"
            )
            return list(positions)
        except SQLAlchemyError as e:
            logger.error(f"Error getting positions at risk: {e}")
            raise

    async def update_stop_loss_take_profit(
        self,
        position_id: int,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
    ) -> Optional[Position]:
        """
        Update stop loss and take profit levels for a position.

        Args:
            position_id: Position ID
            stop_loss: Optional stop loss price
            take_profit: Optional take profit price

        Returns:
            Updated Position instance

        Example:
            >>> position = await position_dao.update_stop_loss_take_profit(
            ...     42,
            ...     stop_loss=Decimal('48000'),
            ...     take_profit=Decimal('60000')
            ... )
        """
        try:
            position = await self.get_by_id(position_id)
            if not position:
                logger.warning(f"Position {position_id} not found for SL/TP update")
                return None

            if stop_loss is not None:
                position.stop_loss = stop_loss
            if take_profit is not None:
                position.take_profit = take_profit

            await self.session.flush()
            await self.session.refresh(position)

            logger.debug(
                f"Updated position {position_id} SL/TP: " f"SL={stop_loss}, TP={take_profit}"
            )
            return position
        except SQLAlchemyError as e:
            logger.error(f"Error updating SL/TP for position {position_id}: {e}")
            raise

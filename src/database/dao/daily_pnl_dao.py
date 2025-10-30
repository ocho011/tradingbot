"""
Data Access Object for Daily P&L records.

Provides database operations for storing and retrieving daily profit/loss
tracking data, including session history and loss limit breach records.
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from src.database.models import DailyPnL
from src.database.dao.base import BaseDAO


logger = logging.getLogger(__name__)


class DailyPnLDAO(BaseDAO[DailyPnL]):
    """
    Data Access Object for Daily P&L operations.

    Provides specialized methods for daily session tracking, including:
    - Session creation and updates
    - Historical P&L queries
    - Loss limit breach tracking
    - Performance statistics retrieval
    """

    def __init__(self, session: AsyncSession):
        """
        Initialize DailyPnLDAO.

        Args:
            session: Async database session
        """
        super().__init__(DailyPnL, session)

    async def create_session(
        self,
        date_str: str,
        starting_balance: Decimal,
        session_start: datetime,
        loss_limit_percentage: float = 6.0
    ) -> DailyPnL:
        """
        Create a new daily P&L session.

        Args:
            date_str: Date in YYYY-MM-DD format
            starting_balance: Starting account balance
            session_start: Session start timestamp
            loss_limit_percentage: Daily loss limit percentage

        Returns:
            Created DailyPnL record

        Raises:
            IntegrityError: If session for this date already exists
            SQLAlchemyError: If database operation fails
        """
        try:
            session = await self.create(
                date=date_str,
                starting_balance=starting_balance,
                session_start=session_start,
                loss_limit_percentage=loss_limit_percentage
            )
            logger.info(f"Created daily session for {date_str} with balance {starting_balance}")
            return session
        except IntegrityError:
            logger.error(f"Session already exists for date {date_str}")
            raise
        except SQLAlchemyError as e:
            logger.error(f"Error creating daily session: {e}")
            raise

    async def update_session(
        self,
        date_str: str,
        ending_balance: Optional[Decimal] = None,
        realized_pnl: Optional[Decimal] = None,
        unrealized_pnl: Optional[Decimal] = None,
        total_pnl: Optional[Decimal] = None,
        pnl_percentage: Optional[float] = None,
        loss_limit_reached: Optional[bool] = None,
        total_trades: Optional[int] = None,
        winning_trades: Optional[int] = None,
        losing_trades: Optional[int] = None,
        session_end: Optional[datetime] = None
    ) -> Optional[DailyPnL]:
        """
        Update existing daily session.

        Args:
            date_str: Date in YYYY-MM-DD format
            ending_balance: Ending account balance
            realized_pnl: Realized profit/loss
            unrealized_pnl: Unrealized profit/loss
            total_pnl: Total profit/loss
            pnl_percentage: P&L percentage
            loss_limit_reached: Whether loss limit was reached
            total_trades: Total number of trades
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
            session_end: Session end timestamp

        Returns:
            Updated DailyPnL record or None if not found

        Raises:
            SQLAlchemyError: If database operation fails
        """
        try:
            stmt = select(DailyPnL).where(DailyPnL.date == date_str)
            result = await self.session.execute(stmt)
            session = result.scalar_one_or_none()

            if not session:
                logger.warning(f"No session found for date {date_str}")
                return None

            # Update provided fields
            if ending_balance is not None:
                session.ending_balance = ending_balance
            if realized_pnl is not None:
                session.realized_pnl = realized_pnl
            if unrealized_pnl is not None:
                session.unrealized_pnl = unrealized_pnl
            if total_pnl is not None:
                session.total_pnl = total_pnl
            if pnl_percentage is not None:
                session.pnl_percentage = pnl_percentage
            if loss_limit_reached is not None:
                session.loss_limit_reached = loss_limit_reached
            if total_trades is not None:
                session.total_trades = total_trades
            if winning_trades is not None:
                session.winning_trades = winning_trades
            if losing_trades is not None:
                session.losing_trades = losing_trades
            if session_end is not None:
                session.session_end = session_end

            await self.session.flush()
            await self.session.refresh(session)

            logger.debug(f"Updated session for {date_str}")
            return session

        except SQLAlchemyError as e:
            logger.error(f"Error updating session for {date_str}: {e}")
            raise

    async def get_session_by_date(self, date_str: str) -> Optional[DailyPnL]:
        """
        Get daily session by date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            DailyPnL record or None if not found
        """
        try:
            stmt = select(DailyPnL).where(DailyPnL.date == date_str)
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error fetching session for {date_str}: {e}")
            raise

    async def get_recent_sessions(
        self,
        limit: int = 30,
        include_loss_limit_only: bool = False
    ) -> List[DailyPnL]:
        """
        Get recent daily sessions.

        Args:
            limit: Maximum number of sessions to return
            include_loss_limit_only: Only return sessions where loss limit was reached

        Returns:
            List of DailyPnL records ordered by date descending
        """
        try:
            stmt = select(DailyPnL).order_by(desc(DailyPnL.date)).limit(limit)

            if include_loss_limit_only:
                stmt = stmt.where(DailyPnL.loss_limit_reached.is_(True))

            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching recent sessions: {e}")
            raise

    async def get_sessions_in_range(
        self,
        start_date: str,
        end_date: str
    ) -> List[DailyPnL]:
        """
        Get sessions within date range.

        Args:
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)

        Returns:
            List of DailyPnL records ordered by date ascending
        """
        try:
            stmt = (
                select(DailyPnL)
                .where(
                    and_(
                        DailyPnL.date >= start_date,
                        DailyPnL.date <= end_date
                    )
                )
                .order_by(DailyPnL.date)
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching sessions in range {start_date} to {end_date}: {e}")
            raise

    async def get_loss_limit_breaches(
        self,
        days: int = 30
    ) -> List[DailyPnL]:
        """
        Get sessions where loss limit was breached.

        Args:
            days: Number of days to look back

        Returns:
            List of DailyPnL records where loss_limit_reached is True
        """
        try:
            cutoff_date = (datetime.now().date() - timedelta(days=days)).strftime('%Y-%m-%d')
            stmt = (
                select(DailyPnL)
                .where(
                    and_(
                        DailyPnL.loss_limit_reached.is_(True),
                        DailyPnL.date >= cutoff_date
                    )
                )
                .order_by(desc(DailyPnL.date))
            )
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as e:
            logger.error(f"Error fetching loss limit breaches: {e}")
            raise

    async def get_performance_summary(
        self,
        days: int = 30
    ) -> dict:
        """
        Get performance summary for the specified period.

        Args:
            days: Number of days to analyze

        Returns:
            Dict containing:
                - total_sessions: Number of trading sessions
                - total_pnl: Sum of all P&L
                - avg_pnl: Average daily P&L
                - winning_sessions: Number of profitable sessions
                - losing_sessions: Number of losing sessions
                - loss_limit_breaches: Number of sessions hitting loss limit
                - win_rate: Percentage of winning sessions
        """
        try:
            cutoff_date = (datetime.now().date() - timedelta(days=days)).strftime('%Y-%m-%d')
            stmt = select(DailyPnL).where(DailyPnL.date >= cutoff_date)
            result = await self.session.execute(stmt)
            sessions = list(result.scalars().all())

            if not sessions:
                return {
                    'total_sessions': 0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0,
                    'winning_sessions': 0,
                    'losing_sessions': 0,
                    'loss_limit_breaches': 0,
                    'win_rate': 0.0
                }

            total_pnl = sum(float(s.total_pnl) for s in sessions)
            winning_sessions = sum(1 for s in sessions if s.total_pnl > 0)
            losing_sessions = sum(1 for s in sessions if s.total_pnl < 0)
            loss_limit_breaches = sum(1 for s in sessions if s.loss_limit_reached)

            return {
                'total_sessions': len(sessions),
                'total_pnl': total_pnl,
                'avg_pnl': total_pnl / len(sessions),
                'winning_sessions': winning_sessions,
                'losing_sessions': losing_sessions,
                'loss_limit_breaches': loss_limit_breaches,
                'win_rate': (winning_sessions / len(sessions)) * 100 if sessions else 0.0
            }

        except SQLAlchemyError as e:
            logger.error(f"Error calculating performance summary: {e}")
            raise

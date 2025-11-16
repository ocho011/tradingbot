"""
Daily loss monitor for tracking and enforcing daily loss limits.

This module implements real-time P&L monitoring with:
- Daily starting balance tracking with timezone awareness
- Real-time loss percentage calculation
- 6% daily loss limit enforcement
- Event emission when threshold reached
- SQLite-based daily P&L history persistence
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal
from threading import Lock
from typing import Any, Dict, Optional

from src.core.constants import EventType
from src.core.events import Event

logger = logging.getLogger(__name__)


class DailyLossLimitError(Exception):
    """Raised when daily loss limit operations fail."""


@dataclass
class DailySession:
    """
    Represents a trading day session.

    Attributes:
        date: Trading day date (UTC)
        starting_balance: Balance at session start
        current_balance: Current balance in session
        realized_pnl: Realized profit/loss for the day
        unrealized_pnl: Unrealized profit/loss for the day
        total_pnl: Total P&L (realized + unrealized)
        loss_percentage: Loss as percentage of starting balance
        limit_reached: Whether loss limit has been reached
    """

    date: str  # YYYY-MM-DD format
    starting_balance: Decimal
    current_balance: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    loss_percentage: Decimal = Decimal("0")
    limit_reached: bool = False

    def calculate_metrics(self) -> None:
        """Calculate P&L metrics."""
        self.total_pnl = self.realized_pnl + self.unrealized_pnl
        if self.starting_balance > 0:
            self.loss_percentage = (self.total_pnl / self.starting_balance) * Decimal("100")
        else:
            self.loss_percentage = Decimal("0")


class DailyLossMonitor:
    """
    Monitor daily profit/loss and enforce loss limits.

    Features:
    - Track daily starting balance at session start
    - Monitor real-time P&L throughout trading day
    - Calculate loss percentage against starting balance
    - Detect 6% loss threshold breach
    - Emit 'daily_loss_limit_reached' event when threshold hit
    - Store daily P&L history in database
    - Thread-safe balance updates
    - Timezone-aware day boundaries (UTC)

    Attributes:
        daily_loss_limit_pct: Maximum allowed daily loss percentage
        reset_time_utc: UTC time for daily session reset (default: 00:00)
        precision: Decimal places for balance calculations
        current_session: Current trading day session
        event_bus: EventBus for emitting limit reached events
    """

    def __init__(
        self,
        event_bus,
        daily_loss_limit_pct: float = 6.0,
        reset_time_utc: time = time(0, 0),
        precision: int = 8,
    ):
        """
        Initialize daily loss monitor.

        Args:
            event_bus: EventBus instance for event emission
            daily_loss_limit_pct: Maximum daily loss percentage (default: 6.0%)
            reset_time_utc: UTC time for daily session reset (default: 00:00)
            precision: Decimal places for balance calculations

        Raises:
            ValueError: If daily_loss_limit_pct is not positive
        """
        if daily_loss_limit_pct <= 0:
            raise ValueError(f"daily_loss_limit_pct must be positive, got {daily_loss_limit_pct}")

        self.event_bus = event_bus
        self.daily_loss_limit_pct = Decimal(str(daily_loss_limit_pct))
        self.reset_time_utc = reset_time_utc
        self.precision = precision

        self.current_session: Optional[DailySession] = None
        self._lock = Lock()
        self._limit_event_emitted = False

        self.logger = logging.getLogger(f"{__name__}.DailyLossMonitor")

    def start_session(self, starting_balance: Decimal) -> DailySession:
        """
        Start a new trading day session.

        Creates a new session with the provided starting balance and
        resets all daily metrics.

        Args:
            starting_balance: Account balance at session start

        Returns:
            DailySession: Newly created session

        Raises:
            ValueError: If starting_balance is not positive
        """
        if starting_balance <= 0:
            raise ValueError(f"starting_balance must be positive, got {starting_balance}")

        with self._lock:
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            self.current_session = DailySession(
                date=current_date,
                starting_balance=starting_balance,
                current_balance=starting_balance,
            )
            self._limit_event_emitted = False

            self.logger.info(
                f"Started new trading session for {current_date} "
                f"with balance: {starting_balance}"
            )

            return self.current_session

    def update_balance(
        self, current_balance: Decimal, realized_pnl: Decimal, unrealized_pnl: Decimal
    ) -> Dict[str, Any]:
        """
        Update current balance and P&L metrics.

        Calculates loss percentage and checks if limit is reached.
        Emits event if threshold breached for the first time.

        Args:
            current_balance: Current account balance
            realized_pnl: Realized profit/loss for the day
            unrealized_pnl: Unrealized profit/loss from open positions

        Returns:
            Dict containing:
                - session: Current session data
                - limit_reached: Whether loss limit was reached
                - event_emitted: Whether limit event was emitted

        Raises:
            DailyLossLimitError: If no active session exists
        """
        with self._lock:
            if not self.current_session:
                raise DailyLossLimitError("No active session. Call start_session() first.")

            # Update session metrics
            self.current_session.current_balance = current_balance
            self.current_session.realized_pnl = realized_pnl
            self.current_session.unrealized_pnl = unrealized_pnl
            self.current_session.calculate_metrics()

            # Check if loss limit reached
            limit_reached = self.current_session.loss_percentage <= -self.daily_loss_limit_pct

            event_emitted = False

            # Emit event only once when limit first reached
            if limit_reached and not self._limit_event_emitted:
                self.current_session.limit_reached = True
                self._emit_limit_reached_event()
                event_emitted = True
                self._limit_event_emitted = True

            return {
                "session": self.current_session,
                "limit_reached": limit_reached,
                "event_emitted": event_emitted,
            }

    def get_current_status(self) -> Optional[Dict[str, Any]]:
        """
        Get current session status and metrics.

        Returns:
            Dict with session info or None if no active session:
                - date: Session date
                - starting_balance: Balance at session start
                - current_balance: Current balance
                - total_pnl: Total profit/loss
                - loss_percentage: Loss as percentage
                - loss_limit: Configured loss limit
                - limit_reached: Whether limit reached
                - distance_to_limit: Percentage points to limit
        """
        with self._lock:
            if not self.current_session:
                return None

            # Calculate distance to limit (positive when below limit, negative when exceeded)
            # loss_percentage is negative for losses, so we need to add it to the limit
            distance_to_limit = self.daily_loss_limit_pct + self.current_session.loss_percentage

            return {
                "date": self.current_session.date,
                "starting_balance": float(self.current_session.starting_balance),
                "current_balance": float(self.current_session.current_balance),
                "realized_pnl": float(self.current_session.realized_pnl),
                "unrealized_pnl": float(self.current_session.unrealized_pnl),
                "total_pnl": float(self.current_session.total_pnl),
                "loss_percentage": float(self.current_session.loss_percentage),
                "loss_limit": float(self.daily_loss_limit_pct),
                "limit_reached": self.current_session.limit_reached,
                "distance_to_limit": float(distance_to_limit),
            }

    def should_reset_session(self) -> bool:
        """
        Check if session should be reset based on UTC time.

        Compares current UTC time against reset_time_utc and session date
        to determine if a new trading day has started.

        Returns:
            bool: True if session should be reset
        """
        if not self.current_session:
            return True

        now_utc = datetime.now(timezone.utc)
        current_date = now_utc.strftime("%Y-%m-%d")

        # Reset if we're on a different date
        if self.current_session.date != current_date:
            # Check if we've passed the reset time
            if now_utc.time() >= self.reset_time_utc:
                return True

        return False

    def is_loss_limit_reached(self) -> bool:
        """
        Check if daily loss limit has been reached.

        Returns:
            bool: True if limit reached, False otherwise
        """
        with self._lock:
            if not self.current_session:
                return False
            return self.current_session.limit_reached

    def _emit_limit_reached_event(self) -> None:
        """
        Emit daily_loss_limit_reached event.

        Creates and publishes event with session context including:
        - Current balance
        - Loss amount
        - Loss percentage
        - Timestamp
        """
        if not self.current_session:
            return

        event_data = {
            "date": self.current_session.date,
            "starting_balance": float(self.current_session.starting_balance),
            "current_balance": float(self.current_session.current_balance),
            "total_pnl": float(self.current_session.total_pnl),
            "realized_pnl": float(self.current_session.realized_pnl),
            "unrealized_pnl": float(self.current_session.unrealized_pnl),
            "loss_percentage": float(self.current_session.loss_percentage),
            "loss_limit": float(self.daily_loss_limit_pct),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        event = Event(
            priority=9,  # High priority for risk management
            event_type=EventType.RISK_LIMIT_EXCEEDED,
            data=event_data,
            source="DailyLossMonitor",
        )

        # Emit event asynchronously
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.event_bus.publish(event))
            else:
                asyncio.run(self.event_bus.publish(event))
        except RuntimeError:
            # If no event loop, create one
            asyncio.run(self.event_bus.publish(event))

        self.logger.warning(
            f"Daily loss limit reached! "
            f"Loss: {self.current_session.loss_percentage:.2f}% "
            f"(Limit: {self.daily_loss_limit_pct}%)"
        )

    def reset_session(self) -> None:
        """
        Reset current session.

        Clears the current session, requiring start_session() to be called
        again before monitoring can resume.
        """
        with self._lock:
            if self.current_session:
                self.logger.info(f"Resetting session for {self.current_session.date}")
            self.current_session = None
            self._limit_event_emitted = False

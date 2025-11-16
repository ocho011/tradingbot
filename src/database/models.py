"""
Database models for trading bot using SQLAlchemy ORM.

This module defines the database schema for:
- Trade history and execution records
- Position tracking (current and historical)
- Performance statistics (daily, monthly aggregates)
- Backtest results and configurations
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

from src.core.constants import TimeFrame

Base = declarative_base()


class Trade(Base):
    """
    Trade execution records.

    Stores complete information about each trade including entry/exit,
    profit/loss, and associated metadata.
    """

    __tablename__ = "trades"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Trade identification
    symbol = Column(String(20), nullable=False, index=True)
    strategy = Column(String(50), nullable=False, index=True)
    timeframe = Column(SQLEnum(TimeFrame), nullable=False)

    # Entry information
    entry_time = Column(DateTime(timezone=True), nullable=False, index=True)
    entry_price = Column(Numeric(precision=18, scale=8), nullable=False)

    # Exit information
    exit_time = Column(DateTime(timezone=True), nullable=True, index=True)
    exit_price = Column(Numeric(precision=18, scale=8), nullable=True)

    # Position details
    quantity = Column(Numeric(precision=18, scale=8), nullable=False)
    leverage = Column(Integer, nullable=False, default=1)
    side = Column(String(10), nullable=False)  # 'LONG' or 'SHORT'

    # Financial results
    pnl = Column(Numeric(precision=18, scale=8), nullable=True)  # Realized P&L
    pnl_percent = Column(Float, nullable=True)  # P&L percentage
    fees = Column(Numeric(precision=18, scale=8), nullable=True, default=0)

    # Trade metadata
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN, CLOSED, CANCELLED
    exit_reason = Column(String(50), nullable=True)  # TP, SL, MANUAL, SIGNAL
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    position = relationship("Position", back_populates="trades")

    # Indexes for query optimization
    __table_args__ = (
        Index("idx_trade_symbol_strategy", "symbol", "strategy"),
        Index("idx_trade_entry_time", "entry_time"),
        Index("idx_trade_exit_time", "exit_time"),
        Index("idx_trade_status", "status"),
        Index("idx_trade_pnl", "pnl"),
        CheckConstraint("quantity > 0", name="check_quantity_positive"),
        CheckConstraint("leverage > 0", name="check_leverage_positive"),
        CheckConstraint("side IN ('LONG', 'SHORT')", name="check_valid_side"),
        CheckConstraint("status IN ('OPEN', 'CLOSED', 'CANCELLED')", name="check_valid_status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id}, symbol='{self.symbol}', strategy='{self.strategy}', "
            f"side={self.side}, status={self.status}, pnl={self.pnl})>"
        )


class Position(Base):
    """
    Current and historical positions.

    Tracks open positions with real-time unrealized P&L and maintains
    historical records of closed positions.
    """

    __tablename__ = "positions"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Position identification
    symbol = Column(String(20), nullable=False, index=True)
    strategy = Column(String(50), nullable=False, index=True)
    timeframe = Column(SQLEnum(TimeFrame), nullable=False)

    # Position details
    side = Column(String(10), nullable=False)  # 'LONG' or 'SHORT'
    size = Column(Numeric(precision=18, scale=8), nullable=False)  # Current position size
    entry_price = Column(Numeric(precision=18, scale=8), nullable=False)
    current_price = Column(Numeric(precision=18, scale=8), nullable=True)
    leverage = Column(Integer, nullable=False, default=1)

    # Financial tracking
    unrealized_pnl = Column(Numeric(precision=18, scale=8), nullable=True, default=0)
    unrealized_pnl_percent = Column(Float, nullable=True, default=0)
    realized_pnl = Column(Numeric(precision=18, scale=8), nullable=True, default=0)
    total_fees = Column(Numeric(precision=18, scale=8), nullable=True, default=0)

    # Risk management
    stop_loss = Column(Numeric(precision=18, scale=8), nullable=True)
    take_profit = Column(Numeric(precision=18, scale=8), nullable=True)

    # Status tracking
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN, CLOSED
    opened_at = Column(DateTime(timezone=True), nullable=False, index=True)
    closed_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    trades = relationship("Trade", back_populates="position", cascade="all, delete-orphan")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_position_symbol_status", "symbol", "status"),
        Index("idx_position_strategy", "strategy"),
        Index("idx_position_opened_at", "opened_at"),
        UniqueConstraint("symbol", "strategy", "opened_at", name="uq_position_unique"),
        CheckConstraint("size > 0", name="check_size_positive"),
        CheckConstraint("leverage > 0", name="check_position_leverage_positive"),
        CheckConstraint("side IN ('LONG', 'SHORT')", name="check_position_valid_side"),
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="check_position_valid_status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Position(id={self.id}, symbol='{self.symbol}', strategy='{self.strategy}', "
            f"side={self.side}, size={self.size}, status={self.status}, unrealized_pnl={self.unrealized_pnl})>"
        )


class Statistics(Base):
    """
    Performance statistics aggregated by strategy and time period.

    Stores daily and monthly statistics for each trading strategy
    to track performance over time.
    """

    __tablename__ = "statistics"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identification
    strategy = Column(String(50), nullable=False, index=True)
    period_type = Column(String(10), nullable=False)  # 'DAILY' or 'MONTHLY'
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)

    # Trading metrics
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=True)  # Percentage

    # Financial metrics
    total_pnl = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    gross_profit = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    gross_loss = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    profit_factor = Column(Float, nullable=True)  # gross_profit / abs(gross_loss)

    # Performance metrics
    avg_win = Column(Numeric(precision=18, scale=8), nullable=True)
    avg_loss = Column(Numeric(precision=18, scale=8), nullable=True)
    largest_win = Column(Numeric(precision=18, scale=8), nullable=True)
    largest_loss = Column(Numeric(precision=18, scale=8), nullable=True)
    max_consecutive_wins = Column(Integer, nullable=True)
    max_consecutive_losses = Column(Integer, nullable=True)

    # Risk metrics
    sharpe_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)  # Percentage
    max_drawdown_duration = Column(Integer, nullable=True)  # Hours

    # Volume metrics
    total_volume = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    total_fees = Column(Numeric(precision=18, scale=8), nullable=False, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Indexes and constraints
    __table_args__ = (
        Index("idx_stats_strategy_period", "strategy", "period_type", "period_start"),
        UniqueConstraint("strategy", "period_type", "period_start", name="uq_stats_unique_period"),
        CheckConstraint("total_trades >= 0", name="check_total_trades_non_negative"),
        CheckConstraint("winning_trades >= 0", name="check_winning_trades_non_negative"),
        CheckConstraint("losing_trades >= 0", name="check_losing_trades_non_negative"),
        CheckConstraint("period_type IN ('DAILY', 'MONTHLY')", name="check_valid_period_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Statistics(id={self.id}, strategy='{self.strategy}', period_type={self.period_type}, "
            f"total_trades={self.total_trades}, win_rate={self.win_rate}, total_pnl={self.total_pnl})>"
        )


class BacktestResult(Base):
    """
    Backtest execution results and configurations.

    Stores complete backtest runs including configuration, performance metrics,
    and detailed results for historical analysis.
    """

    __tablename__ = "backtest_results"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Backtest identification
    name = Column(String(100), nullable=False)
    strategy = Column(String(50), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(SQLEnum(TimeFrame), nullable=False)

    # Test period
    start_date = Column(DateTime(timezone=True), nullable=False, index=True)
    end_date = Column(DateTime(timezone=True), nullable=False, index=True)

    # Performance metrics
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=True)

    # Financial results
    initial_capital = Column(Numeric(precision=18, scale=8), nullable=False)
    final_capital = Column(Numeric(precision=18, scale=8), nullable=False)
    total_return = Column(Float, nullable=False)  # Percentage
    total_pnl = Column(Numeric(precision=18, scale=8), nullable=False)

    # Risk metrics
    sharpe_ratio = Column(Float, nullable=True)
    sortino_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)  # Percentage
    max_drawdown_duration = Column(Integer, nullable=True)  # Hours
    calmar_ratio = Column(Float, nullable=True)

    # Trade metrics
    avg_trade_pnl = Column(Numeric(precision=18, scale=8), nullable=True)
    avg_win = Column(Numeric(precision=18, scale=8), nullable=True)
    avg_loss = Column(Numeric(precision=18, scale=8), nullable=True)
    profit_factor = Column(Float, nullable=True)
    largest_win = Column(Numeric(precision=18, scale=8), nullable=True)
    largest_loss = Column(Numeric(precision=18, scale=8), nullable=True)

    # Configuration (stored as JSON)
    configuration = Column(Text, nullable=False)  # JSON string with backtest parameters
    notes = Column(Text, nullable=True)

    # Metadata
    execution_time = Column(Float, nullable=True)  # Seconds
    data_points = Column(Integer, nullable=True)  # Number of candles processed

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Indexes and constraints
    __table_args__ = (
        Index("idx_backtest_strategy_symbol", "strategy", "symbol"),
        Index("idx_backtest_dates", "start_date", "end_date"),
        Index("idx_backtest_created", "created_at"),
        CheckConstraint("total_trades >= 0", name="check_backtest_total_trades"),
        CheckConstraint("initial_capital > 0", name="check_initial_capital_positive"),
        CheckConstraint("final_capital >= 0", name="check_final_capital_non_negative"),
    )

    def __repr__(self) -> str:
        return (
            f"<BacktestResult(id={self.id}, name='{self.name}', strategy='{self.strategy}', "
            f"symbol='{self.symbol}', total_return={self.total_return}%, sharpe={self.sharpe_ratio})>"
        )


class DailyPnL(Base):
    """
    Daily profit/loss tracking records.

    Stores daily session data including starting balance, P&L metrics,
    and loss limit status for risk management monitoring.
    """

    __tablename__ = "daily_pnl"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Session identification
    date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD

    # Balance tracking
    starting_balance = Column(Numeric(precision=18, scale=8), nullable=False)
    ending_balance = Column(Numeric(precision=18, scale=8), nullable=True)

    # P&L metrics
    realized_pnl = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    unrealized_pnl = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    total_pnl = Column(Numeric(precision=18, scale=8), nullable=False, default=0)
    pnl_percentage = Column(Float, nullable=False, default=0.0)

    # Risk management
    loss_limit_reached = Column(Boolean, nullable=False, default=False)
    loss_limit_percentage = Column(Float, nullable=False, default=6.0)

    # Trading activity
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)

    # Timestamps
    session_start = Column(DateTime(timezone=True), nullable=False)
    session_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Indexes and constraints
    __table_args__ = (
        Index("idx_daily_pnl_date", "date"),
        Index("idx_daily_pnl_session_start", "session_start"),
        Index("idx_daily_pnl_loss_limit", "loss_limit_reached"),
        CheckConstraint("starting_balance > 0", name="check_starting_balance_positive"),
        CheckConstraint("loss_limit_percentage > 0", name="check_loss_limit_positive"),
        CheckConstraint("total_trades >= 0", name="check_total_trades_non_negative"),
        CheckConstraint("winning_trades >= 0", name="check_winning_trades_non_negative"),
        CheckConstraint("losing_trades >= 0", name="check_losing_trades_non_negative"),
    )

    def __repr__(self) -> str:
        """String representation of DailyPnL."""
        return (
            f"<DailyPnL(date='{self.date}', "
            f"pnl={self.total_pnl}, "
            f"pnl_pct={self.pnl_percentage:.2f}%, "
            f"limit_reached={self.loss_limit_reached})>"
        )

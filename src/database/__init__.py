"""
Database package for trading bot.

Provides SQLAlchemy models, async engine configuration, and session management
for storing trade history, positions, statistics, and backtest results.
"""

from src.database.engine import (
    close_db,
    create_all_tables,
    drop_all_tables,
    get_engine,
    get_session,
    get_session_factory,
    health_check,
    init_db,
)
from src.database.models import BacktestResult, Base, DailyPnL, Position, Statistics, Trade

__all__ = [
    # Models
    "Base",
    "Trade",
    "Position",
    "Statistics",
    "BacktestResult",
    "DailyPnL",
    # Engine and session management
    "init_db",
    "close_db",
    "get_session",
    "get_engine",
    "get_session_factory",
    "create_all_tables",
    "drop_all_tables",
    "health_check",
]

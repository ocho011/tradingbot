"""
Database package for trading bot.

Provides SQLAlchemy models, async engine configuration, and session management
for storing trade history, positions, statistics, and backtest results.
"""

from src.database.models import Base, Trade, Position, Statistics, BacktestResult, DailyPnL
from src.database.engine import (
    init_db,
    close_db,
    get_session,
    get_engine,
    get_session_factory,
    create_all_tables,
    drop_all_tables,
    health_check,
)


__all__ = [
    # Models
    'Base',
    'Trade',
    'Position',
    'Statistics',
    'BacktestResult',
    'DailyPnL',
    # Engine and session management
    'init_db',
    'close_db',
    'get_session',
    'get_engine',
    'get_session_factory',
    'create_all_tables',
    'drop_all_tables',
    'health_check',
]

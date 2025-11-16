"""
Data Access Object (DAO) layer for database operations.

This module provides a clean abstraction layer for database CRUD operations
and complex queries across all trading bot entities.
"""

from src.database.dao.backtest_dao import BacktestResultDAO
from src.database.dao.base import BaseDAO
from src.database.dao.daily_pnl_dao import DailyPnLDAO
from src.database.dao.position_dao import PositionDAO
from src.database.dao.statistics_dao import StatisticsDAO
from src.database.dao.trade_dao import TradeDAO

__all__ = [
    "BaseDAO",
    "TradeDAO",
    "PositionDAO",
    "StatisticsDAO",
    "BacktestResultDAO",
    "DailyPnLDAO",
]

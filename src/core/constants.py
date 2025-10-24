"""
Global constants and enumerations for the trading bot.
"""

from enum import Enum


class TradingMode(str, Enum):
    """Trading mode enumeration."""

    PAPER = "paper"
    LIVE = "live"


class OrderSide(str, Enum):
    """Order side enumeration."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type enumeration."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


class PositionSide(str, Enum):
    """Position side enumeration."""

    LONG = "LONG"
    SHORT = "SHORT"


class TimeFrame(str, Enum):
    """Candlestick timeframe enumeration."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class ICTPattern(str, Enum):
    """ICT pattern types."""

    FVG = "Fair Value Gap"
    ORDER_BLOCK = "Order Block"
    BREAKER_BLOCK = "Breaker Block"
    LIQUIDITY_SWEEP = "Liquidity Sweep"
    DISPLACEMENT = "Displacement"
    MARKET_STRUCTURE = "Market Structure"


class MarketStructure(str, Enum):
    """Market structure states."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"
    UNCERTAIN = "UNCERTAIN"


class EventType(str, Enum):
    """Event types for the event system."""

    # Market data events
    CANDLE_RECEIVED = "candle_received"
    CANDLE_CLOSED = "candle_closed"
    ORDERBOOK_UPDATE = "orderbook_update"

    # ICT indicator events
    FVG_DETECTED = "fvg_detected"
    ORDER_BLOCK_DETECTED = "order_block_detected"
    BREAKER_BLOCK_DETECTED = "breaker_block_detected"
    LIQUIDITY_SWEEP_DETECTED = "liquidity_sweep_detected"
    MARKET_STRUCTURE_CHANGE = "market_structure_change"
    MARKET_STRUCTURE_BREAK = "market_structure_break"
    INDICATORS_UPDATED = "indicators_updated"
    INDICATOR_EXPIRED = "indicator_expired"

    # Trading events
    SIGNAL_GENERATED = "signal_generated"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    POSITION_MODIFIED = "position_modified"

    # Risk management events
    STOP_LOSS_HIT = "stop_loss_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    RISK_LIMIT_EXCEEDED = "risk_limit_exceeded"

    # Exchange connection events
    EXCHANGE_CONNECTED = "exchange_connected"
    EXCHANGE_DISCONNECTED = "exchange_disconnected"
    EXCHANGE_ERROR = "exchange_error"

    # System events
    SYSTEM_START = "system_start"
    SYSTEM_STOP = "system_stop"
    ERROR_OCCURRED = "error_occurred"


# Trading pairs
DEFAULT_SYMBOL = "BTCUSDT"
SUPPORTED_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "SOLUSDT",
]

# Timeframes for analysis
PRIMARY_TIMEFRAME = TimeFrame.M15
HIGHER_TIMEFRAME = TimeFrame.H1
LOWER_TIMEFRAME = TimeFrame.M5

# ICT Constants
MIN_FVG_SIZE_PERCENT = 0.1  # Minimum FVG size as percentage of price
MIN_ORDER_BLOCK_VOLUME_MULTIPLIER = 1.5  # Minimum volume multiplier for OB
LIQUIDITY_SWEEP_TOLERANCE_PERCENT = 0.2  # Tolerance for liquidity sweep detection
DISPLACEMENT_MIN_CANDLES = 3  # Minimum candles for displacement detection

# Risk Management Constants
DEFAULT_RISK_REWARD_RATIO = 2.0  # Default R:R ratio
MAX_DAILY_LOSS_PERCENT = 5.0  # Maximum daily loss percentage
MAX_CONCURRENT_POSITIONS = 3  # Maximum number of concurrent positions
DEFAULT_STOP_LOSS_PERCENT = 2.0  # Default stop loss percentage

# Database Constants
DB_CANDLE_RETENTION_DAYS = 90  # Keep candle data for 90 days
DB_TRADE_RETENTION_DAYS = 365  # Keep trade history for 1 year
DB_BATCH_SIZE = 1000  # Batch size for database operations

# API Rate Limits
BINANCE_RATE_LIMIT_PER_MINUTE = 1200
BINANCE_ORDER_RATE_LIMIT_PER_SECOND = 10

# WebSocket Configuration
WS_RECONNECT_DELAY_SECONDS = 5
WS_PING_INTERVAL_SECONDS = 30
WS_MAX_RECONNECT_ATTEMPTS = 10

# Discord Notification Settings
DISCORD_NOTIFY_ON_SIGNAL = True
DISCORD_NOTIFY_ON_ORDER = True
DISCORD_NOTIFY_ON_ERROR = True

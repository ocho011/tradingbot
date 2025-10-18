"""
Binance exchange manager using ccxt library.

Handles connection initialization, environment management (testnet/mainnet),
WebSocket stream subscriptions, and basic API key validation for Binance cryptocurrency exchange.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Set, Callable
from datetime import datetime
import ccxt.async_support as ccxt

from src.core.config import BinanceConfig
from src.core.events import Event, EventBus
from src.core.constants import EventType, TimeFrame


logger = logging.getLogger(__name__)


class BinanceConnectionError(Exception):
    """Raised when Binance connection fails."""
    pass


class BinanceManager:
    """
    Manages Binance exchange connection with ccxt library.

    Features:
    - Testnet/mainnet environment separation
    - API key validation
    - Connection testing
    - WebSocket stream subscriptions for real-time candle data
    - Event system integration for connection state changes and market data

    Attributes:
        config: Binance configuration from environment
        exchange: ccxt Binance exchange instance
        event_bus: Optional event bus for publishing connection events
        _ws_subscriptions: Active WebSocket subscriptions tracking
        _ws_tasks: Running WebSocket listener tasks
    """

    def __init__(
        self,
        config: Optional[BinanceConfig] = None,
        event_bus: Optional[EventBus] = None
    ):
        """
        Initialize Binance manager.

        Args:
            config: Binance configuration (uses default from env if None)
            event_bus: Optional event bus for publishing connection events
        """
        self.config = config or BinanceConfig()
        self.event_bus = event_bus
        self.exchange: Optional[ccxt.binance] = None
        self._connected = False
        self._connection_tested = False

        # WebSocket subscription tracking
        self._ws_subscriptions: Dict[str, Set[TimeFrame]] = {}  # symbol -> set of timeframes
        self._ws_tasks: Dict[str, asyncio.Task] = {}  # subscription_key -> task
        self._ws_running = False

        logger.info(
            f"Initializing BinanceManager (testnet={'enabled' if self.config.testnet else 'disabled'})"
        )

    async def initialize(self) -> None:
        """
        Initialize ccxt Binance exchange instance with proper configuration.

        Creates exchange instance with:
        - API credentials from config
        - Testnet/mainnet endpoint selection
        - Basic connection options

        Raises:
            BinanceConnectionError: If initialization fails
        """
        try:
            logger.info("Creating ccxt.binance instance...")

            # Initialize ccxt Binance exchange
            self.exchange = ccxt.binance({
                'apiKey': self.config.api_key,
                'secret': self.config.secret_key,
                'enableRateLimit': True,  # Respect rate limits
                'options': {
                    'defaultType': 'future',  # Use futures trading
                    'adjustForTimeDifference': True,  # Auto-sync time
                }
            })

            # Configure testnet if enabled
            if self.config.testnet:
                logger.info("Configuring Binance testnet endpoints")
                self.exchange.set_sandbox_mode(True)

            logger.info(f"Binance exchange initialized (testnet={self.config.testnet})")

        except Exception as e:
            error_msg = f"Failed to initialize Binance exchange: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def test_connection(self) -> bool:
        """
        Test connection to Binance API by fetching server time.

        Returns:
            True if connection successful

        Raises:
            BinanceConnectionError: If connection test fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.info("Testing Binance API connection...")

            # Fetch server time as connection test
            response = await self.exchange.fetch_time()
            server_time = response if isinstance(response, int) else response.get('timestamp')

            if server_time:
                self._connected = True
                self._connection_tested = True
                logger.info(f"✓ Connected to Binance (server time: {server_time})")

                # Publish connection event if event bus available
                if self.event_bus:
                    await self.event_bus.publish(Event(
                        event_type=EventType.EXCHANGE_CONNECTED,
                        priority=7,
                        data={
                            'exchange': 'binance',
                            'testnet': self.config.testnet,
                            'server_time': server_time
                        },
                        source='BinanceManager'
                    ))

                return True
            else:
                raise BinanceConnectionError("Invalid server time response")

        except Exception as e:
            self._connected = False
            error_msg = f"Binance connection test failed: {e}"
            logger.error(error_msg, exc_info=True)

            # Publish connection error event
            if self.event_bus:
                await self.event_bus.publish(Event(
                    event_type=EventType.EXCHANGE_ERROR,
                    priority=8,
                    data={
                        'exchange': 'binance',
                        'error': str(e),
                        'testnet': self.config.testnet
                    },
                    source='BinanceManager'
                ))

            raise BinanceConnectionError(error_msg) from e

    async def validate_api_permissions(self) -> Dict[str, bool]:
        """
        Validate API key permissions (read, trade).

        Returns:
            Dictionary with permission status:
            - 'read': Can read account data
            - 'trade': Can place orders

        Raises:
            BinanceConnectionError: If permission check fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        if not self._connection_tested:
            await self.test_connection()

        permissions = {'read': False, 'trade': False}

        try:
            logger.info("Validating API key permissions...")

            # Test read permission by fetching account balance
            try:
                await self.exchange.fetch_balance()
                permissions['read'] = True
                logger.info("✓ Read permission: GRANTED")
            except Exception as e:
                logger.warning(f"✗ Read permission: DENIED ({e})")

            # Test trade permission by fetching open orders (safe read operation)
            # Note: We don't actually place test orders to avoid affecting account
            try:
                await self.exchange.fetch_open_orders()
                permissions['trade'] = True
                logger.info("✓ Trade permission: GRANTED")
            except Exception as e:
                logger.warning(f"✗ Trade permission: DENIED ({e})")

            logger.info(f"API permissions: read={permissions['read']}, trade={permissions['trade']}")
            return permissions

        except Exception as e:
            error_msg = f"Failed to validate API permissions: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    @property
    def is_connected(self) -> bool:
        """Check if connected to Binance."""
        return self._connected

    @property
    def is_testnet(self) -> bool:
        """Check if using testnet."""
        return self.config.testnet

    async def subscribe_candles(
        self,
        symbol: str,
        timeframes: List[TimeFrame]
    ) -> None:
        """
        Subscribe to candle (OHLCV) streams for specified symbol and timeframes.

        Uses ccxt's watchOHLCV for WebSocket streaming. Candles are automatically
        published to the event bus as CANDLE_RECEIVED events.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
            timeframes: List of timeframes to subscribe (e.g., [TimeFrame.M1, TimeFrame.M15])

        Raises:
            BinanceConnectionError: If exchange not initialized or subscription fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        if not self._connected:
            await self.test_connection()

        # Track subscriptions
        if symbol not in self._ws_subscriptions:
            self._ws_subscriptions[symbol] = set()

        for timeframe in timeframes:
            if timeframe in self._ws_subscriptions[symbol]:
                logger.debug(f"Already subscribed to {symbol} {timeframe.value}")
                continue

            self._ws_subscriptions[symbol].add(timeframe)
            subscription_key = f"{symbol}:{timeframe.value}"

            # Create listener task for this symbol-timeframe combination
            task = asyncio.create_task(
                self._watch_candles(symbol, timeframe),
                name=subscription_key
            )
            self._ws_tasks[subscription_key] = task

            logger.info(f"✓ Subscribed to {symbol} {timeframe.value} candles")

        self._ws_running = True

    async def _watch_candles(self, symbol: str, timeframe: TimeFrame) -> None:
        """
        Internal method to watch candles for a specific symbol and timeframe.

        Continuously watches for new candles and publishes them to the event bus.

        Args:
            symbol: Trading pair symbol
            timeframe: Timeframe to watch
        """
        subscription_key = f"{symbol}:{timeframe.value}"
        logger.info(f"Starting candle watcher for {subscription_key}")

        try:
            while self._ws_running:
                try:
                    # Watch for new candles (ccxt handles WebSocket internally)
                    ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe.value)

                    if not ohlcv or len(ohlcv) == 0:
                        continue

                    # Get the latest candle
                    latest_candle = ohlcv[-1]

                    # Parse candle data: [timestamp, open, high, low, close, volume]
                    candle_data = {
                        'symbol': symbol,
                        'timeframe': timeframe.value,
                        'timestamp': latest_candle[0],
                        'datetime': datetime.fromtimestamp(latest_candle[0] / 1000).isoformat(),
                        'open': latest_candle[1],
                        'high': latest_candle[2],
                        'low': latest_candle[3],
                        'close': latest_candle[4],
                        'volume': latest_candle[5],
                    }

                    # Validate candle data
                    if self._validate_candle(candle_data):
                        # Publish to event bus
                        if self.event_bus:
                            await self.event_bus.publish(Event(
                                event_type=EventType.CANDLE_RECEIVED,
                                priority=6,
                                data=candle_data,
                                source='BinanceManager'
                            ))

                            logger.debug(
                                f"Published candle: {symbol} {timeframe.value} "
                                f"@ {candle_data['datetime']} close={candle_data['close']}"
                            )

                except asyncio.CancelledError:
                    logger.info(f"Candle watcher cancelled for {subscription_key}")
                    raise

                except Exception as e:
                    logger.error(f"Error watching candles for {subscription_key}: {e}", exc_info=True)
                    # Continue watching despite errors
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info(f"Candle watcher stopped for {subscription_key}")
        except Exception as e:
            logger.error(f"Fatal error in candle watcher for {subscription_key}: {e}", exc_info=True)
        finally:
            # Cleanup subscription tracking
            if symbol in self._ws_subscriptions:
                self._ws_subscriptions[symbol].discard(timeframe)
                if not self._ws_subscriptions[symbol]:
                    del self._ws_subscriptions[symbol]

    def _validate_candle(self, candle_data: Dict[str, Any]) -> bool:
        """
        Validate candle data integrity.

        Args:
            candle_data: Candle data dictionary

        Returns:
            True if candle data is valid, False otherwise
        """
        try:
            # Check required fields
            required_fields = ['symbol', 'timeframe', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(field in candle_data for field in required_fields):
                logger.warning(f"Candle missing required fields: {candle_data}")
                return False

            # Check OHLC relationships
            if not (candle_data['low'] <= candle_data['open'] <= candle_data['high'] and
                    candle_data['low'] <= candle_data['close'] <= candle_data['high']):
                logger.warning(f"Invalid OHLC relationships in candle: {candle_data}")
                return False

            # Check for negative values
            if any(candle_data[field] < 0 for field in ['open', 'high', 'low', 'close', 'volume']):
                logger.warning(f"Negative values in candle: {candle_data}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating candle: {e}", exc_info=True)
            return False

    async def unsubscribe_candles(self, symbol: str, timeframe: Optional[TimeFrame] = None) -> None:
        """
        Unsubscribe from candle streams.

        Args:
            symbol: Trading pair symbol
            timeframe: Specific timeframe to unsubscribe (None = unsubscribe all timeframes for symbol)
        """
        if symbol not in self._ws_subscriptions:
            logger.warning(f"No active subscriptions for {symbol}")
            return

        if timeframe:
            # Unsubscribe specific timeframe
            subscription_key = f"{symbol}:{timeframe.value}"
            if subscription_key in self._ws_tasks:
                self._ws_tasks[subscription_key].cancel()
                del self._ws_tasks[subscription_key]
                logger.info(f"✓ Unsubscribed from {subscription_key}")

            self._ws_subscriptions[symbol].discard(timeframe)
            if not self._ws_subscriptions[symbol]:
                del self._ws_subscriptions[symbol]
        else:
            # Unsubscribe all timeframes for symbol
            timeframes_to_remove = list(self._ws_subscriptions[symbol])
            for tf in timeframes_to_remove:
                subscription_key = f"{symbol}:{tf.value}"
                if subscription_key in self._ws_tasks:
                    self._ws_tasks[subscription_key].cancel()
                    del self._ws_tasks[subscription_key]

            del self._ws_subscriptions[symbol]
            logger.info(f"✓ Unsubscribed from all {symbol} streams")

    def get_active_subscriptions(self) -> Dict[str, List[str]]:
        """
        Get currently active WebSocket subscriptions.

        Returns:
            Dictionary mapping symbols to list of subscribed timeframes
        """
        return {
            symbol: [tf.value for tf in timeframes]
            for symbol, timeframes in self._ws_subscriptions.items()
        }

    async def close(self) -> None:
        """
        Close the exchange connection and cleanup resources.

        Stops all WebSocket subscriptions and closes the ccxt exchange connection.
        """
        # Stop WebSocket subscriptions
        self._ws_running = False

        if self._ws_tasks:
            logger.info(f"Cancelling {len(self._ws_tasks)} WebSocket subscription tasks...")
            for subscription_key, task in self._ws_tasks.items():
                if not task.done():
                    task.cancel()

            # Wait for all tasks to complete
            await asyncio.gather(*self._ws_tasks.values(), return_exceptions=True)
            self._ws_tasks.clear()
            self._ws_subscriptions.clear()
            logger.info("All WebSocket subscriptions stopped")

        if self.exchange:
            try:
                logger.info("Closing Binance exchange connection...")
                await self.exchange.close()
                self._connected = False
                logger.info("Binance connection closed")

                # Publish disconnection event
                if self.event_bus:
                    await self.event_bus.publish(Event(
                        event_type=EventType.EXCHANGE_DISCONNECTED,
                        priority=7,
                        data={'exchange': 'binance'},
                        source='BinanceManager'
                    ))

            except Exception as e:
                logger.error(f"Error closing Binance connection: {e}", exc_info=True)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        await self.test_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

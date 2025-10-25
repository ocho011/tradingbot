"""
Binance exchange manager using ccxt library.

Handles connection initialization, environment management (testnet/mainnet),
WebSocket stream subscriptions, and basic API key validation for Binance cryptocurrency exchange.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
import ccxt.pro as ccxt

from src.core.config import BinanceConfig
from src.core.events import Event, EventBus
from src.core.constants import EventType, TimeFrame
from src.services.exchange.permissions import PermissionVerifier, PermissionType


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

        # Heartbeat monitoring
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_running = False
        self._last_heartbeat_time: Optional[float] = None
        self._heartbeat_interval = 30  # seconds
        self._heartbeat_timeout = 60  # seconds
        self._ws_connection_healthy = False

        # Reconnection configuration with exponential backoff
        self._reconnect_enabled = True
        self._reconnect_base_delay = 1.0  # seconds - initial delay
        self._reconnect_max_delay = 60.0  # seconds - maximum delay
        self._reconnect_max_retries = 10  # maximum reconnection attempts
        self._reconnect_attempts = 0
        self._reconnect_current_delay = self._reconnect_base_delay
        self._reconnect_task: Optional[asyncio.Task] = None
        self._is_reconnecting = False

        # Permission verification system (initialized after exchange setup)
        self._permission_verifier: Optional[PermissionVerifier] = None

        logger.info(
            f"Initializing BinanceManager (testnet={'enabled' if self.config.testnet else 'disabled'})"
        )

    async def initialize(self) -> None:
        """
        Initialize ccxt Binance exchange instance with proper configuration.

        Creates exchange instance with:
        - API credentials from config (auto-selected based on testnet setting)
        - Testnet/mainnet endpoint selection
        - Basic connection options

        Raises:
            BinanceConnectionError: If initialization fails
            ValueError: If credentials are missing for the selected environment
        """
        try:
            # Validate credentials before initialization
            self.config.validate_credentials()

            env_name = "testnet" if self.config.testnet else "mainnet"
            logger.info(f"Creating ccxt.binance instance for {env_name}...")

            # Initialize ccxt Binance exchange with active credentials
            self.exchange = ccxt.binance({
                'apiKey': self.config.active_api_key,
                'secret': self.config.active_secret_key,
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

            # Initialize permission verifier
            self._permission_verifier = PermissionVerifier(
                exchange=self.exchange,
                event_bus=self.event_bus,
                cache_ttl=3600,  # 1 hour cache
                revalidate_interval=3600  # Re-validate every hour
            )

            logger.info(f"Binance exchange initialized (testnet={self.config.testnet})")

        except ValueError as e:
            # Re-raise credential validation errors with clear message
            logger.error(f"Credential validation failed: {e}")
            raise BinanceConnectionError(str(e)) from e
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

    async def validate_api_permissions(
        self,
        force_refresh: bool = False,
        start_monitoring: bool = True
    ) -> Dict[str, bool]:
        """
        Validate API key permissions with enhanced caching and monitoring.

        This method uses the PermissionVerifier system which provides:
        - Permission caching with 1-hour TTL
        - Automatic periodic re-validation
        - Change detection and event notifications
        - Error tracking and alerts

        Args:
            force_refresh: Force fresh verification ignoring cache
            start_monitoring: Start periodic re-validation if not already running

        Returns:
            Dictionary with permission status:
            - 'read': Can read account data
            - 'trade': Can place orders

        Raises:
            BinanceConnectionError: If permission check fails and no cache available
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        if not self._permission_verifier:
            raise BinanceConnectionError("Permission verifier not initialized.")

        if not self._connection_tested:
            await self.test_connection()

        try:
            # Use the enhanced permission verifier
            permissions = await self._permission_verifier.verify_permissions(
                force_refresh=force_refresh
            )

            # Start periodic monitoring if requested and not already running
            if start_monitoring and not self._permission_verifier.is_validation_running:
                await self._permission_verifier.start_periodic_validation()

            return permissions

        except Exception as e:
            error_msg = f"Failed to validate API permissions: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    def get_permission_status(self) -> Dict[str, Any]:
        """
        Get detailed permission status information.

        Returns:
            Dictionary containing:
            - 'read': Read permission status
            - 'trade': Trade permission status
            - 'last_checked': Last verification timestamp
            - 'last_changed': Last permission change timestamp
            - 'check_count': Number of verifications performed
            - 'error_count': Number of verification errors

        Raises:
            BinanceConnectionError: If permission verifier not initialized
        """
        if not self._permission_verifier:
            raise BinanceConnectionError("Permission verifier not initialized.")

        return self._permission_verifier.get_status()

    def has_permission(self, permission_type: PermissionType) -> bool:
        """
        Check if a specific permission is granted.

        Args:
            permission_type: Type of permission to check

        Returns:
            True if permission is granted, False otherwise

        Raises:
            BinanceConnectionError: If permission verifier not initialized
        """
        if not self._permission_verifier:
            raise BinanceConnectionError("Permission verifier not initialized.")

        return self._permission_verifier.is_permission_granted(permission_type)

    async def start_permission_monitoring(self) -> None:
        """
        Start periodic permission re-validation.

        Automatically re-validates permissions every hour and publishes
        change events when permissions are modified.

        Raises:
            BinanceConnectionError: If permission verifier not initialized
        """
        if not self._permission_verifier:
            raise BinanceConnectionError("Permission verifier not initialized.")

        await self._permission_verifier.start_periodic_validation()

    async def stop_permission_monitoring(self) -> None:
        """
        Stop periodic permission re-validation.

        Raises:
            BinanceConnectionError: If permission verifier not initialized
        """
        if not self._permission_verifier:
            raise BinanceConnectionError("Permission verifier not initialized.")

        await self._permission_verifier.stop_periodic_validation()

    # ========== REST API Wrapper Methods ==========

    async def fetch_balance(self) -> Dict[str, Any]:
        """
        Fetch account balance information.

        Returns:
            Dictionary containing:
            - 'free': Available balances per currency
            - 'used': Balances in active orders per currency
            - 'total': Total balances per currency
            - Asset-specific details with free/used/total amounts

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug("Fetching account balance...")
            balance = await self.exchange.fetch_balance()
            logger.debug(f"Balance retrieved: {len(balance.get('info', {}))} assets")
            return balance

        except Exception as e:
            error_msg = f"Failed to fetch balance: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_positions(self, symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Fetch open positions information.

        Args:
            symbols: Optional list of symbols to fetch positions for.
                    If None, fetches all open positions.

        Returns:
            List of position dictionaries containing:
            - 'symbol': Trading pair
            - 'side': 'long' or 'short'
            - 'contracts': Position size in contracts
            - 'contractSize': Contract size
            - 'unrealizedPnl': Unrealized profit/loss
            - 'leverage': Position leverage
            - 'liquidationPrice': Liquidation price
            - 'entryPrice': Average entry price
            - 'markPrice': Current mark price
            - Additional position details

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching positions for {symbols if symbols else 'all symbols'}...")
            positions = await self.exchange.fetch_positions(symbols)

            # Filter out zero positions
            active_positions = [p for p in positions if float(p.get('contracts', 0)) != 0]

            logger.debug(f"Retrieved {len(active_positions)} active positions (of {len(positions)} total)")
            return active_positions

        except Exception as e:
            error_msg = f"Failed to fetch positions: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch order history.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT'). If None, fetches all symbols.
            since: Timestamp in milliseconds to fetch orders from
            limit: Maximum number of orders to return

        Returns:
            List of order dictionaries containing:
            - 'id': Order ID
            - 'symbol': Trading pair
            - 'type': Order type (market, limit, etc.)
            - 'side': 'buy' or 'sell'
            - 'price': Order price
            - 'amount': Order amount
            - 'cost': Total cost
            - 'filled': Filled amount
            - 'remaining': Remaining amount
            - 'status': Order status (open, closed, canceled)
            - 'timestamp': Order creation time
            - Additional order details

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching orders for {symbol or 'all symbols'}...")
            orders = await self.exchange.fetch_orders(symbol, since, limit)
            logger.debug(f"Retrieved {len(orders)} orders")
            return orders

        except Exception as e:
            error_msg = f"Failed to fetch orders: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_open_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch currently open orders.

        Args:
            symbol: Trading pair symbol. If None, fetches for all symbols.
            since: Timestamp in milliseconds
            limit: Maximum number of orders to return

        Returns:
            List of open order dictionaries (same format as fetch_orders)

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching open orders for {symbol or 'all symbols'}...")
            orders = await self.exchange.fetch_open_orders(symbol, since, limit)
            logger.debug(f"Retrieved {len(orders)} open orders")
            return orders

        except Exception as e:
            error_msg = f"Failed to fetch open orders: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_closed_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch closed (filled/canceled) orders.

        Args:
            symbol: Trading pair symbol. If None, fetches for all symbols.
            since: Timestamp in milliseconds
            limit: Maximum number of orders to return

        Returns:
            List of closed order dictionaries (same format as fetch_orders)

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching closed orders for {symbol or 'all symbols'}...")
            orders = await self.exchange.fetch_closed_orders(symbol, since, limit)
            logger.debug(f"Retrieved {len(orders)} closed orders")
            return orders

        except Exception as e:
            error_msg = f"Failed to fetch closed orders: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch current ticker data for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')

        Returns:
            Dictionary containing:
            - 'symbol': Trading pair
            - 'last': Last traded price
            - 'bid': Highest bid price
            - 'ask': Lowest ask price
            - 'high': 24h high
            - 'low': 24h low
            - 'volume': 24h volume
            - 'quoteVolume': 24h quote currency volume
            - 'timestamp': Ticker timestamp
            - Additional ticker data

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching ticker for {symbol}...")
            ticker = await self.exchange.fetch_ticker(symbol)
            logger.debug(f"Ticker retrieved: {symbol} @ {ticker.get('last')}")
            return ticker

        except Exception as e:
            error_msg = f"Failed to fetch ticker for {symbol}: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[List]:
        """
        Fetch OHLCV (candlestick) data.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d', etc.)
            since: Timestamp in milliseconds to fetch from
            limit: Maximum number of candles to return (default: 500, max: 1000)

        Returns:
            List of OHLCV arrays, each containing:
            [timestamp, open, high, low, close, volume]

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching OHLCV for {symbol} {timeframe}...")
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            logger.debug(f"Retrieved {len(ohlcv)} candles for {symbol} {timeframe}")
            return ohlcv

        except Exception as e:
            error_msg = f"Failed to fetch OHLCV for {symbol} {timeframe}: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_order_book(self, symbol: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Fetch order book (market depth) for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            limit: Order book depth limit (5, 10, 20, 50, 100, 500, 1000, 5000)

        Returns:
            Dictionary containing:
            - 'symbol': Trading pair
            - 'bids': List of [price, amount] bid orders (sorted high to low)
            - 'asks': List of [price, amount] ask orders (sorted low to high)
            - 'timestamp': Order book timestamp
            - 'datetime': ISO datetime string

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching order book for {symbol} (limit={limit})...")
            order_book = await self.exchange.fetch_order_book(symbol, limit)
            logger.debug(
                f"Order book retrieved: {symbol} "
                f"({len(order_book['bids'])} bids, {len(order_book['asks'])} asks)"
            )
            return order_book

        except Exception as e:
            error_msg = f"Failed to fetch order book for {symbol}: {e}"
            logger.error(error_msg, exc_info=True)
            raise BinanceConnectionError(error_msg) from e

    async def fetch_trading_fees(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch trading fees for symbol(s).

        Args:
            symbol: Trading pair symbol. If None, fetches fees for all symbols.

        Returns:
            Dictionary mapping symbols to fee information:
            - 'maker': Maker fee rate (e.g., 0.0002 for 0.02%)
            - 'taker': Taker fee rate
            - Additional fee details

        Raises:
            BinanceConnectionError: If exchange not initialized or API call fails
        """
        if not self.exchange:
            raise BinanceConnectionError("Exchange not initialized. Call initialize() first.")

        try:
            logger.debug(f"Fetching trading fees for {symbol or 'all symbols'}...")
            fees = await self.exchange.fetch_trading_fees()

            if symbol and symbol in fees:
                return {symbol: fees[symbol]}
            return fees

        except Exception as e:
            error_msg = f"Failed to fetch trading fees: {e}"
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

        # Start heartbeat monitor if not already running
        if not self._heartbeat_running:
            await self.start_heartbeat_monitor()

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

    async def _heartbeat_monitor(self) -> None:
        """
        Monitor WebSocket connection health through periodic heartbeat checks.

        Sends periodic pings and monitors responses to detect connection issues.
        Publishes connection state change events when health status changes.
        """
        logger.info("Starting heartbeat monitor")

        try:
            while self._heartbeat_running and self._ws_running:
                try:
                    current_time = time.time()

                    # Check if we have an active connection
                    if self.exchange and self._ws_subscriptions:
                        # Send a lightweight request to verify connection
                        # Using fetch_time as it's a simple, fast endpoint
                        ping_start = time.time()
                        await self.exchange.fetch_time()
                        response_time = time.time() - ping_start

                        # Update heartbeat time
                        self._last_heartbeat_time = current_time

                        # Check if connection was previously unhealthy
                        if not self._ws_connection_healthy:
                            self._ws_connection_healthy = True
                            logger.info(f"✓ WebSocket connection restored (response time: {response_time:.3f}s)")

                            # Publish connection restored event
                            if self.event_bus:
                                await self.event_bus.publish(Event(
                                    event_type=EventType.EXCHANGE_CONNECTED,
                                    priority=7,
                                    data={
                                        'exchange': 'binance',
                                        'testnet': self.config.testnet,
                                        'response_time': response_time,
                                        'message': 'WebSocket connection restored'
                                    },
                                    source='BinanceManager.Heartbeat'
                                ))
                        else:
                            logger.debug(f"Heartbeat OK (response time: {response_time:.3f}s)")

                    # Check for timeout
                    elif self._last_heartbeat_time:
                        time_since_last = current_time - self._last_heartbeat_time
                        if time_since_last > self._heartbeat_timeout:
                            if self._ws_connection_healthy:
                                self._ws_connection_healthy = False
                                logger.warning(f"⚠ WebSocket connection timeout detected ({time_since_last:.1f}s)")

                                # Publish connection lost event
                                if self.event_bus:
                                    await self.event_bus.publish(Event(
                                        event_type=EventType.EXCHANGE_DISCONNECTED,
                                        priority=8,
                                        data={
                                            'exchange': 'binance',
                                            'reason': 'heartbeat_timeout',
                                            'timeout_seconds': time_since_last
                                        },
                                        source='BinanceManager.Heartbeat'
                                    ))

                                # Trigger reconnection
                                if self._reconnect_enabled and not self._is_reconnecting:
                                    logger.info("Triggering automatic reconnection...")
                                    asyncio.create_task(self._reconnect())

                except asyncio.CancelledError:
                    logger.info("Heartbeat monitor cancelled")
                    raise

                except Exception as e:
                    logger.error(f"Error in heartbeat monitor: {e}", exc_info=True)

                    # Mark connection as unhealthy on errors
                    if self._ws_connection_healthy:
                        self._ws_connection_healthy = False
                        logger.warning("⚠ WebSocket connection marked unhealthy due to heartbeat error")

                        # Publish connection error event
                        if self.event_bus:
                            await self.event_bus.publish(Event(
                                event_type=EventType.EXCHANGE_ERROR,
                                priority=8,
                                data={
                                    'exchange': 'binance',
                                    'error': str(e),
                                    'source': 'heartbeat_monitor'
                                },
                                source='BinanceManager.Heartbeat'
                            ))

                        # Trigger reconnection on heartbeat errors
                        if self._reconnect_enabled and not self._is_reconnecting:
                            logger.info("Triggering reconnection after heartbeat error...")
                            asyncio.create_task(self._reconnect())

                # Wait for next heartbeat interval
                await asyncio.sleep(self._heartbeat_interval)

        except asyncio.CancelledError:
            logger.info("Heartbeat monitor stopped")
        except Exception as e:
            logger.error(f"Fatal error in heartbeat monitor: {e}", exc_info=True)
        finally:
            self._heartbeat_running = False
            logger.info("Heartbeat monitor terminated")

    async def start_heartbeat_monitor(self) -> None:
        """
        Start the heartbeat monitoring system.

        Should be called after WebSocket subscriptions are active.
        """
        if self._heartbeat_running:
            logger.debug("Heartbeat monitor already running")
            return

        if not self._ws_running:
            logger.warning("Cannot start heartbeat monitor: WebSocket not running")
            return

        self._heartbeat_running = True
        self._last_heartbeat_time = time.time()
        self._ws_connection_healthy = True

        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_monitor(),
            name="heartbeat_monitor"
        )

        logger.info(f"✓ Heartbeat monitor started (interval: {self._heartbeat_interval}s, timeout: {self._heartbeat_timeout}s)")

    async def stop_heartbeat_monitor(self) -> None:
        """
        Stop the heartbeat monitoring system.
        """
        if not self._heartbeat_running:
            return

        logger.info("Stopping heartbeat monitor...")
        self._heartbeat_running = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        self._heartbeat_task = None
        self._ws_connection_healthy = False
        logger.info("Heartbeat monitor stopped")

    @property
    def is_websocket_healthy(self) -> bool:
        """Check if WebSocket connection is healthy based on heartbeat monitoring."""
        return self._ws_connection_healthy and self._heartbeat_running

    async def _reconnect(self) -> None:
        """
        Implement exponential backoff reconnection logic.

        Automatically attempts to reconnect when WebSocket connection drops.
        Uses exponential backoff: 1s, 2s, 4s, 8s, ... up to max 60s.
        Resets delay on successful reconnection.
        """
        if self._is_reconnecting:
            logger.debug("Reconnection already in progress")
            return

        self._is_reconnecting = True
        logger.info(f"Starting reconnection process (attempt 1/{self._reconnect_max_retries})")

        try:
            while self._reconnect_attempts < self._reconnect_max_retries:
                self._reconnect_attempts += 1

                # Log reconnection attempt
                logger.info(
                    f"Reconnection attempt {self._reconnect_attempts}/{self._reconnect_max_retries} "
                    f"(delay: {self._reconnect_current_delay:.1f}s)"
                )

                # Publish reconnection attempt event
                if self.event_bus:
                    await self.event_bus.publish(Event(
                        event_type=EventType.EXCHANGE_ERROR,
                        priority=7,
                        data={
                            'exchange': 'binance',
                            'event': 'reconnection_attempt',
                            'attempt': self._reconnect_attempts,
                            'max_attempts': self._reconnect_max_retries,
                            'delay': self._reconnect_current_delay
                        },
                        source='BinanceManager.Reconnect'
                    ))

                # Wait with exponential backoff delay
                await asyncio.sleep(self._reconnect_current_delay)

                try:
                    # Attempt to reconnect by testing connection
                    logger.info("Testing connection...")
                    await self.exchange.fetch_time()

                    # Connection successful - reset state
                    logger.info("✓ Reconnection successful!")
                    self._reconnect_attempts = 0
                    self._reconnect_current_delay = self._reconnect_base_delay
                    self._ws_connection_healthy = True
                    self._last_heartbeat_time = time.time()

                    # Publish successful reconnection event
                    if self.event_bus:
                        await self.event_bus.publish(Event(
                            event_type=EventType.EXCHANGE_CONNECTED,
                            priority=7,
                            data={
                                'exchange': 'binance',
                                'event': 'reconnection_successful',
                                'attempts_taken': self._reconnect_attempts
                            },
                            source='BinanceManager.Reconnect'
                        ))

                    # Resubscribe to all previous streams
                    if self._ws_subscriptions:
                        logger.info("Resubscribing to WebSocket streams...")
                        for symbol, timeframes in list(self._ws_subscriptions.items()):
                            for timeframe in timeframes:
                                subscription_key = f"{symbol}:{timeframe.value}"
                                # Check if task still exists and is running
                                if subscription_key not in self._ws_tasks or self._ws_tasks[subscription_key].done():
                                    # Recreate the task
                                    task = asyncio.create_task(
                                        self._watch_candles(symbol, timeframe),
                                        name=subscription_key
                                    )
                                    self._ws_tasks[subscription_key] = task
                                    logger.info(f"✓ Resubscribed to {subscription_key}")

                    return  # Exit reconnection loop on success

                except Exception as e:
                    logger.warning(f"Reconnection attempt {self._reconnect_attempts} failed: {e}")

                    # Calculate next delay with exponential backoff
                    self._reconnect_current_delay = min(
                        self._reconnect_current_delay * 2,
                        self._reconnect_max_delay
                    )

                    # Check if max retries reached
                    if self._reconnect_attempts >= self._reconnect_max_retries:
                        logger.error(
                            f"✗ Maximum reconnection attempts ({self._reconnect_max_retries}) reached. "
                            "Reconnection failed."
                        )

                        # Publish max retries exceeded event
                        if self.event_bus:
                            await self.event_bus.publish(Event(
                                event_type=EventType.EXCHANGE_ERROR,
                                priority=9,
                                data={
                                    'exchange': 'binance',
                                    'event': 'reconnection_failed',
                                    'reason': 'max_retries_exceeded',
                                    'attempts': self._reconnect_attempts,
                                    'last_error': str(e)
                                },
                                source='BinanceManager.Reconnect'
                            ))

                        break

        except asyncio.CancelledError:
            logger.info("Reconnection process cancelled")
            raise
        except Exception as e:
            logger.error(f"Fatal error in reconnection process: {e}", exc_info=True)
        finally:
            self._is_reconnecting = False
            logger.info("Reconnection process ended")

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

        Stops all WebSocket subscriptions, heartbeat monitor, permission monitoring,
        and closes the ccxt exchange connection.
        """
        # Stop permission monitoring
        if self._permission_verifier:
            await self.stop_permission_monitoring()

        # Stop heartbeat monitor
        await self.stop_heartbeat_monitor()

        # Stop WebSocket subscriptions
        self._ws_running = False

        if self._ws_tasks:
            logger.info(f"Cancelling {len(self._ws_tasks)} WebSocket subscription tasks...")
            for task in self._ws_tasks.values():
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

"""
Binance exchange manager using ccxt library.

Handles connection initialization, environment management (testnet/mainnet),
and basic API key validation for Binance cryptocurrency exchange.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import ccxt.async_support as ccxt

from src.core.config import BinanceConfig
from src.core.events import Event, EventBus
from src.core.constants import EventType


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
    - Event system integration for connection state changes

    Attributes:
        config: Binance configuration from environment
        exchange: ccxt Binance exchange instance
        event_bus: Optional event bus for publishing connection events
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

    async def close(self) -> None:
        """
        Close the exchange connection and cleanup resources.
        """
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

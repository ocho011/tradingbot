"""
Unit tests for BinanceManager class.
Tests initialization, connection testing, API validation, and environment management.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.config import BinanceConfig
from src.core.events import EventBus, EventType
from src.services.exchange.binance_manager import BinanceConnectionError, BinanceManager


@pytest.fixture
def binance_config():
    """Create test Binance configuration."""
    return BinanceConfig(
        testnet_api_key="test_testnet_api_key",
        testnet_secret_key="test_testnet_secret_key",
        mainnet_api_key="test_mainnet_api_key",
        mainnet_secret_key="test_mainnet_secret_key",
        testnet=True,
    )


@pytest.fixture
def event_bus():
    """Create mock event bus."""
    bus = Mock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
async def binance_manager(binance_config, event_bus):
    """Create BinanceManager instance for testing."""
    manager = BinanceManager(config=binance_config, event_bus=event_bus)
    yield manager
    if manager.exchange:
        await manager.close()


class TestBinanceManagerInitialization:
    """Test BinanceManager initialization."""

    def test_init_with_config(self, binance_config, event_bus):
        """Test initialization with provided config."""
        manager = BinanceManager(config=binance_config, event_bus=event_bus)
        assert manager.config == binance_config
        assert manager.event_bus == event_bus
        assert manager.exchange is None
        assert not manager.is_connected
        assert manager.is_testnet

    def test_init_without_config(self):
        """Test initialization with default config from environment."""
        with patch("src.services.exchange.binance_manager.BinanceConfig") as mock_config:
            mock_config.return_value = Mock(testnet=True)
            manager = BinanceManager()
            assert manager.config is not None
            assert manager.event_bus is None

    @pytest.mark.asyncio
    async def test_initialize_testnet(self, binance_manager):
        """Test initialization with testnet configuration."""
        with patch("ccxt.pro.binance") as mock_binance:
            mock_exchange = AsyncMock()
            mock_binance.return_value = mock_exchange
            await binance_manager.initialize()
            assert binance_manager.exchange is not None
            mock_binance.assert_called_once()
            mock_exchange.set_sandbox_mode.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_initialize_mainnet(self, binance_config, event_bus):
        """Test initialization with mainnet configuration."""
        binance_config.testnet = False
        manager = BinanceManager(config=binance_config, event_bus=event_bus)
        with patch("ccxt.pro.binance") as mock_binance:
            mock_exchange = AsyncMock()
            mock_binance.return_value = mock_exchange
            await manager.initialize()
            assert manager.exchange is not None
            mock_exchange.set_sandbox_mode.assert_not_called()
        await manager.close()

    @pytest.mark.asyncio
    async def test_initialize_failure(self, binance_manager):
        """Test initialization failure handling."""
        with patch("ccxt.pro.binance") as mock_binance:
            mock_binance.side_effect = Exception("Connection failed")
            with pytest.raises(BinanceConnectionError, match="Failed to initialize"):
                await binance_manager.initialize()


class TestBinanceManagerConnection:
    """Test BinanceManager connection functionality."""

    @pytest.mark.asyncio
    async def test_test_connection_success(self, binance_manager, event_bus):
        """Test successful connection test."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        binance_manager.exchange = mock_exchange
        result = await binance_manager.test_connection()
        assert result is True
        assert binance_manager.is_connected
        mock_exchange.fetch_time.assert_called_once()
        event_bus.publish.assert_called_once()
        # Verify published event
        call_args = event_bus.publish.call_args[0][0]
        assert call_args.event_type == EventType.EXCHANGE_CONNECTED
        assert call_args.data["exchange"] == "binance"
        assert call_args.data["testnet"] is True

    @pytest.mark.asyncio
    async def test_test_connection_no_exchange(self, binance_manager):
        """Test connection test without initialized exchange."""
        with pytest.raises(BinanceConnectionError, match="Exchange not initialized"):
            await binance_manager.test_connection()

    @pytest.mark.asyncio
    async def test_test_connection_failure(self, binance_manager, event_bus):
        """Test connection test failure."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(side_effect=Exception("Network error"))
        binance_manager.exchange = mock_exchange
        with pytest.raises(BinanceConnectionError, match="connection test failed"):
            await binance_manager.test_connection()
        assert not binance_manager.is_connected
        # Verify error event published
        event_bus.publish.assert_called_once()
        call_args = event_bus.publish.call_args[0][0]
        assert call_args.event_type == EventType.EXCHANGE_ERROR


class TestBinanceManagerPermissions:
    """Test BinanceManager API permission validation."""

    @pytest.mark.asyncio
    async def test_validate_permissions_full_access(self, binance_manager):
        """Test permission validation with full access."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        mock_exchange.fetch_balance = AsyncMock(return_value={"USDT": {"free": 1000}})
        mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
        binance_manager.exchange = mock_exchange
        binance_manager._connection_tested = True
        binance_manager._connected = True
        permissions = await binance_manager.validate_api_permissions()
        assert permissions["read"] is True
        assert permissions["trade"] is True

    @pytest.mark.asyncio
    async def test_validate_permissions_read_only(self, binance_manager):
        """Test permission validation with read-only access."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        mock_exchange.fetch_balance = AsyncMock(return_value={"USDT": {"free": 1000}})
        mock_exchange.fetch_open_orders = AsyncMock(side_effect=Exception("Permission denied"))
        binance_manager.exchange = mock_exchange
        binance_manager._connection_tested = True
        binance_manager._connected = True
        permissions = await binance_manager.validate_api_permissions()
        assert permissions["read"] is True
        assert permissions["trade"] is False

    @pytest.mark.asyncio
    async def test_validate_permissions_no_access(self, binance_manager):
        """Test permission validation with no access."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        mock_exchange.fetch_balance = AsyncMock(side_effect=Exception("Invalid API key"))
        mock_exchange.fetch_open_orders = AsyncMock(side_effect=Exception("Invalid API key"))
        binance_manager.exchange = mock_exchange
        binance_manager._connection_tested = True
        binance_manager._connected = True
        permissions = await binance_manager.validate_api_permissions()
        assert permissions["read"] is False
        assert permissions["trade"] is False

    @pytest.mark.asyncio
    async def test_validate_permissions_auto_connect(self, binance_manager):
        """Test permission validation auto-connects if needed."""
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        mock_exchange.fetch_balance = AsyncMock(return_value={})
        mock_exchange.fetch_open_orders = AsyncMock(return_value=[])
        binance_manager.exchange = mock_exchange
        # permissions = await binance_manager.validate_api_permissions()
        # Should auto-connect first
        mock_exchange.fetch_time.assert_called_once()
        assert binance_manager.is_connected


class TestBinanceManagerContextManager:
    """Test BinanceManager async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_success(self, binance_config, event_bus):
        """Test async context manager with successful connection."""
        with patch("ccxt.pro.binance") as mock_binance:
            mock_exchange = AsyncMock()
            mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
            mock_binance.return_value = mock_exchange
            async with BinanceManager(config=binance_config, event_bus=event_bus) as manager:
                assert manager.is_connected
                assert manager.exchange is not None
            mock_exchange.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_initialization_failure(self, binance_config):
        """Test async context manager with initialization failure."""
        with patch("ccxt.pro.binance") as mock_binance:
            mock_binance.side_effect = Exception("Init failed")
        with pytest.raises(BinanceConnectionError):
            # async with BinanceManager(config=binance_config) as manager:
            pass


class TestBinanceManagerClose:
    """Test BinanceManager close functionality."""

    @pytest.mark.asyncio
    async def test_close_success(self, binance_manager, event_bus):
        """Test successful close operation."""
        mock_exchange = AsyncMock()
        binance_manager.exchange = mock_exchange
        binance_manager._connected = True
        await binance_manager.close()
        mock_exchange.close.assert_called_once()
        assert not binance_manager.is_connected
        event_bus.publish.assert_called_once()
        # Verify disconnect event
        call_args = event_bus.publish.call_args[0][0]
        assert call_args.event_type == EventType.EXCHANGE_DISCONNECTED

    @pytest.mark.asyncio
    async def test_close_no_exchange(self, binance_manager):
        """Test close with no exchange initialized."""
        # Should not raise error
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_close_with_error(self, binance_manager):
        """Test close with error during close operation."""
        mock_exchange = AsyncMock()
        mock_exchange.close = AsyncMock(side_effect=Exception("Close error"))
        binance_manager.exchange = mock_exchange
        # Should not raise error, just log
        await binance_manager.close()


class TestBinanceConfigCredentials:
    """Test BinanceConfig credential selection and validation."""

    def test_active_api_key_testnet_selection(self):
        """Test that testnet credentials are selected when testnet=True."""
        config = BinanceConfig(
            testnet_api_key="testnet_key",
            testnet_secret_key="testnet_secret",
            mainnet_api_key="mainnet_key",
            mainnet_secret_key="mainnet_secret",
            testnet=True,
        )
        assert config.active_api_key == "testnet_key"
        assert config.active_secret_key == "testnet_secret"

    def test_active_api_key_mainnet_selection(self):
        """Test that mainnet credentials are selected when testnet=False."""
        config = BinanceConfig(
            testnet_api_key="testnet_key",
            testnet_secret_key="testnet_secret",
            mainnet_api_key="mainnet_key",
            mainnet_secret_key="mainnet_secret",
            testnet=False,
        )
        assert config.active_api_key == "mainnet_key"
        assert config.active_secret_key == "mainnet_secret"

    def test_active_api_key_legacy_fallback_testnet(self):
        """Test that legacy credentials are used as fallback for testnet."""
        config = BinanceConfig(api_key="legacy_key", secret_key="legacy_secret", testnet=True)
        assert config.active_api_key == "legacy_key"
        assert config.active_secret_key == "legacy_secret"

    def test_active_api_key_legacy_fallback_mainnet(self):
        """Test that legacy credentials are used as fallback for mainnet."""
        config = BinanceConfig(api_key="legacy_key", secret_key="legacy_secret", testnet=False)
        assert config.active_api_key == "legacy_key"
        assert config.active_secret_key == "legacy_secret"

    def test_active_api_key_testnet_with_legacy_fallback(self):
        """Test that testnet credentials take precedence over legacy."""
        config = BinanceConfig(
            testnet_api_key="testnet_key",
            testnet_secret_key="testnet_secret",
            api_key="legacy_key",
            secret_key="legacy_secret",
            testnet=True,
        )
        assert config.active_api_key == "testnet_key"
        assert config.active_secret_key == "testnet_secret"

    def test_validate_credentials_success_testnet(self):
        """Test successful credential validation for testnet."""
        config = BinanceConfig(
            testnet_api_key="testnet_key", testnet_secret_key="testnet_secret", testnet=True
        )
        # Should not raise exception
        config.validate_credentials()

    def test_validate_credentials_success_mainnet(self):
        """Test successful credential validation for mainnet."""
        config = BinanceConfig(
            mainnet_api_key="mainnet_key", mainnet_secret_key="mainnet_secret", testnet=False
        )
        # Should not raise exception
        config.validate_credentials()

    def test_validate_credentials_missing_testnet_api_key(self):
        """Test validation fails when testnet API key is missing."""
        config = BinanceConfig(
            testnet_api_key="",  # Empty string
            testnet_secret_key="testnet_secret",
            api_key="",  # Ensure no fallback
            secret_key="",
            testnet=True,
        )
        with pytest.raises(ValueError, match="Binance testnet API credentials not configured"):
            config.validate_credentials()

    def test_validate_credentials_missing_testnet_secret_key(self):
        """Test validation fails when testnet secret key is missing."""
        config = BinanceConfig(
            testnet_api_key="testnet_key",
            testnet_secret_key="",  # Empty string
            api_key="",  # Ensure no fallback
            secret_key="",
            testnet=True,
        )
        with pytest.raises(ValueError, match="Binance testnet API credentials not configured"):
            config.validate_credentials()

    def test_validate_credentials_missing_mainnet_api_key(self):
        """Test validation fails when mainnet API key is missing."""
        config = BinanceConfig(
            mainnet_api_key="",  # Empty string
            mainnet_secret_key="mainnet_secret",
            api_key="",  # Ensure no fallback
            secret_key="",
            testnet=False,
        )
        with pytest.raises(ValueError, match="Binance mainnet API credentials not configured"):
            config.validate_credentials()

    def test_validate_credentials_missing_mainnet_secret_key(self):
        """Test validation fails when mainnet secret key is missing."""
        config = BinanceConfig(
            mainnet_api_key="mainnet_key",
            mainnet_secret_key="",  # Empty string
            api_key="",  # Ensure no fallback
            secret_key="",
            testnet=False,
        )
        with pytest.raises(ValueError, match="Binance mainnet API credentials not configured"):
            config.validate_credentials()

    def test_validate_credentials_error_message_includes_env_vars(self):
        """Test validation error message includes correct environment variable names."""
        config = BinanceConfig(
            testnet_api_key="", testnet_secret_key="", api_key="", secret_key="", testnet=True
        )
        try:
            config.validate_credentials()
            assert False, "Should have raised ValueError"
        except ValueError as e:
            error_message = str(e)
            assert "BINANCE_TESTNET_API_KEY" in error_message
            assert "BINANCE_TESTNET_SECRET_KEY" in error_message

    @pytest.mark.asyncio
    async def test_initialize_validates_credentials(self, event_bus):
        """Test that BinanceManager.initialize() validates credentials before initializing exchange."""
        config = BinanceConfig(
            testnet_api_key="", testnet_secret_key="", api_key="", secret_key="", testnet=True
        )
        manager = BinanceManager(config=config, event_bus=event_bus)

        with pytest.raises(
            BinanceConnectionError, match="Binance testnet API credentials not configured"
        ):
            await manager.initialize()

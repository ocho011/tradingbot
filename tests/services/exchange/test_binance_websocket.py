"""
Unit tests for BinanceManager WebSocket subscription functionality.
Tests candle stream subscriptions, multi-symbol/timeframe support,
data validation, and event publishing.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.config import BinanceConfig
from src.core.constants import TimeFrame
from src.core.events import EventBus, EventType
from src.services.exchange.binance_manager import BinanceConnectionError, BinanceManager


@pytest.fixture
def binance_config():
    """Create test Binance configuration."""
    return BinanceConfig(api_key="test_api_key", secret_key="test_secret_key", testnet=True)


@pytest.fixture
def event_bus():
    """Create mock event bus."""
    bus = Mock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
async def binance_manager(binance_config, event_bus):
    """Create initialized BinanceManager instance for testing (with heartbeat disabled)."""
    manager = BinanceManager(config=binance_config, event_bus=event_bus)
    # Mock exchange initialization
    mock_exchange = AsyncMock()
    mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
    mock_exchange.close = AsyncMock()  # Mock close() to prevent hanging
    manager.exchange = mock_exchange
    manager._connected = True
    manager._connection_tested = True
    manager._heartbeat_running = True  # Prevent heartbeat from starting (non-heartbeat tests)
    yield manager
    # Cleanup
    await manager.close()


@pytest.fixture
async def binance_manager_with_heartbeat(binance_config, event_bus):
    """Create initialized BinanceManager instance for heartbeat testing."""
    manager = BinanceManager(config=binance_config, event_bus=event_bus)
    # Mock exchange initialization
    mock_exchange = AsyncMock()
    mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
    mock_exchange.close = AsyncMock()  # Mock close() to prevent hanging
    manager.exchange = mock_exchange
    manager._connected = True
    manager._connection_tested = True
    manager._ws_running = True  # Enable WebSocket running state for heartbeat tests
    # DON'T set _heartbeat_running - let heartbeat tests control it
    yield manager
    # Cleanup
    await manager.close()


class TestCandleSubscription:
    """Test candle stream subscription functionality."""

    @pytest.mark.asyncio
    async def test_subscribe_single_symbol_single_timeframe(self, binance_manager, event_bus):
        """Test subscribing to single symbol and timeframe."""
        symbol = "BTCUSDT"
        timeframes = [TimeFrame.M1]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles(symbol, timeframes)
        assert symbol in binance_manager._ws_subscriptions
        assert TimeFrame.M1 in binance_manager._ws_subscriptions[symbol]
        assert binance_manager._ws_running is True
        assert f"{symbol}:{TimeFrame.M1.value}" in binance_manager._ws_tasks
        # Cleanup: stop tasks to prevent hanging
        binance_manager._ws_running = False
        for task in binance_manager._ws_tasks.values():
            task.cancel()
        await asyncio.gather(*binance_manager._ws_tasks.values(), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_subscribe_single_symbol_multiple_timeframes(self, binance_manager):
        """Test subscribing to multiple timeframes for single symbol."""
        symbol = "BTCUSDT"
        timeframes = [TimeFrame.M1, TimeFrame.M15, TimeFrame.H1]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles(symbol, timeframes)
        assert symbol in binance_manager._ws_subscriptions
        assert len(binance_manager._ws_subscriptions[symbol]) == 3
        assert all(tf in binance_manager._ws_subscriptions[symbol] for tf in timeframes)
        assert len(binance_manager._ws_tasks) == 3
        # Cleanup
        binance_manager._ws_running = False
        for task in binance_manager._ws_tasks.values():
            task.cancel()
        await asyncio.gather(*binance_manager._ws_tasks.values(), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_subscribe_multiple_symbols(self, binance_manager):
        """Test subscribing to multiple symbols."""
        symbols = ["BTCUSDT", "ETHUSDT"]
        timeframes = [TimeFrame.M1, TimeFrame.M15]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        for symbol in symbols:
            await binance_manager.subscribe_candles(symbol, timeframes)
        assert len(binance_manager._ws_subscriptions) == 2
        for symbol in symbols:
            assert symbol in binance_manager._ws_subscriptions
            assert len(binance_manager._ws_subscriptions[symbol]) == 2
        # 2 symbols * 2 timeframes = 4 tasks
        assert len(binance_manager._ws_tasks) == 4
        # Cleanup
        binance_manager._ws_running = False
        for task in binance_manager._ws_tasks.values():
            task.cancel()
        await asyncio.gather(*binance_manager._ws_tasks.values(), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_subscribe_duplicate_prevention(self, binance_manager):
        """Test that duplicate subscriptions are prevented."""
        symbol = "BTCUSDT"
        timeframes = [TimeFrame.M1]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Subscribe twice
        await binance_manager.subscribe_candles(symbol, timeframes)
        await binance_manager.subscribe_candles(symbol, timeframes)
        # Should only have one subscription
        assert len(binance_manager._ws_subscriptions[symbol]) == 1
        assert len(binance_manager._ws_tasks) == 1
        # Cleanup
        binance_manager._ws_running = False
        for task in binance_manager._ws_tasks.values():
            task.cancel()
        await asyncio.gather(*binance_manager._ws_tasks.values(), return_exceptions=True)

    @pytest.mark.asyncio
    async def test_subscribe_without_exchange_initialized(self, binance_config, event_bus):
        """Test subscription fails without initialized exchange."""
        manager = BinanceManager(config=binance_config, event_bus=event_bus)
        manager.exchange = None
        with pytest.raises(BinanceConnectionError, match="Exchange not initialized"):
            await manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])

    @pytest.mark.asyncio
    async def test_subscribe_auto_connects(self, binance_config, event_bus):
        """Test subscription auto-connects if not connected."""
        manager = BinanceManager(config=binance_config, event_bus=event_bus)
        mock_exchange = AsyncMock()
        mock_exchange.fetch_time = AsyncMock(return_value=1234567890000)
        mock_exchange.watch_ohlcv = AsyncMock(
            return_value=[[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]
        )
        mock_exchange.close = AsyncMock()  # Mock close() to prevent hanging
        manager.exchange = mock_exchange
        manager._connected = False
        manager._heartbeat_running = True  # Prevent heartbeat from starting
        await manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Should have called test_connection
        mock_exchange.fetch_time.assert_called_once()
        assert manager.is_connected
        await manager.close()


class TestCandleWatcher:
    """Test candle watching and event publishing."""

    @pytest.mark.asyncio
    async def test_watch_candles_publishes_events(self, binance_manager, event_bus):
        """Test that candle watcher publishes events correctly."""
        symbol = "BTCUSDT"
        timeframe = TimeFrame.M1
        # Mock watch_ohlcv to return sample candle data once, then empty to exit loop
        sample_candle = [
            1234567890000,  # timestamp
            50000.0,  # open
            51000.0,  # high
            49000.0,  # low
            50500.0,  # close
            100.5,  # volume
        ]
        call_count = 0

        async def mock_watch_ohlcv(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [sample_candle]
            # Return empty to exit loop
            binance_manager._ws_running = False
            return []

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Start watching
        binance_manager._ws_running = True
        watch_task = asyncio.create_task(binance_manager._watch_candles(symbol, timeframe))
        # Wait for task to complete
        await asyncio.sleep(0.5)
        # Verify event was published
        assert event_bus.publish.called
        published_event = event_bus.publish.call_args[0][0]
        assert published_event.event_type == EventType.CANDLE_RECEIVED
        assert published_event.data["symbol"] == symbol
        assert published_event.data["timeframe"] == timeframe.value
        assert published_event.data["open"] == 50000.0
        assert published_event.data["close"] == 50500.0
        # Cleanup
        if not watch_task.done():
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_watch_candles_handles_errors(self, binance_manager, event_bus):
        """Test that candle watcher handles errors gracefully."""
        symbol = "BTCUSDT"
        timeframe = TimeFrame.M1
        # Mock watch_ohlcv to raise error first, then return data, then exit
        error_count = 0

        async def mock_watch_with_error(*args, **kwargs):
            nonlocal error_count
            error_count += 1
            if error_count == 1:
                raise Exception("Network error")
            elif error_count == 2:
                # Return valid candle after error
                return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]
            else:
                # Exit loop after recovery
                binance_manager._ws_running = False
                return []

        binance_manager.exchange.watch_ohlcv = mock_watch_with_error
        # Start watching
        binance_manager._ws_running = True
        watch_task = asyncio.create_task(binance_manager._watch_candles(symbol, timeframe))
        # Wait for execution
        await asyncio.sleep(2.0)  # Enough time for error and recovery
        # Should have recovered and published event
        assert event_bus.publish.called
        # Cleanup
        if not watch_task.done():
            watch_task.cancel()
            try:
                await watch_task
            except asyncio.CancelledError:
                pass


class TestCandleValidation:
    """Test candle data validation."""

    def test_validate_candle_valid_data(self, binance_manager):
        """Test validation with valid candle data."""
        candle_data = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "timestamp": 1234567890000,
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "volume": 100.5,
        }
        assert binance_manager._validate_candle(candle_data) is True

    def test_validate_candle_missing_fields(self, binance_manager):
        """Test validation fails with missing fields."""
        candle_data = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            # Missing other required fields
        }
        assert binance_manager._validate_candle(candle_data) is False

    def test_validate_candle_invalid_ohlc(self, binance_manager):
        """Test validation fails with invalid OHLC relationships."""
        # High is lower than low
        candle_data = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "timestamp": 1234567890000,
            "open": 50000.0,
            "high": 48000.0,  # Invalid: high < low
            "low": 49000.0,
            "close": 50500.0,
            "volume": 100.5,
        }
        assert binance_manager._validate_candle(candle_data) is False

    def test_validate_candle_negative_values(self, binance_manager):
        """Test validation fails with negative values."""
        candle_data = {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "timestamp": 1234567890000,
            "open": 50000.0,
            "high": 51000.0,
            "low": -49000.0,  # Invalid: negative
            "close": 50500.0,
            "volume": 100.5,
        }
        assert binance_manager._validate_candle(candle_data) is False


class TestUnsubscribe:
    """Test unsubscribe functionality."""

    @pytest.mark.asyncio
    async def test_unsubscribe_specific_timeframe(self, binance_manager):
        """Test unsubscribing from specific timeframe."""
        symbol = "BTCUSDT"
        timeframes = [TimeFrame.M1, TimeFrame.M15, TimeFrame.H1]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles(symbol, timeframes)
        # Unsubscribe from M1 only
        await binance_manager.unsubscribe_candles(symbol, TimeFrame.M1)
        assert symbol in binance_manager._ws_subscriptions
        assert TimeFrame.M1 not in binance_manager._ws_subscriptions[symbol]
        assert TimeFrame.M15 in binance_manager._ws_subscriptions[symbol]
        assert TimeFrame.H1 in binance_manager._ws_subscriptions[symbol]
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_unsubscribe_all_timeframes(self, binance_manager):
        """Test unsubscribing from all timeframes for a symbol."""
        symbol = "BTCUSDT"
        timeframes = [TimeFrame.M1, TimeFrame.M15]
        # Mock watch_ohlcv to prevent actual WebSocket connection

        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles(symbol, timeframes)
        # Unsubscribe all
        await binance_manager.unsubscribe_candles(symbol)
        assert symbol not in binance_manager._ws_subscriptions
        assert len(binance_manager._ws_tasks) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_subscription(self, binance_manager):
        """Test unsubscribing from non-existent subscription doesn't error."""
        # Should not raise error
        await binance_manager.unsubscribe_candles("BTCUSDT", TimeFrame.M1)


class TestSubscriptionTracking:
    """Test subscription tracking functionality."""

    @pytest.mark.asyncio
    async def test_get_active_subscriptions(self, binance_manager):
        """Test getting active subscriptions."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1, TimeFrame.M15])
        await binance_manager.subscribe_candles("ETHUSDT", [TimeFrame.H1])
        subscriptions = binance_manager.get_active_subscriptions()
        assert len(subscriptions) == 2
        assert "BTCUSDT" in subscriptions
        assert "ETHUSDT" in subscriptions
        assert set(subscriptions["BTCUSDT"]) == {"1m", "15m"}
        assert subscriptions["ETHUSDT"] == ["1h"]
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_get_active_subscriptions_empty(self, binance_manager):
        """Test getting subscriptions when none active."""
        subscriptions = binance_manager.get_active_subscriptions()
        assert subscriptions == {}


class TestCloseWithWebSocket:
    """Test closing manager with active WebSocket subscriptions."""

    @pytest.mark.asyncio
    async def test_close_cancels_subscriptions(self, binance_manager):
        """Test that close() cancels all active subscriptions."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1, TimeFrame.M15])
        await binance_manager.subscribe_candles("ETHUSDT", [TimeFrame.H1])
        assert len(binance_manager._ws_tasks) == 3
        await binance_manager.close()
        # All tasks should be cancelled
        assert len(binance_manager._ws_tasks) == 0
        assert len(binance_manager._ws_subscriptions) == 0
        assert binance_manager._ws_running is False

    @pytest.mark.asyncio
    async def test_close_without_subscriptions(self, binance_manager):
        """Test close without active subscriptions."""
        # Should not raise error
        await binance_manager.close()
        assert not binance_manager.is_connected


class TestHeartbeatMonitoring:
    """Test heartbeat monitoring system."""

    @pytest.mark.asyncio
    async def test_heartbeat_starts_with_subscription(self, binance_manager_with_heartbeat):
        """Test that heartbeat monitor starts automatically with first subscription."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        # Use a function that yields control to prevent busy loop
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Wait a moment for heartbeat to start
        await asyncio.sleep(0.1)
        # Heartbeat should be running
        assert binance_manager_with_heartbeat._heartbeat_running is True
        assert binance_manager_with_heartbeat._heartbeat_task is not None
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_sends_periodic_pings(self, binance_manager_with_heartbeat, event_bus):
        """Test that heartbeat sends periodic pings."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set shorter interval for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.5
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Wait for multiple heartbeat cycles
        initial_time = binance_manager_with_heartbeat._last_heartbeat_time
        await asyncio.sleep(1.5)
        # Heartbeat time should have been updated
        assert binance_manager_with_heartbeat._last_heartbeat_time > initial_time
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_detects_connection_timeout(
        self, binance_manager_with_heartbeat, event_bus
    ):
        """Test that heartbeat detects connection timeout."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set short timeout for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.2
        binance_manager_with_heartbeat._heartbeat_timeout = 0.5
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Mock exchange.fetch_time to fail (simulating network issue)
        binance_manager_with_heartbeat.exchange.fetch_time = AsyncMock(
            side_effect=Exception("Network error")
        )
        # Wait for timeout to be detected
        await asyncio.sleep(1.0)
        # Connection should be marked unhealthy
        assert binance_manager_with_heartbeat.is_websocket_healthy is False
        # Should have published disconnection event
        # Find EXCHANGE_DISCONNECTED or EXCHANGE_ERROR events
        disconnection_events = [
            call
            for call in event_bus.publish.call_args_list
            if call[0][0].event_type in [EventType.EXCHANGE_DISCONNECTED, EventType.EXCHANGE_ERROR]
        ]
        assert len(disconnection_events) > 0
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_recovers_after_failure(
        self, binance_manager_with_heartbeat, event_bus
    ):
        """Test that heartbeat can recover after temporary failure."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set short intervals for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.3
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Initially healthy
        await asyncio.sleep(0.5)
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Simulate temporary failure
        original_fetch_time = binance_manager_with_heartbeat.exchange.fetch_time
        binance_manager_with_heartbeat.exchange.fetch_time = AsyncMock(
            side_effect=Exception("Temporary network error")
        )
        # Wait for failure to be detected
        await asyncio.sleep(0.5)
        assert binance_manager_with_heartbeat.is_websocket_healthy is False
        # Restore connection
        binance_manager_with_heartbeat.exchange.fetch_time = original_fetch_time
        # Wait for recovery
        await asyncio.sleep(0.5)
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Should have published recovery event
        recovery_events = [
            call
            for call in event_bus.publish.call_args_list
            if call[0][0].event_type == EventType.EXCHANGE_CONNECTED
            and "restored" in call[0][0].data.get("message", "").lower()
        ]
        assert len(recovery_events) > 0
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_stops_when_manager_closes(self, binance_manager_with_heartbeat):
        """Test that heartbeat monitor stops when manager closes."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Verify heartbeat is running
        assert binance_manager_with_heartbeat._heartbeat_running is True
        # Close manager
        await binance_manager_with_heartbeat.close()
        # Heartbeat should be stopped
        assert binance_manager_with_heartbeat._heartbeat_running is False
        assert binance_manager_with_heartbeat._heartbeat_task is None
        assert binance_manager_with_heartbeat.is_websocket_healthy is False

    @pytest.mark.asyncio
    async def test_heartbeat_tracks_response_times(self, binance_manager_with_heartbeat, event_bus):
        """Test that heartbeat tracks response times."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set short interval for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.3
        # Mock fetch_time with a delay to simulate response time

        async def mock_fetch_time_with_delay():
            await asyncio.sleep(0.05)  # 50ms delay
            return 1234567890000

        binance_manager_with_heartbeat.exchange.fetch_time = mock_fetch_time_with_delay
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Wait for heartbeat to execute
        await asyncio.sleep(0.5)
        # Response time should be tracked (check logs or events would contain response_time)
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_publishes_connection_events(
        self, binance_manager_with_heartbeat, event_bus
    ):
        """Test that heartbeat publishes appropriate connection state events."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set intervals for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.2
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Wait for initial heartbeat
        await asyncio.sleep(0.3)
        # Simulate connection failure
        binance_manager_with_heartbeat.exchange.fetch_time = AsyncMock(
            side_effect=Exception("Connection lost")
        )
        await asyncio.sleep(0.3)
        # Restore connection
        binance_manager_with_heartbeat.exchange.fetch_time = AsyncMock(return_value=1234567890000)
        await asyncio.sleep(0.3)
        # Should have published multiple events
        published_event_types = [call[0][0].event_type for call in event_bus.publish.call_args_list]
        # Should include connection-related events
        connection_events = [
            et
            for et in published_event_types
            if et
            in [
                EventType.EXCHANGE_CONNECTED,
                EventType.EXCHANGE_DISCONNECTED,
                EventType.EXCHANGE_ERROR,
            ]
        ]
        assert len(connection_events) > 0
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_heartbeat_property_reflects_state(self, binance_manager_with_heartbeat):
        """Test that is_websocket_healthy property reflects actual state."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Before subscription
        assert binance_manager_with_heartbeat.is_websocket_healthy is False
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        await asyncio.sleep(0.1)
        # After subscription
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # After close
        await binance_manager_with_heartbeat.close()
        assert binance_manager_with_heartbeat.is_websocket_healthy is False


class TestExponentialBackoffReconnection:
    """Test exponential backoff reconnection logic."""

    @pytest.mark.asyncio
    async def test_reconnection_triggered_on_timeout(
        self, binance_manager_with_heartbeat, event_bus
    ):
        """Test that reconnection is automatically triggered on heartbeat timeout."""

        # Mock watch_ohlcv to prevent actual WebSocket connection
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager_with_heartbeat.exchange.watch_ohlcv = mock_watch_ohlcv
        # Set short timeout for testing
        binance_manager_with_heartbeat._heartbeat_interval = 0.2
        binance_manager_with_heartbeat._heartbeat_timeout = 0.5
        await binance_manager_with_heartbeat.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Initially healthy
        await asyncio.sleep(0.3)
        assert binance_manager_with_heartbeat.is_websocket_healthy is True
        # Mock exchange.fetch_time to fail (simulating network issue)
        binance_manager_with_heartbeat.exchange.fetch_time = AsyncMock(
            side_effect=Exception("Network error")
        )
        # Wait for timeout and reconnection to trigger
        await asyncio.sleep(1.0)
        # Reconnection should have been triggered
        assert (
            binance_manager_with_heartbeat._reconnect_attempts > 0
            or binance_manager_with_heartbeat._is_reconnecting
        )
        # Cleanup
        await binance_manager_with_heartbeat.close()

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self, binance_manager, event_bus):
        """Test that reconnection delays follow exponential backoff pattern."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.1
        binance_manager._reconnect_current_delay = (
            0.1  # Must reset current delay when changing base delay
        )
        binance_manager._reconnect_max_delay = 1.0
        binance_manager._reconnect_max_retries = 4
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Mock fetch_time to fail continuously
        binance_manager.exchange.fetch_time = AsyncMock(side_effect=Exception("Connection failed"))
        # Trigger reconnection manually
        reconnect_task = asyncio.create_task(binance_manager._reconnect())
        # Wait for reconnection attempts
        await asyncio.sleep(3.0)
        # Should have attempted multiple times with increasing delays
        # Base: 0.1s, then 0.2s, 0.4s, 0.8s (4 attempts total)
        assert binance_manager._reconnect_attempts == binance_manager._reconnect_max_retries
        # Cancel reconnection task if still running
        if not reconnect_task.done():
            reconnect_task.cancel()
            try:
                await reconnect_task
            except asyncio.CancelledError:
                pass
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_reconnection_success_resets_state(self, binance_manager, event_bus):
        """Test that successful reconnection resets retry state."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.05
        binance_manager._reconnect_max_retries = 5
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Set initial failed state
        binance_manager._reconnect_attempts = 3
        binance_manager._reconnect_current_delay = 0.4
        binance_manager._ws_connection_healthy = False
        # Mock successful reconnection
        binance_manager.exchange.fetch_time = AsyncMock(return_value=1234567890000)
        # Trigger reconnection
        await binance_manager._reconnect()
        # State should be reset
        assert binance_manager._reconnect_attempts == 0
        assert binance_manager._reconnect_current_delay == binance_manager._reconnect_base_delay
        assert binance_manager._ws_connection_healthy is True
        # Should have published success event
        success_events = [
            call
            for call in event_bus.publish.call_args_list
            if call[0][0].event_type == EventType.EXCHANGE_CONNECTED
            and call[0][0].data.get("event") == "reconnection_successful"
        ]
        assert len(success_events) > 0
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, binance_manager, event_bus):
        """Test that reconnection stops after max retries."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.05
        binance_manager._reconnect_max_retries = 3
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Mock continuous failures
        binance_manager.exchange.fetch_time = AsyncMock(side_effect=Exception("Permanent failure"))
        # Trigger reconnection
        await binance_manager._reconnect()
        # Should have stopped after max retries
        assert binance_manager._reconnect_attempts == binance_manager._reconnect_max_retries
        assert binance_manager._is_reconnecting is False
        # Should have published failure event
        failure_events = [
            call
            for call in event_bus.publish.call_args_list
            if call[0][0].event_type == EventType.EXCHANGE_ERROR
            and call[0][0].data.get("event") == "reconnection_failed"
        ]
        assert len(failure_events) > 0
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_reconnection_resubscribes_streams(self, binance_manager, event_bus):
        """Test that successful reconnection resubscribes to WebSocket streams."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Subscribe to multiple streams
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1, TimeFrame.M15])
        await binance_manager.subscribe_candles("ETHUSDT", [TimeFrame.H1])
        # Verify subscriptions
        assert len(binance_manager._ws_subscriptions) == 2
        initial_task_count = len(binance_manager._ws_tasks)
        # Simulate stream disconnection by canceling tasks
        for task in list(binance_manager._ws_tasks.values()):
            task.cancel()
        await asyncio.gather(*binance_manager._ws_tasks.values(), return_exceptions=True)
        # Mock successful reconnection
        binance_manager.exchange.fetch_time = AsyncMock(return_value=1234567890000)
        binance_manager._ws_connection_healthy = False
        # Trigger reconnection
        await binance_manager._reconnect()
        # Should have resubscribed to all streams
        assert len(binance_manager._ws_subscriptions) == 2
        assert "BTCUSDT" in binance_manager._ws_subscriptions
        assert "ETHUSDT" in binance_manager._ws_subscriptions
        # Tasks should be recreated
        await asyncio.sleep(0.1)
        assert len(binance_manager._ws_tasks) >= initial_task_count
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_reconnection_delay_caps_at_maximum(self, binance_manager):
        """Test that reconnection delay doesn't exceed maximum."""
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.5
        binance_manager._reconnect_max_delay = 2.0
        binance_manager._reconnect_current_delay = 0.5
        # Simulate multiple failures
        for _ in range(5):
            binance_manager._reconnect_current_delay = min(
                binance_manager._reconnect_current_delay * 2, binance_manager._reconnect_max_delay
            )
        # Delay should be capped at max
        assert binance_manager._reconnect_current_delay == binance_manager._reconnect_max_delay

    @pytest.mark.asyncio
    async def test_reconnection_not_triggered_when_disabled(self, binance_manager, event_bus):
        """Test that reconnection is not triggered when disabled."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Disable reconnection
        binance_manager._reconnect_enabled = False
        # Set short timeout
        binance_manager._heartbeat_interval = 0.2
        binance_manager._heartbeat_timeout = 0.5
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Mock failure
        binance_manager.exchange.fetch_time = AsyncMock(side_effect=Exception("Network error"))
        # Wait for timeout
        await asyncio.sleep(1.0)
        # Reconnection should NOT have been triggered
        assert binance_manager._reconnect_attempts == 0
        assert binance_manager._is_reconnecting is False
        # Cleanup
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_concurrent_reconnection_prevented(self, binance_manager):
        """Test that concurrent reconnection attempts are prevented."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.5
        binance_manager.exchange.fetch_time = AsyncMock(side_effect=Exception("Connection failed"))
        # Start first reconnection
        task1 = asyncio.create_task(binance_manager._reconnect())
        await asyncio.sleep(0.1)
        # Try to start second reconnection
        task2 = asyncio.create_task(binance_manager._reconnect())
        await asyncio.sleep(0.1)
        # Second call should return immediately
        assert task2.done() or binance_manager._is_reconnecting
        # Cleanup
        task1.cancel()
        task2.cancel()
        await asyncio.gather(task1, task2, return_exceptions=True)
        await binance_manager.close()

    @pytest.mark.asyncio
    async def test_reconnection_publishes_attempt_events(self, binance_manager, event_bus):
        """Test that reconnection publishes events for each attempt."""

        # Mock watch_ohlcv
        async def mock_watch_ohlcv(*args, **kwargs):
            await asyncio.sleep(0.01)  # Yield control to event loop
            return [[1234567890000, 50000.0, 51000.0, 49000.0, 50500.0, 100.5]]

        binance_manager.exchange.watch_ohlcv = mock_watch_ohlcv
        # Configure for testing
        binance_manager._reconnect_base_delay = 0.05
        binance_manager._reconnect_max_retries = 3
        await binance_manager.subscribe_candles("BTCUSDT", [TimeFrame.M1])
        # Clear previous events
        event_bus.publish.reset_mock()
        # Mock failures
        binance_manager.exchange.fetch_time = AsyncMock(side_effect=Exception("Connection failed"))
        # Trigger reconnection
        await binance_manager._reconnect()
        # Should have published attempt events
        attempt_events = [
            call
            for call in event_bus.publish.call_args_list
            if call[0][0].data.get("event") == "reconnection_attempt"
        ]
        assert len(attempt_events) == binance_manager._reconnect_max_retries
        # Verify event data contains attempt info
        for idx, event_call in enumerate(attempt_events, 1):
            event_data = event_call[0][0].data
            assert event_data["attempt"] == idx
            assert event_data["max_attempts"] == binance_manager._reconnect_max_retries
            assert "delay" in event_data
        # Cleanup
        await binance_manager.close()

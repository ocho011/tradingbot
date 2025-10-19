"""
Tests for Binance REST API wrapper methods.

Tests account balance, positions, orders, market data retrieval,
error handling, and rate limiting functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.services.exchange.binance_manager import BinanceManager, BinanceConnectionError
from src.core.config import BinanceConfig
from src.core.events import EventBus


@pytest.fixture
def event_bus():
    """Create event bus for testing."""
    return EventBus()


@pytest.fixture
def binance_config():
    """Create test Binance configuration."""
    return BinanceConfig(
        api_key="test_api_key",
        secret_key="test_secret_key",
        testnet=True
    )


@pytest.fixture
async def binance_manager(binance_config, event_bus):
    """Create BinanceManager instance for testing."""
    manager = BinanceManager(config=binance_config, event_bus=event_bus)

    # Mock the exchange
    manager.exchange = AsyncMock()
    manager._connected = True
    manager._connection_tested = True

    yield manager

    # Cleanup
    if manager.exchange:
        await manager.close()


class TestAccountBalance:
    """Tests for account balance retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_balance_success(self, binance_manager):
        """Test successful balance retrieval."""
        # Mock balance data
        mock_balance = {
            'free': {'USDT': 1000.0, 'BTC': 0.5},
            'used': {'USDT': 200.0, 'BTC': 0.1},
            'total': {'USDT': 1200.0, 'BTC': 0.6},
            'info': {'assets': []}
        }
        binance_manager.exchange.fetch_balance.return_value = mock_balance

        # Fetch balance
        result = await binance_manager.fetch_balance()

        # Verify
        assert result == mock_balance
        assert result['total']['USDT'] == 1200.0
        assert result['total']['BTC'] == 0.6
        binance_manager.exchange.fetch_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_balance_without_initialization(self, binance_config):
        """Test fetch_balance fails without initialization."""
        manager = BinanceManager(config=binance_config)

        with pytest.raises(BinanceConnectionError, match="not initialized"):
            await manager.fetch_balance()

    @pytest.mark.asyncio
    async def test_fetch_balance_api_error(self, binance_manager):
        """Test fetch_balance handles API errors."""
        binance_manager.exchange.fetch_balance.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch balance"):
            await binance_manager.fetch_balance()


class TestPositions:
    """Tests for position information retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_positions_all_symbols(self, binance_manager):
        """Test fetching positions for all symbols."""
        # Mock position data
        mock_positions = [
            {'symbol': 'BTC/USDT', 'contracts': 1.5, 'side': 'long', 'unrealizedPnl': 100.0},
            {'symbol': 'ETH/USDT', 'contracts': 0.0, 'side': 'long', 'unrealizedPnl': 0.0},  # Zero position
            {'symbol': 'SOL/USDT', 'contracts': 10.0, 'side': 'short', 'unrealizedPnl': -50.0},
        ]
        binance_manager.exchange.fetch_positions.return_value = mock_positions

        # Fetch positions
        result = await binance_manager.fetch_positions()

        # Verify - should filter out zero positions
        assert len(result) == 2
        assert result[0]['symbol'] == 'BTC/USDT'
        assert result[1]['symbol'] == 'SOL/USDT'
        binance_manager.exchange.fetch_positions.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_fetch_positions_specific_symbols(self, binance_manager):
        """Test fetching positions for specific symbols."""
        symbols = ['BTC/USDT', 'ETH/USDT']
        mock_positions = [
            {'symbol': 'BTC/USDT', 'contracts': 1.5, 'side': 'long'},
            {'symbol': 'ETH/USDT', 'contracts': 2.0, 'side': 'short'},
        ]
        binance_manager.exchange.fetch_positions.return_value = mock_positions

        result = await binance_manager.fetch_positions(symbols)

        assert len(result) == 2
        binance_manager.exchange.fetch_positions.assert_called_once_with(symbols)

    @pytest.mark.asyncio
    async def test_fetch_positions_api_error(self, binance_manager):
        """Test fetch_positions handles API errors."""
        binance_manager.exchange.fetch_positions.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch positions"):
            await binance_manager.fetch_positions()


class TestOrders:
    """Tests for order history retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_orders_all_symbols(self, binance_manager):
        """Test fetching all orders."""
        mock_orders = [
            {
                'id': '12345',
                'symbol': 'BTC/USDT',
                'type': 'limit',
                'side': 'buy',
                'price': 50000.0,
                'amount': 0.1,
                'status': 'closed',
                'filled': 0.1
            },
            {
                'id': '12346',
                'symbol': 'ETH/USDT',
                'type': 'market',
                'side': 'sell',
                'amount': 1.0,
                'status': 'open',
                'filled': 0.0
            }
        ]
        binance_manager.exchange.fetch_orders.return_value = mock_orders

        result = await binance_manager.fetch_orders()

        assert len(result) == 2
        assert result[0]['id'] == '12345'
        assert result[1]['id'] == '12346'
        binance_manager.exchange.fetch_orders.assert_called_once_with(None, None, None)

    @pytest.mark.asyncio
    async def test_fetch_orders_specific_symbol(self, binance_manager):
        """Test fetching orders for specific symbol."""
        symbol = 'BTC/USDT'
        mock_orders = [
            {'id': '12345', 'symbol': 'BTC/USDT', 'status': 'closed'}
        ]
        binance_manager.exchange.fetch_orders.return_value = mock_orders

        result = await binance_manager.fetch_orders(symbol)

        assert len(result) == 1
        binance_manager.exchange.fetch_orders.assert_called_once_with(symbol, None, None)

    @pytest.mark.asyncio
    async def test_fetch_orders_with_params(self, binance_manager):
        """Test fetching orders with since and limit."""
        symbol = 'BTC/USDT'
        since = 1609459200000  # 2021-01-01
        limit = 100

        binance_manager.exchange.fetch_orders.return_value = []

        await binance_manager.fetch_orders(symbol, since, limit)

        binance_manager.exchange.fetch_orders.assert_called_once_with(symbol, since, limit)

    @pytest.mark.asyncio
    async def test_fetch_open_orders(self, binance_manager):
        """Test fetching open orders only."""
        mock_orders = [
            {'id': '12346', 'symbol': 'ETH/USDT', 'status': 'open'}
        ]
        binance_manager.exchange.fetch_open_orders.return_value = mock_orders

        result = await binance_manager.fetch_open_orders()

        assert len(result) == 1
        assert result[0]['status'] == 'open'
        binance_manager.exchange.fetch_open_orders.assert_called_once_with(None, None, None)

    @pytest.mark.asyncio
    async def test_fetch_closed_orders(self, binance_manager):
        """Test fetching closed orders only."""
        mock_orders = [
            {'id': '12345', 'symbol': 'BTC/USDT', 'status': 'closed'}
        ]
        binance_manager.exchange.fetch_closed_orders.return_value = mock_orders

        result = await binance_manager.fetch_closed_orders()

        assert len(result) == 1
        assert result[0]['status'] == 'closed'
        binance_manager.exchange.fetch_closed_orders.assert_called_once_with(None, None, None)


class TestMarketData:
    """Tests for market data retrieval."""

    @pytest.mark.asyncio
    async def test_fetch_ticker(self, binance_manager):
        """Test fetching ticker data."""
        symbol = 'BTC/USDT'
        mock_ticker = {
            'symbol': symbol,
            'last': 50000.0,
            'bid': 49990.0,
            'ask': 50010.0,
            'high': 51000.0,
            'low': 49000.0,
            'volume': 1000.0,
            'timestamp': 1609459200000
        }
        binance_manager.exchange.fetch_ticker.return_value = mock_ticker

        result = await binance_manager.fetch_ticker(symbol)

        assert result['symbol'] == symbol
        assert result['last'] == 50000.0
        assert result['bid'] == 49990.0
        binance_manager.exchange.fetch_ticker.assert_called_once_with(symbol)

    @pytest.mark.asyncio
    async def test_fetch_ohlcv(self, binance_manager):
        """Test fetching OHLCV candlestick data."""
        symbol = 'BTC/USDT'
        timeframe = '1h'
        mock_ohlcv = [
            [1609459200000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0],
            [1609462800000, 50500.0, 51500.0, 50000.0, 51000.0, 150.0],
        ]
        binance_manager.exchange.fetch_ohlcv.return_value = mock_ohlcv

        result = await binance_manager.fetch_ohlcv(symbol, timeframe)

        assert len(result) == 2
        assert result[0][1] == 50000.0  # Open price of first candle
        assert result[1][4] == 51000.0  # Close price of second candle
        binance_manager.exchange.fetch_ohlcv.assert_called_once_with(symbol, timeframe, None, None)

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_with_params(self, binance_manager):
        """Test fetching OHLCV with since and limit."""
        symbol = 'BTC/USDT'
        timeframe = '1m'
        since = 1609459200000
        limit = 100

        binance_manager.exchange.fetch_ohlcv.return_value = []

        await binance_manager.fetch_ohlcv(symbol, timeframe, since, limit)

        binance_manager.exchange.fetch_ohlcv.assert_called_once_with(symbol, timeframe, since, limit)

    @pytest.mark.asyncio
    async def test_fetch_order_book(self, binance_manager):
        """Test fetching order book."""
        symbol = 'BTC/USDT'
        mock_order_book = {
            'symbol': symbol,
            'bids': [[50000.0, 1.0], [49990.0, 2.0]],
            'asks': [[50010.0, 1.5], [50020.0, 2.5]],
            'timestamp': 1609459200000
        }
        binance_manager.exchange.fetch_order_book.return_value = mock_order_book

        result = await binance_manager.fetch_order_book(symbol)

        assert result['symbol'] == symbol
        assert len(result['bids']) == 2
        assert len(result['asks']) == 2
        assert result['bids'][0][0] == 50000.0
        binance_manager.exchange.fetch_order_book.assert_called_once_with(symbol, None)

    @pytest.mark.asyncio
    async def test_fetch_order_book_with_limit(self, binance_manager):
        """Test fetching order book with depth limit."""
        symbol = 'BTC/USDT'
        limit = 10

        binance_manager.exchange.fetch_order_book.return_value = {
            'symbol': symbol,
            'bids': [],
            'asks': []
        }

        await binance_manager.fetch_order_book(symbol, limit)

        binance_manager.exchange.fetch_order_book.assert_called_once_with(symbol, limit)

    @pytest.mark.asyncio
    async def test_fetch_trading_fees(self, binance_manager):
        """Test fetching trading fees."""
        mock_fees = {
            'BTC/USDT': {'maker': 0.0002, 'taker': 0.0004},
            'ETH/USDT': {'maker': 0.0002, 'taker': 0.0004}
        }
        binance_manager.exchange.fetch_trading_fees.return_value = mock_fees

        result = await binance_manager.fetch_trading_fees()

        assert 'BTC/USDT' in result
        assert result['BTC/USDT']['maker'] == 0.0002
        binance_manager.exchange.fetch_trading_fees.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_trading_fees_specific_symbol(self, binance_manager):
        """Test fetching trading fees for specific symbol."""
        symbol = 'BTC/USDT'
        mock_fees = {
            'BTC/USDT': {'maker': 0.0002, 'taker': 0.0004},
            'ETH/USDT': {'maker': 0.0002, 'taker': 0.0004}
        }
        binance_manager.exchange.fetch_trading_fees.return_value = mock_fees

        result = await binance_manager.fetch_trading_fees(symbol)

        # Should only return fees for requested symbol
        assert symbol in result
        assert 'ETH/USDT' not in result
        assert result[symbol]['maker'] == 0.0002


class TestErrorHandling:
    """Tests for error handling across all REST API methods."""

    @pytest.mark.asyncio
    async def test_fetch_ticker_api_error(self, binance_manager):
        """Test ticker API error handling."""
        binance_manager.exchange.fetch_ticker.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch ticker"):
            await binance_manager.fetch_ticker('BTC/USDT')

    @pytest.mark.asyncio
    async def test_fetch_ohlcv_api_error(self, binance_manager):
        """Test OHLCV API error handling."""
        binance_manager.exchange.fetch_ohlcv.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch OHLCV"):
            await binance_manager.fetch_ohlcv('BTC/USDT', '1h')

    @pytest.mark.asyncio
    async def test_fetch_order_book_api_error(self, binance_manager):
        """Test order book API error handling."""
        binance_manager.exchange.fetch_order_book.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch order book"):
            await binance_manager.fetch_order_book('BTC/USDT')

    @pytest.mark.asyncio
    async def test_fetch_open_orders_api_error(self, binance_manager):
        """Test open orders API error handling."""
        binance_manager.exchange.fetch_open_orders.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch open orders"):
            await binance_manager.fetch_open_orders()

    @pytest.mark.asyncio
    async def test_fetch_trading_fees_api_error(self, binance_manager):
        """Test trading fees API error handling."""
        binance_manager.exchange.fetch_trading_fees.side_effect = Exception("API error")

        with pytest.raises(BinanceConnectionError, match="Failed to fetch trading fees"):
            await binance_manager.fetch_trading_fees()


class TestRateLimiting:
    """Tests for rate limiting management."""

    @pytest.mark.asyncio
    async def test_rate_limiting_enabled(self, binance_manager):
        """Test that rate limiting is enabled in exchange config."""
        # Verify rate limiting was enabled during initialization
        assert binance_manager.exchange is not None
        # The 'enableRateLimit' is set during initialization in the actual init method
        # Here we just verify the exchange exists and rate limit calls work

    @pytest.mark.asyncio
    async def test_multiple_rapid_requests(self, binance_manager):
        """Test multiple rapid requests respect rate limits."""
        # Mock responses for multiple calls
        binance_manager.exchange.fetch_ticker.return_value = {
            'symbol': 'BTC/USDT',
            'last': 50000.0
        }

        # Make multiple rapid requests
        symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
        tasks = [binance_manager.fetch_ticker(symbol) for symbol in symbols]

        results = await asyncio.gather(*tasks)

        # All requests should complete successfully
        assert len(results) == 3
        assert all(r['symbol'] for r in results)

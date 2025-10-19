"""
Example: Historical Candle Data Loading

This example demonstrates how to use the HistoricalDataLoader to load
historical candle data from Binance.
"""

import asyncio
import logging
from src.services.exchange.binance_manager import BinanceManager
from src.services.exchange.historical_loader import HistoricalDataLoader
from src.services.candle_storage import CandleStorage
from src.core.constants import TimeFrame
from src.core.events import EventBus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Main function demonstrating historical data loading."""

    # Initialize components
    event_bus = EventBus()
    binance_manager = BinanceManager(event_bus=event_bus)
    candle_storage = CandleStorage(max_candles=1000)

    # Initialize loader
    historical_loader = HistoricalDataLoader(
        binance_manager=binance_manager,
        candle_storage=candle_storage,
        enable_rate_limiting=True
    )

    try:
        # Initialize Binance connection
        logger.info("Initializing Binance connection...")
        await binance_manager.initialize()
        await binance_manager.test_connection()

        # Example 1: Load single symbol-timeframe
        logger.info("\n=== Example 1: Load single symbol-timeframe ===")
        candles = await historical_loader.load_historical_data(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=500
        )

        logger.info(f"Loaded {len(candles)} candles for BTCUSDT 15m")
        logger.info(f"First candle: {candles[0]}")
        logger.info(f"Last candle: {candles[-1]}")

        # Example 2: Load multiple symbols and timeframes
        logger.info("\n=== Example 2: Load multiple symbols/timeframes ===")
        results = await historical_loader.load_multiple_symbols(
            symbols=['BTCUSDT', 'ETHUSDT'],
            timeframes=[TimeFrame.M15, TimeFrame.H1],
            limit=100,
            parallel=True
        )

        # Display results
        for symbol, timeframe_data in results.items():
            for timeframe, candles in timeframe_data.items():
                logger.info(f"{symbol} {timeframe.value}: {len(candles)} candles")

        # Example 3: Check storage statistics
        logger.info("\n=== Example 3: Storage Statistics ===")
        storage_stats = candle_storage.get_stats()
        logger.info(f"Total candles in storage: {storage_stats.total_candles}")
        logger.info(f"Storage count: {storage_stats.storage_count}")
        logger.info(f"Memory usage: {storage_stats.memory_mb} MB")

        # Example 4: Retrieve from storage
        logger.info("\n=== Example 4: Retrieve from storage ===")
        stored_candles = candle_storage.get_candles(
            symbol='BTCUSDT',
            timeframe=TimeFrame.M15,
            limit=10
        )
        logger.info(f"Retrieved {len(stored_candles)} candles from storage")

        # Example 5: Loader statistics
        logger.info("\n=== Example 5: Loader Statistics ===")
        loader_stats = historical_loader.get_stats()
        logger.info(f"Total candles loaded: {loader_stats['total_candles_loaded']}")
        logger.info(f"Total API requests: {loader_stats['total_requests']}")
        logger.info(f"Rate limit delays: {loader_stats['rate_limit_delays']}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)

    finally:
        # Cleanup
        await binance_manager.close()
        logger.info("Binance connection closed")


if __name__ == "__main__":
    asyncio.run(main())

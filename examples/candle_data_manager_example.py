"""
Example usage of CandleDataManager for multi-symbol/timeframe management.

This example demonstrates:
1. Setting up the manager with multiple symbols and timeframes
2. Adding and removing symbols dynamically
3. Monitoring system resources and memory usage
4. Retrieving candle data
5. Getting dashboard state for monitoring
"""

import asyncio
import logging
from datetime import datetime, timezone

from src.core.constants import EventType, TimeFrame
from src.core.events import EventBus, Event
from src.services.candle_data_manager import CandleDataManager
from src.models.candle import Candle


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def main():
    """Main example function."""

    # 1. Initialize EventBus and CandleDataManager
    logger.info("=" * 60)
    logger.info("Setting up CandleDataManager")
    logger.info("=" * 60)

    event_bus = EventBus()
    manager = CandleDataManager(
        event_bus=event_bus,
        max_candles_per_storage=500,
        enable_monitoring=True,
        monitoring_interval=30  # Monitor every 30 seconds
    )

    # Start the manager
    await manager.start()

    try:
        # 2. Add multiple symbols with different timeframes
        logger.info("\n" + "=" * 60)
        logger.info("Adding symbols and timeframes")
        logger.info("=" * 60)

        # Add BTCUSDT with 1m, 15m, 1h timeframes
        await manager.add_symbol('BTCUSDT', [TimeFrame.M1, TimeFrame.M15, TimeFrame.H1])
        logger.info("✓ Added BTCUSDT with 3 timeframes")

        # Add ETHUSDT with 1m, 1h timeframes
        await manager.add_symbol('ETHUSDT', [TimeFrame.M1, TimeFrame.H1])
        logger.info("✓ Added ETHUSDT with 2 timeframes")

        # Add BNBUSDT with just 1m
        await manager.add_symbol('BNBUSDT', [TimeFrame.M1])
        logger.info("✓ Added BNBUSDT with 1 timeframe")

        # 3. Display current configuration
        logger.info("\n" + "=" * 60)
        logger.info("Current Configuration")
        logger.info("=" * 60)

        symbols = manager.get_symbols()
        logger.info(f"Managed symbols: {symbols}")

        for symbol in symbols:
            config = manager.get_symbol_config(symbol)
            logger.info(f"\n{symbol}:")
            logger.info(f"  Timeframes: {config['timeframes']}")
            logger.info(f"  Added at: {config['added_at']}")
            logger.info(f"  Enabled: {config['enabled']}")

        # 4. Simulate receiving candle data
        logger.info("\n" + "=" * 60)
        logger.info("Simulating Candle Data Reception")
        logger.info("=" * 60)

        # Simulate some candle events for BTCUSDT
        base_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        base_timestamp = Candle.normalize_timestamp(base_timestamp, TimeFrame.M1)

        for i in range(5):
            timestamp = base_timestamp + (i * 60000)  # 1 minute apart

            event = Event(
                event_type=EventType.CANDLE_RECEIVED,
                priority=5,
                data={
                    'symbol': 'BTCUSDT',
                    'timeframe': '1m',
                    'timestamp': timestamp,
                    'open': 45000.0 + i,
                    'high': 45100.0 + i,
                    'low': 44900.0 + i,
                    'close': 45050.0 + i,
                    'volume': 100.5 + i
                }
            )

            await event_bus.publish(event)
            logger.info(f"Published candle event #{i+1} for BTCUSDT")

        # Wait for events to process
        await asyncio.sleep(0.5)

        # 5. Retrieve candle data
        logger.info("\n" + "=" * 60)
        logger.info("Retrieving Candle Data")
        logger.info("=" * 60)

        candles = manager.get_candles('BTCUSDT', TimeFrame.M1, limit=3)
        logger.info(f"Retrieved {len(candles)} candles for BTCUSDT 1m")

        for candle in candles:
            logger.info(f"  {candle.get_datetime_iso()}: O={candle.open:.2f} C={candle.close:.2f}")

        latest = manager.get_latest_candle('BTCUSDT', TimeFrame.M1)
        if latest:
            logger.info(f"\nLatest candle: {latest}")

        # 6. Get dashboard state
        logger.info("\n" + "=" * 60)
        logger.info("Dashboard State")
        logger.info("=" * 60)

        state = manager.get_dashboard_state()
        logger.info(f"Total symbols: {state['total_symbols']}")
        logger.info(f"Uptime: {state['uptime_seconds']:.1f} seconds")
        logger.info(f"\nStorage:")
        logger.info(f"  Total candles: {state['storage']['total_candles']}")
        logger.info(f"  Storage count: {state['storage']['storage_count']}")
        logger.info(f"  Memory usage: {state['storage']['memory_mb']} MB")
        logger.info(f"\nProcessor:")
        logger.info(f"  Candles processed: {state['processor']['candles_processed']}")
        logger.info(f"  Candles closed: {state['processor']['candles_closed']}")

        # 7. Memory usage breakdown
        logger.info("\n" + "=" * 60)
        logger.info("Memory Usage Breakdown")
        logger.info("=" * 60)

        memory_summary = manager.get_memory_usage_summary()
        for symbol, data in memory_summary.items():
            logger.info(f"\n{symbol}: {data['total_mb']} MB")
            for tf, tf_data in data['timeframes'].items():
                logger.info(f"  {tf}: {tf_data['candles']} candles, {tf_data['estimated_mb']} MB")

        # 8. Dynamically add more timeframes
        logger.info("\n" + "=" * 60)
        logger.info("Dynamic Timeframe Addition")
        logger.info("=" * 60)

        await manager.add_symbol('BTCUSDT', [TimeFrame.M5, TimeFrame.H4], replace=False)
        logger.info("✓ Added M5 and H4 timeframes to BTCUSDT")

        timeframes = manager.get_timeframes('BTCUSDT')
        logger.info(f"BTCUSDT now has {len(timeframes)} timeframes: {[tf.value for tf in timeframes]}")

        # 9. Remove specific timeframes
        logger.info("\n" + "=" * 60)
        logger.info("Removing Timeframes")
        logger.info("=" * 60)

        await manager.remove_symbol('BNBUSDT', clear_data=True)
        logger.info("✓ Removed BNBUSDT entirely")

        await manager.remove_symbol('BTCUSDT', [TimeFrame.M5], clear_data=False)
        logger.info("✓ Removed M5 from BTCUSDT (data retained)")

        # 10. Memory optimization
        logger.info("\n" + "=" * 60)
        logger.info("Memory Optimization")
        logger.info("=" * 60)

        result = await manager.optimize_memory(aggressive=False)
        logger.info(f"Memory freed: {result['memory_freed_mb']} MB")
        logger.info(f"Objects collected: {result['gc_objects_collected']}")
        logger.info(f"Before: {result['before_memory_mb']} MB")
        logger.info(f"After: {result['after_memory_mb']} MB")

        # 11. Final state
        logger.info("\n" + "=" * 60)
        logger.info("Final State")
        logger.info("=" * 60)

        logger.info(f"Active symbols: {manager.get_symbols()}")
        logger.info(f"\nManager: {manager}")
        logger.info(f"Storage: {manager._storage}")

        # Let monitoring run for a bit
        logger.info("\nLetting monitoring run for 5 seconds...")
        await asyncio.sleep(5)

    finally:
        # Cleanup
        logger.info("\n" + "=" * 60)
        logger.info("Shutting down")
        logger.info("=" * 60)

        await manager.stop()
        logger.info("✓ CandleDataManager stopped")


if __name__ == "__main__":
    asyncio.run(main())

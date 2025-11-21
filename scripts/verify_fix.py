import asyncio
import logging
from decimal import Decimal
from unittest.mock import MagicMock
import pandas as pd
from src.core.constants import TimeFrame
from src.models.candle import Candle
from src.services.strategy.integration_layer import StrategyIntegrationLayer

# Configure logging
logging.basicConfig(level=logging.INFO)

async def test_evaluate_strategies():
    print("Starting test_evaluate_strategies...")
    
    # Mock CandleStorage
    mock_storage = MagicMock()
    
    # Create sample candles
    candles = []
    for i in range(100):
        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe=TimeFrame.M1,
            timestamp=1700000000000 + i * 60000,
            open=50000.0 + i,
            high=50100.0 + i,
            low=49900.0 + i,
            close=50050.0 + i,
            volume=10.0
        ))
    
    # Setup mock return value (List of Candles, NOT DataFrame)
    mock_storage.get_candles.return_value = candles
    
    # Initialize StrategyIntegrationLayer
    layer = StrategyIntegrationLayer(
        candle_storage=mock_storage,
        event_bus=MagicMock()
    )
    
    # Test evaluate_strategies
    try:
        print("Calling evaluate_strategies...")
        signals = await layer.evaluate_strategies(
            symbol="BTCUSDT",
            timeframe="1m",
            indicators={}
        )
        print(f"Success! Generated {len(signals)} signals.")
        
    except AttributeError as e:
        print(f"FAILED with AttributeError: {e}")
    except Exception as e:
        print(f"FAILED with Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_evaluate_strategies())

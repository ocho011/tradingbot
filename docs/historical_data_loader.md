# HistoricalDataLoader Documentation

## Overview

The `HistoricalDataLoader` class provides a robust solution for loading historical candle data from Binance exchange with intelligent batching, rate limiting, and data validation.

## Features

### Core Capabilities
- ✅ Batch loading up to 1000 candles per request (Binance API limit)
- ✅ Automatic rate limiting with exponential backoff
- ✅ Data integrity validation (time ordering, gap detection, duplicates)
- ✅ Integration with CandleStorage for persistence
- ✅ Parallel loading of multiple symbols/timeframes
- ✅ Comprehensive error handling and retry logic
- ✅ Statistics tracking for monitoring

### Rate Limiting
- Implements sliding window rate limiting
- Respects Binance API weight limits (1200 requests/minute)
- Automatic delay when approaching rate limits
- Configurable backoff strategy

### Data Validation
- **Time Ordering**: Ensures candles are in chronological order
- **Gap Detection**: Identifies missing candles in sequences
- **Duplicate Detection**: Finds duplicate timestamps
- **OHLCV Integrity**: Validates price relationships

## Usage

### Basic Example

```python
from src.services.exchange.binance_manager import BinanceManager
from src.services.exchange.historical_loader import HistoricalDataLoader
from src.services.candle_storage import CandleStorage
from src.core.constants import TimeFrame

# Initialize components
binance_manager = BinanceManager()
candle_storage = CandleStorage(max_candles=1000)
loader = HistoricalDataLoader(binance_manager, candle_storage)

# Initialize Binance
await binance_manager.initialize()
await binance_manager.test_connection()

# Load historical data
candles = await loader.load_historical_data(
    symbol='BTCUSDT',
    timeframe=TimeFrame.M15,
    limit=500
)
```

### Loading Multiple Symbols

```python
# Load multiple symbols and timeframes in parallel
results = await loader.load_multiple_symbols(
    symbols=['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
    timeframes=[TimeFrame.M15, TimeFrame.H1, TimeFrame.H4],
    limit=500,
    parallel=True  # Load in parallel for efficiency
)

# Access results
btc_m15_candles = results['BTCUSDT'][TimeFrame.M15]
eth_h1_candles = results['ETHUSDT'][TimeFrame.H1]
```

### Data Validation

```python
# Load with validation enabled (default)
candles = await loader.load_historical_data(
    symbol='BTCUSDT',
    timeframe=TimeFrame.M15,
    limit=500,
    validate=True  # Validates time ordering, gaps, duplicates
)

# Check validation results manually
validation_result = loader._validate_candles(candles)
if not validation_result['valid']:
    print("Issues found:", validation_result['issues'])
    print("Gaps:", validation_result['gaps'])
    print("Duplicates:", validation_result['duplicates'])
```

### Without Storage

```python
# Load without storing in CandleStorage
candles = await loader.load_historical_data(
    symbol='BTCUSDT',
    timeframe=TimeFrame.M15,
    limit=500,
    store=False  # Don't persist to storage
)
```

### Statistics Monitoring

```python
# Get loader statistics
stats = loader.get_stats()
print(f"Total candles loaded: {stats['total_candles_loaded']}")
print(f"Total API requests: {stats['total_requests']}")
print(f"Rate limit delays: {stats['rate_limit_delays']}")

# Reset statistics
loader.reset_stats()
```

## Configuration

### Rate Limiting Settings

```python
# Disable rate limiting (not recommended for production)
loader = HistoricalDataLoader(
    binance_manager=binance_manager,
    candle_storage=candle_storage,
    enable_rate_limiting=False
)

# Rate limit configuration (class constants)
MAX_CANDLES_PER_REQUEST = 1000  # Binance limit
RATE_LIMIT_REQUESTS_PER_MINUTE = 1200  # Binance weight limit
RATE_LIMIT_WINDOW_SECONDS = 60
REQUEST_WEIGHT = 5  # Weight per klines request
```

### Retry Configuration

```python
# Backoff configuration (class constants)
BACKOFF_BASE_DELAY = 1.0  # Initial delay in seconds
BACKOFF_MAX_DELAY = 30.0  # Maximum delay in seconds
BACKOFF_MULTIPLIER = 2.0  # Exponential multiplier
MAX_RETRIES = 5  # Maximum retry attempts
```

## API Reference

### Main Methods

#### `load_historical_data`
Load historical candle data for a single symbol-timeframe pair.

**Parameters:**
- `symbol` (str): Trading pair symbol (e.g., 'BTCUSDT')
- `timeframe` (TimeFrame): Candle timeframe
- `limit` (int): Number of candles to load (default: 500, max: 1000)
- `validate` (bool): Validate data integrity (default: True)
- `store` (bool): Store in CandleStorage (default: True)

**Returns:** `List[Candle]`

#### `load_multiple_symbols`
Load historical data for multiple symbol-timeframe combinations.

**Parameters:**
- `symbols` (List[str]): List of trading pair symbols
- `timeframes` (List[TimeFrame]): List of timeframes
- `limit` (int): Number of candles per combination
- `validate` (bool): Validate data integrity
- `store` (bool): Store in CandleStorage
- `parallel` (bool): Load in parallel (default: True)

**Returns:** `Dict[str, Dict[TimeFrame, List[Candle]]]`

#### `get_stats`
Get loader statistics.

**Returns:**
```python
{
    'total_candles_loaded': int,
    'total_requests': int,
    'rate_limit_delays': int,
    'rate_limiting_enabled': bool
}
```

#### `reset_stats`
Reset loading statistics.

## Error Handling

### Retry with Exponential Backoff

The loader automatically retries failed requests with exponential backoff:

```
Attempt 1: 1.0s delay
Attempt 2: 2.0s delay
Attempt 3: 4.0s delay
Attempt 4: 8.0s delay
Attempt 5: 16.0s delay (max 30s)
```

### Exception Handling

```python
from src.services.exchange.binance_manager import BinanceConnectionError

try:
    candles = await loader.load_historical_data(
        symbol='BTCUSDT',
        timeframe=TimeFrame.M15,
        limit=500
    )
except BinanceConnectionError as e:
    print(f"Failed to load data: {e}")
except ValueError as e:
    print(f"Invalid parameters: {e}")
```

## Data Validation Details

### Time Ordering
Ensures candles are sorted chronologically:
- Each candle's timestamp must be greater than the previous
- Violations are logged with specific timestamps

### Gap Detection
Identifies missing candles in sequences:
- Calculates expected timestamp based on timeframe interval
- Reports gaps with size (number of missing candles)
- Provides gap start and end timestamps

### Duplicate Detection
Finds duplicate candles:
- Tracks seen timestamps
- Reports duplicate timestamps
- Logs duplicate issues

## Performance Considerations

### Parallel Loading
- Use `parallel=True` for multiple symbols (faster)
- Respects rate limits even in parallel mode
- Recommended for initial data loading

### Rate Limiting Impact
- Enabled by default for safety
- May introduce delays when approaching limits
- Disable only for testing or when using proxy

### Memory Usage
- Each candle consumes ~200-300 bytes
- 500 candles ≈ 100-150 KB
- Monitor with `CandleStorage.get_stats()`

## Best Practices

1. **Always enable rate limiting in production**
   ```python
   enable_rate_limiting=True  # Default
   ```

2. **Load initial data sequentially or in small batches**
   ```python
   # Good: Load in controlled batches
   for symbol in symbols:
       await loader.load_historical_data(symbol, timeframe, limit=500)
   ```

3. **Monitor statistics during bulk loads**
   ```python
   stats = loader.get_stats()
   if stats['rate_limit_delays'] > 10:
       print("Consider reducing load frequency")
   ```

4. **Validate data for critical operations**
   ```python
   candles = await loader.load_historical_data(..., validate=True)
   ```

5. **Handle errors gracefully**
   ```python
   try:
       candles = await loader.load_historical_data(...)
   except BinanceConnectionError:
       # Retry later or use cached data
   ```

## Testing

Comprehensive test coverage (94%):
- ✅ Basic data loading
- ✅ Storage integration
- ✅ Data validation (gaps, duplicates, ordering)
- ✅ Error handling and retry logic
- ✅ Rate limiting
- ✅ Multiple symbol loading
- ✅ Statistics tracking

Run tests:
```bash
python3 -m pytest tests/services/exchange/test_historical_loader.py -v
```

## Example Output

```
2024-01-01 10:00:00 - INFO - Loading 500 historical candles for BTCUSDT 15m...
2024-01-01 10:00:01 - INFO - Loaded 500 candles for BTCUSDT 15m (requested: 500)
2024-01-01 10:00:01 - DEBUG - Data validation passed for BTCUSDT 15m
2024-01-01 10:00:01 - INFO - Stored 500 candles in storage for BTCUSDT 15m
2024-01-01 10:00:01 - INFO - ✓ Historical data load complete: BTCUSDT 15m (500 candles in 1.23s)
```

## Integration Example

See `examples/historical_data_loading.py` for a complete working example.

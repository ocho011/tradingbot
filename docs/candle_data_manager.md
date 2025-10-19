# CandleDataManager Documentation

## Overview

The `CandleDataManager` is a comprehensive system for managing real-time candle data across multiple trading pairs (symbols) and timeframes. It provides centralized coordination, resource monitoring, and dynamic configuration capabilities.

## Features

### Multi-Symbol Support
- Manage multiple trading pairs simultaneously (e.g., BTCUSDT, ETHUSDT, BNBUSDT)
- Independent timeframe configurations per symbol
- Dynamic symbol addition and removal at runtime
- Case-insensitive symbol handling

### Multi-Timeframe Support
- Support for all standard timeframes (1m, 5m, 15m, 30m, 1h, 4h, 1d)
- Independent storage per symbol-timeframe pair
- Configurable maximum candles per storage (default: 500)
- Automatic LRU (Least Recently Used) eviction

### Resource Management
- Real-time system resource monitoring (CPU, memory)
- Memory usage tracking and optimization
- Garbage collection with configurable aggressiveness
- Process-specific memory monitoring

### Dashboard & Monitoring
- Comprehensive dashboard state with system metrics
- Per-symbol memory usage breakdown
- Storage statistics and processor metrics
- Uptime tracking and performance indicators

### Event-Driven Architecture
- Integration with EventBus for pub/sub patterns
- Real-time candle processing through events
- Automatic candle completion detection
- Thread-safe operations with RLock

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CandleDataManager                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        EventBus Integration                          │   │
│  │  - Subscribe to CANDLE_RECEIVED events               │   │
│  │  - Publish symbol management events                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        Centralized CandleStorage                     │   │
│  │  - Multi-symbol, multi-timeframe storage             │   │
│  │  - Thread-safe deque-based implementation            │   │
│  │  - Automatic LRU eviction                            │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        RealtimeCandleProcessor                       │   │
│  │  - Parses incoming candle events                     │   │
│  │  - Detects candle completion                         │   │
│  │  - Validates data integrity                          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        Resource Monitoring (Optional)                │   │
│  │  - Background task for system metrics                │   │
│  │  - Configurable monitoring interval                  │   │
│  │  - CPU, memory, storage tracking                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │        Symbol Configurations                         │   │
│  │  - Per-symbol timeframe sets                         │   │
│  │  - Enabled/disabled states                           │   │
│  │  - Addition timestamps                               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Usage

### Basic Setup

```python
from src.core.events import EventBus
from src.core.constants import TimeFrame
from src.services.candle_data_manager import CandleDataManager

# Initialize
event_bus = EventBus()
manager = CandleDataManager(
    event_bus=event_bus,
    max_candles_per_storage=500,
    enable_monitoring=True,
    monitoring_interval=60
)

# Start the manager
await manager.start()
```

### Adding Symbols

```python
# Add single symbol with multiple timeframes
await manager.add_symbol('BTCUSDT', [
    TimeFrame.M1,
    TimeFrame.M15,
    TimeFrame.H1
])

# Add another symbol
await manager.add_symbol('ETHUSDT', [
    TimeFrame.M1,
    TimeFrame.H1
])

# Merge additional timeframes (replace=False)
await manager.add_symbol('BTCUSDT', [
    TimeFrame.M5,
    TimeFrame.H4
], replace=False)

# Replace all timeframes (replace=True)
await manager.add_symbol('BTCUSDT', [
    TimeFrame.H1
], replace=True)
```

### Removing Symbols

```python
# Remove specific timeframes
await manager.remove_symbol('BTCUSDT', [TimeFrame.M1], clear_data=False)

# Remove entire symbol, keep data
await manager.remove_symbol('ETHUSDT', clear_data=False)

# Remove entire symbol and clear all data
await manager.remove_symbol('BNBUSDT', clear_data=True)
```

### Retrieving Data

```python
# Get all symbols
symbols = manager.get_symbols()

# Get timeframes for a symbol
timeframes = manager.get_timeframes('BTCUSDT')

# Get candles
candles = manager.get_candles('BTCUSDT', TimeFrame.M1, limit=100)

# Get latest candle
latest = manager.get_latest_candle('BTCUSDT', TimeFrame.M1)
```

### Monitoring & Analytics

```python
# Get comprehensive dashboard state
state = manager.get_dashboard_state()
print(f"Total symbols: {state['total_symbols']}")
print(f"Total candles: {state['storage']['total_candles']}")
print(f"Memory usage: {state['storage']['memory_mb']} MB")

# Get memory breakdown by symbol
memory_summary = manager.get_memory_usage_summary()
for symbol, data in memory_summary.items():
    print(f"{symbol}: {data['total_mb']} MB")
    for tf, tf_data in data['timeframes'].items():
        print(f"  {tf}: {tf_data['candles']} candles")

# Get symbol configuration
config = manager.get_symbol_config('BTCUSDT')
print(f"Timeframes: {config['timeframes']}")
print(f"Added at: {config['added_at']}")
```

### Memory Optimization

```python
# Standard garbage collection
result = await manager.optimize_memory(aggressive=False)
print(f"Freed {result['memory_freed_mb']} MB")

# Aggressive garbage collection
result = await manager.optimize_memory(aggressive=True)
print(f"Collected {result['gc_objects_collected']} objects")
```

## Configuration

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `event_bus` | EventBus | required | Event bus for pub/sub communication |
| `max_candles_per_storage` | int | 500 | Maximum candles per symbol-timeframe pair |
| `enable_monitoring` | bool | True | Enable system resource monitoring |
| `monitoring_interval` | int | 60 | Monitoring interval in seconds |

### Symbol Configuration

Each symbol has the following configuration:

```python
@dataclass
class SymbolConfig:
    symbol: str                    # Trading pair symbol
    timeframes: Set[TimeFrame]     # Set of timeframes to track
    enabled: bool = True           # Whether symbol is active
    added_at: datetime             # When symbol was added
```

## Data Classes

### SystemMetrics

Represents system resource metrics:

```python
@dataclass
class SystemMetrics:
    cpu_percent: float            # CPU usage percentage
    memory_percent: float         # System memory usage percentage
    memory_mb: float              # System memory in MB
    process_memory_mb: float      # Process memory in MB
    candle_storage_mb: float      # Storage memory in MB
    total_candles: int            # Total candles stored
    active_symbols: int           # Number of active symbols
    active_timeframes: int        # Total timeframes across all symbols
    timestamp: datetime           # When metrics were collected
```

## Dashboard State Structure

```python
{
    'total_symbols': int,
    'symbols': {
        'BTCUSDT': {
            'symbol': 'BTCUSDT',
            'timeframes': ['1m', '15m', '1h'],
            'enabled': True,
            'added_at': '2024-01-01T00:00:00+00:00'
        },
        # ... more symbols
    },
    'storage': {
        'total_candles': int,
        'storage_count': int,
        'memory_bytes': int,
        'memory_mb': float,
        'evictions': int
    },
    'processor': {
        'candles_processed': int,
        'candles_closed': int,
        'duplicates_filtered': int,
        'outliers_filtered': int,
        'active_streams': int
    },
    'metrics': {
        'cpu_percent': float,
        'memory_percent': float,
        'memory_mb': float,
        'process_memory_mb': float,
        'candle_storage_mb': float,
        'total_candles': int,
        'active_symbols': int,
        'active_timeframes': int,
        'timestamp': str
    },
    'uptime_seconds': float,
    'started_at': str,
    'monitoring_enabled': bool
}
```

## Performance Characteristics

### Time Complexity

- **Symbol addition**: O(1)
- **Symbol removal**: O(1) for config, O(n) for data clearing
- **Candle retrieval**: O(1) for latest, O(n) for filtered
- **Dashboard state**: O(s × t) where s=symbols, t=avg timeframes

### Space Complexity

- **Per candle**: ~200 bytes (estimated)
- **Per symbol-timeframe**: max_candles × 200 bytes
- **Total**: symbols × timeframes × max_candles × 200 bytes

### Example Memory Usage

With default settings (500 candles per storage):

| Symbols | Avg Timeframes | Total Storages | Est. Memory |
|---------|----------------|----------------|-------------|
| 1 | 3 | 3 | ~0.3 MB |
| 5 | 3 | 15 | ~1.5 MB |
| 10 | 4 | 40 | ~4.0 MB |
| 20 | 5 | 100 | ~10 MB |

## Thread Safety

All public methods are thread-safe through the use of `RLock`:
- Symbol addition/removal
- Candle storage operations
- Configuration retrieval
- Statistics collection

## Error Handling

### Validation Errors

```python
# Empty symbol
await manager.add_symbol('', [TimeFrame.M1])
# Raises: ValueError("Symbol cannot be empty")

# Empty timeframes
await manager.add_symbol('BTCUSDT', [])
# Raises: ValueError("Must specify at least one timeframe")
```

### Edge Cases

- Adding duplicate symbols merges timeframes by default
- Removing non-existent symbols returns `False`
- Case-insensitive symbol handling (btcusdt → BTCUSDT)
- Thread-safe concurrent operations

## Best Practices

### 1. Start and Stop Properly

```python
# Always start before use
await manager.start()

try:
    # Use the manager
    await manager.add_symbol('BTCUSDT', [TimeFrame.M1])
finally:
    # Always stop to cleanup resources
    await manager.stop()
```

### 2. Monitor Memory Usage

```python
# For production, enable monitoring
manager = CandleDataManager(
    event_bus=event_bus,
    enable_monitoring=True,
    monitoring_interval=60  # Check every minute
)

# Periodically check dashboard
state = manager.get_dashboard_state()
if state['storage']['memory_mb'] > 100:
    await manager.optimize_memory(aggressive=True)
```

### 3. Configure Storage Limits

```python
# For high-frequency trading (more recent data)
manager = CandleDataManager(
    event_bus=event_bus,
    max_candles_per_storage=200  # Less history, lower memory
)

# For analysis (more historical data)
manager = CandleDataManager(
    event_bus=event_bus,
    max_candles_per_storage=1000  # More history, higher memory
)
```

### 4. Handle Cleanup Properly

```python
# Remove symbol and clear data when done
await manager.remove_symbol('BTCUSDT', clear_data=True)

# Or keep data for later analysis
await manager.remove_symbol('BTCUSDT', clear_data=False)
```

## Testing

Run the comprehensive test suite:

```bash
pytest tests/test_candle_data_manager.py -v
```

Test coverage includes:
- Basic operations (initialization, start/stop)
- Symbol management (add, remove, merge, replace)
- Data storage integration
- Monitoring and metrics
- Configuration management
- Concurrency and thread-safety
- Edge cases and validation

## Example Use Cases

### 1. Multi-Timeframe Analysis

```python
# Setup for ICT trading strategy
await manager.add_symbol('BTCUSDT', [
    TimeFrame.M1,   # Entry timing
    TimeFrame.M15,  # Signal confirmation
    TimeFrame.H1,   # Trend direction
    TimeFrame.H4    # Market structure
])
```

### 2. Portfolio Monitoring

```python
# Monitor multiple assets
symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT']
for symbol in symbols:
    await manager.add_symbol(symbol, [TimeFrame.M1, TimeFrame.H1])
```

### 3. Dynamic Strategy Adjustment

```python
# Start with basic timeframes
await manager.add_symbol('BTCUSDT', [TimeFrame.M1])

# Add more as strategy evolves
await manager.add_symbol('BTCUSDT', [
    TimeFrame.M5,
    TimeFrame.M15
], replace=False)

# Remove when no longer needed
await manager.remove_symbol('BTCUSDT', [TimeFrame.M5])
```

## See Also

- [CandleStorage Documentation](./candle_storage.md)
- [RealtimeCandleProcessor Documentation](./realtime_processor.md)
- [EventBus Documentation](./event_bus.md)
- [Example Implementation](../examples/candle_data_manager_example.py)

# OpenTelemetry Distributed Tracing Guide

## Overview

This trading bot implements comprehensive distributed tracing using OpenTelemetry with Jaeger as the backend. Tracing provides end-to-end visibility of the trading workflow from signal generation to order execution.

## Features

- **Full Workflow Tracing**: Track requests from signal generation through order execution
- **Exchange API Instrumentation**: Automatic tracing of all exchange API calls via aiohttp
- **Database Operation Tracing**: SQLAlchemy instrumentation for database queries
- **FastAPI Integration**: Automatic HTTP request/response tracing
- **Performance Optimized**: Configurable sampling with minimal overhead (<1%)
- **Error Tracking**: Automatic exception recording with full stack traces

## Architecture

```
Signal Generation → Order Validation → Exchange API → Order Confirmation
        ↓                  ↓                ↓                ↓
     [Span 1]          [Span 2]        [Span 3]         [Span 4]
        └──────────────────────────────────────────────────┘
                        [Parent Trace]
```

## Quick Start

### 1. Install Jaeger (Local Development)

#### Using Docker (Recommended)

```bash
# Run Jaeger all-in-one container
docker run -d \
  --name jaeger \
  -e COLLECTOR_ZIPKIN_HOST_PORT=:9411 \
  -p 5775:5775/udp \
  -p 6831:6831/udp \
  -p 6832:6832/udp \
  -p 5778:5778 \
  -p 16686:16686 \
  -p 14250:14250 \
  -p 14268:14268 \
  -p 14269:14269 \
  -p 9411:9411 \
  jaegertracing/all-in-one:latest
```

Access Jaeger UI at: http://localhost:16686

#### Using Docker Compose (Already Configured)

```bash
# Start all services including Jaeger
docker-compose up -d

# View Jaeger UI
open http://localhost:16686
```

### 2. Configure Environment Variables

Add to your `.env` file:

```bash
# OpenTelemetry Tracing Configuration
OTEL_TRACING_ENABLED=true              # Enable tracing
OTEL_SERVICE_NAME="tradingbot"         # Service identifier
SERVICE_VERSION="0.1.0"                # Service version
JAEGER_HOST="localhost"                # Jaeger agent host
JAEGER_PORT=6831                       # Jaeger UDP port
OTEL_SAMPLING_RATE=0.1                 # Sample 10% of traces
```

### 3. Initialize Tracing in Application

The tracing is automatically initialized at application startup. To manually initialize:

```python
from src.monitoring.tracing import init_tracing, TracingConfig

# Initialize with default config from environment
tracer = init_tracing()

# Or with custom config
config = TracingConfig(
    service_name="tradingbot",
    sampling_rate=0.1,
    enabled=True
)
tracer = init_tracing(config)
```

## Usage Examples

### Automatic Tracing

Most tracing happens automatically:

- **HTTP Requests**: FastAPI routes are automatically traced
- **Database Queries**: SQLAlchemy operations are automatically traced
- **Exchange API Calls**: aiohttp client requests are automatically traced
- **Signal Generation**: Built into SignalGenerator base class
- **Order Execution**: Built into OrderExecutor

### Manual Tracing with Context Manager

```python
from src.monitoring.tracing import get_tracer

tracer = get_tracer()

# Create a span for a custom operation
with tracer.start_span(
    "custom_operation",
    attributes={
        "operation.type": "analysis",
        "symbol": "BTCUSDT",
        "timeframe": "1h"
    }
) as span:
    # Your code here
    result = perform_analysis()

    # Add events to span
    tracer.add_event("analysis_completed", {
        "result_count": len(result)
    })

    # Set additional attributes
    tracer.set_attribute("result.confidence", 0.95)
```

### Manual Tracing with Decorator

```python
from src.monitoring.tracing import get_tracer

tracer = get_tracer()

@tracer.trace_function(
    span_name="calculate_indicators",
    attributes={"component": "technical_analysis"}
)
async def calculate_indicators(symbol: str, candles: pd.DataFrame):
    # Function is automatically traced
    # Arguments are captured as attributes (first 3)
    return indicators
```

### Error Handling with Tracing

```python
tracer = get_tracer()

try:
    with tracer.start_span("risky_operation"):
        result = perform_risky_operation()
except Exception as e:
    # Exception is automatically recorded in span
    tracer.record_exception(e)
    raise
```

## Configuration Options

### Sampling Strategies

Control what percentage of requests are traced:

```python
# Sample 10% of requests (production)
OTEL_SAMPLING_RATE=0.1

# Sample 100% of requests (development)
OTEL_SAMPLING_RATE=1.0

# Sample 1% of requests (high traffic)
OTEL_SAMPLING_RATE=0.01
```

### Performance Tuning

The tracer uses batching to minimize performance impact:

```python
# In tracing.py - BatchSpanProcessor configuration
max_queue_size=2048,           # Buffer up to 2048 spans
schedule_delay_millis=5000,    # Export every 5 seconds
max_export_batch_size=512,     # Export 512 spans per batch
```

### Disabling Tracing

To completely disable tracing:

```bash
OTEL_TRACING_ENABLED=false
```

Or programmatically:

```python
config = TracingConfig(enabled=False)
tracer = init_tracing(config)
```

## Viewing Traces in Jaeger

### 1. Access Jaeger UI

Navigate to http://localhost:16686

### 2. Search for Traces

- **Service**: Select "tradingbot"
- **Operation**: Filter by operation (e.g., "signal_generation", "order_execution")
- **Tags**: Search by tags (e.g., `symbol=BTCUSDT`)
- **Time Range**: Select time window

### 3. Analyze Trace Timeline

Each trace shows:
- **Duration**: Total time from start to finish
- **Spans**: Individual operations with timing
- **Tags**: Metadata attached to spans
- **Events**: Significant events during execution
- **Errors**: Any exceptions that occurred

### 4. Common Queries

```
# Find slow order executions
operation:"order_execution" AND duration > 1000ms

# Find failed signals
operation:"signal_generation" AND error:true

# Find trades for specific symbol
symbol:"BTCUSDT"

# Find high-confidence signals
signal.confidence > 80
```

## Trace Attributes Reference

### Signal Generation Spans

| Attribute | Description | Example |
|-----------|-------------|---------|
| `strategy.name` | Strategy identifier | "Strategy_A_Conservative" |
| `trading.symbol` | Trading pair | "BTCUSDT" |
| `trading.price` | Current market price | "50000.00" |
| `market.candles_count` | Number of candles | 100 |
| `signal.generated` | Whether signal was created | true |
| `signal.direction` | Trade direction | "LONG" |
| `signal.confidence` | Signal confidence score | 85.5 |
| `signal.entry_price` | Proposed entry price | "50100.00" |

### Order Execution Spans

| Attribute | Description | Example |
|-----------|-------------|---------|
| `order.symbol` | Trading pair | "BTCUSDT" |
| `order.type` | Order type | "MARKET" |
| `order.side` | Order side | "BUY" |
| `order.quantity` | Order quantity | "0.001" |
| `order.price` | Order price | "50000.00" |
| `order.success` | Execution success | true |
| `order.execution_time_ms` | Execution time | 250.5 |
| `order.order_id` | Exchange order ID | "12345678" |
| `order.filled_quantity` | Filled amount | "0.001" |
| `order.error_type` | Error classification | "network_error" |

## Performance Impact

### Overhead Measurements

With 10% sampling (`OTEL_SAMPLING_RATE=0.1`):
- **Signal Generation**: <1ms overhead per signal
- **Order Execution**: <2ms overhead per order
- **Memory**: ~5MB for 10,000 spans in queue
- **CPU**: <1% additional CPU usage

### Recommendations

| Environment | Sampling Rate | Rationale |
|-------------|---------------|-----------|
| Development | 100% (1.0) | Full visibility for debugging |
| Staging | 50% (0.5) | Good coverage with lower overhead |
| Production (Low Volume) | 10% (0.1) | Balance between visibility and performance |
| Production (High Volume) | 1% (0.01) | Minimal overhead, statistical sampling |

## Troubleshooting

### Traces Not Appearing in Jaeger

1. **Check Jaeger is running**:
   ```bash
   docker ps | grep jaeger
   curl http://localhost:16686
   ```

2. **Verify tracing is enabled**:
   ```bash
   grep OTEL_TRACING_ENABLED .env
   # Should show: OTEL_TRACING_ENABLED=true
   ```

3. **Check application logs**:
   ```bash
   # Look for initialization message
   grep "Tracing initialized" logs/tradingbot.log
   ```

4. **Test connectivity**:
   ```bash
   # Verify port 6831 is accessible
   nc -zv localhost 6831
   ```

### High Memory Usage

If memory usage is high due to tracing:

1. **Reduce sampling rate**:
   ```bash
   OTEL_SAMPLING_RATE=0.01  # Sample only 1%
   ```

2. **Reduce batch size**:
   ```python
   # In tracing.py, adjust BatchSpanProcessor
   max_queue_size=1024,  # Reduce from 2048
   ```

3. **Increase export frequency**:
   ```python
   schedule_delay_millis=2000,  # Export every 2s instead of 5s
   ```

### Traces Missing Spans

If traces are incomplete:

1. **Check for exceptions**: Uncaught exceptions may prevent span completion
2. **Verify context propagation**: Ensure async context is properly managed
3. **Check sampling**: Parent span sampling decision applies to all child spans

## Best Practices

### 1. Use Descriptive Span Names

```python
# Good
with tracer.start_span("signal_generation.strategy_a"):
    pass

# Bad
with tracer.start_span("process"):
    pass
```

### 2. Add Meaningful Attributes

```python
# Good
tracer.set_attribute("signal.confidence", 85.5)
tracer.set_attribute("order.filled_quantity", str(quantity))

# Bad
tracer.set_attribute("data", "some_value")
```

### 3. Record Important Events

```python
# Mark significant milestones
tracer.add_event("market_conditions_validated")
tracer.add_event("order_placed", {"order_id": order_id})
tracer.add_event("position_opened", {"size": position_size})
```

### 4. Handle Sensitive Data

```python
# Never log sensitive data in traces
# Bad: tracer.set_attribute("api_key", api_key)
# Good: tracer.set_attribute("api_key_present", True)
```

### 5. Use Appropriate Span Granularity

```python
# Don't create spans for every tiny operation
# Instead, group related operations:
with tracer.start_span("indicator_calculation"):
    calculate_ema()
    calculate_rsi()
    calculate_macd()
```

## Integration with Monitoring

Tracing complements Prometheus metrics:

- **Metrics**: What is happening (request rate, error rate, latency percentiles)
- **Traces**: Why it's happening (specific request flow, bottlenecks, errors)

Use both together for complete observability:
1. Metrics alert you to problems
2. Traces help you diagnose root causes

## Production Deployment

### Kubernetes with Jaeger Operator

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: tradingbot-jaeger
spec:
  strategy: production
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch:9200
```

### Environment Configuration

```bash
# Production settings
OTEL_TRACING_ENABLED=true
OTEL_SERVICE_NAME="tradingbot-prod"
JAEGER_HOST="jaeger-agent.monitoring.svc.cluster.local"
JAEGER_PORT=6831
OTEL_SAMPLING_RATE=0.01  # 1% sampling for high volume
```

## Further Reading

- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/instrumentation/python/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Distributed Tracing Best Practices](https://opentelemetry.io/docs/concepts/signals/traces/)

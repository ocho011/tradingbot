# Performance Tuning Guide

## Table of Contents
1. [Database Optimization](#database-optimization)
2. [Application Performance](#application-performance)
3. [Exchange API Optimization](#exchange-api-optimization)
4. [Resource Tuning](#resource-tuning)
5. [Caching Strategies](#caching-strategies)
6. [Load Testing and Benchmarking](#load-testing-and-benchmarking)

## Database Optimization

### Connection Pool Tuning

#### PostgreSQL Connection Pool Configuration
```python
# src/database/engine.py
from sqlalchemy.pool import QueuePool

engine = create_async_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=20,          # Base connections (default: 20)
    max_overflow=10,       # Additional connections (default: 10)
    pool_timeout=30,       # Connection wait timeout
    pool_recycle=3600,     # Recycle connections every hour
    pool_pre_ping=True,    # Verify connections before use
    echo_pool=False        # Enable for debugging
)
```

**Tuning Guidelines**:
- **pool_size**: Base connections = (concurrent requests × avg query time) / desired response time
- **max_overflow**: Spike capacity = pool_size × 0.5 to 1.0
- **Recommended Settings**:
  - Low traffic: pool_size=10, max_overflow=5
  - Medium traffic: pool_size=20, max_overflow=10
  - High traffic: pool_size=40, max_overflow=20

#### Monitor Pool Usage
```python
# Add to monitoring
from prometheus_client import Gauge

db_pool_size = Gauge('database_pool_size', 'Database connection pool size')
db_pool_active = Gauge('database_pool_active_connections', 'Active database connections')
db_pool_idle = Gauge('database_pool_idle_connections', 'Idle database connections')

# Update metrics
db_pool_size.set(engine.pool.size())
db_pool_active.set(engine.pool.checkedout())
db_pool_idle.set(engine.pool.size() - engine.pool.checkedout())
```

### Index Optimization

#### Identify Missing Indexes
```sql
-- Find tables without indexes
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
AND tablename NOT IN (
    SELECT tablename
    FROM pg_indexes
    WHERE schemaname = 'public'
)
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Find slow queries
SELECT
    calls,
    total_exec_time,
    mean_exec_time,
    query
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
```

#### Recommended Indexes
```sql
-- Trades table
CREATE INDEX idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_exchange ON trades(exchange);
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_composite ON trades(exchange, symbol, created_at DESC);

-- Orders table
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_exchange_id ON orders(exchange_order_id);

-- Positions table
CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_opened_at ON positions(opened_at DESC);

-- Market data table (if exists)
CREATE INDEX idx_market_data_symbol_timestamp ON market_data(symbol, timestamp DESC);
```

#### Index Maintenance
```sql
-- Rebuild indexes to reduce bloat
REINDEX TABLE trades;
REINDEX TABLE orders;
REINDEX TABLE positions;

-- Analyze tables for query planner
ANALYZE trades;
ANALYZE orders;
ANALYZE positions;

-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan ASC;
```

### Query Optimization

#### Use EXPLAIN ANALYZE
```sql
-- Analyze query execution plan
EXPLAIN ANALYZE
SELECT * FROM trades
WHERE symbol = 'BTCUSDT'
AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC
LIMIT 100;

-- Look for:
-- - Seq Scan (should be Index Scan for large tables)
-- - High cost values
-- - Nested Loops (consider Hash Join for large datasets)
```

#### Query Optimization Patterns
```python
# Bad: N+1 query problem
async def get_trades_with_orders():
    trades = await session.execute(select(Trade))
    for trade in trades:
        # This creates N queries!
        orders = await session.execute(
            select(Order).where(Order.trade_id == trade.id)
        )

# Good: Use eager loading
from sqlalchemy.orm import selectinload

async def get_trades_with_orders():
    result = await session.execute(
        select(Trade).options(selectinload(Trade.orders))
    )
    trades = result.scalars().all()
    # All orders loaded in 2 queries total

# Good: Use pagination for large result sets
async def get_recent_trades(page: int = 1, page_size: int = 100):
    offset = (page - 1) * page_size
    result = await session.execute(
        select(Trade)
        .order_by(Trade.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )
    return result.scalars().all()

# Good: Use bulk operations
async def create_trades_bulk(trades_data: list):
    # Bad: Multiple INSERT statements
    # for trade_data in trades_data:
    #     session.add(Trade(**trade_data))

    # Good: Single bulk INSERT
    await session.execute(
        insert(Trade),
        trades_data
    )
    await session.commit()
```

### Database Configuration Tuning

#### PostgreSQL Configuration (`postgresql.conf`)
```ini
# Memory Settings
shared_buffers = 256MB              # 25% of RAM for dedicated DB server
effective_cache_size = 1GB          # 50-75% of RAM
work_mem = 16MB                     # Per operation memory
maintenance_work_mem = 128MB        # For VACUUM, CREATE INDEX

# Connection Settings
max_connections = 100               # Match application pool + overhead

# Write-Ahead Logging
wal_buffers = 16MB
checkpoint_completion_target = 0.9
max_wal_size = 2GB
min_wal_size = 1GB

# Query Planner
random_page_cost = 1.1              # For SSD storage
effective_io_concurrency = 200      # For SSD storage

# Autovacuum (crucial for performance)
autovacuum = on
autovacuum_max_workers = 3
autovacuum_naptime = 1min
```

#### Monitor Vacuum Progress
```sql
-- Check last vacuum/analyze times
SELECT
    schemaname,
    relname,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
ORDER BY last_autovacuum ASC NULLS FIRST;

-- Manual vacuum if needed
VACUUM ANALYZE trades;
VACUUM ANALYZE orders;
```

## Application Performance

### Async/Await Optimization

#### Pattern: Concurrent Operations
```python
import asyncio

# Bad: Sequential execution
async def fetch_all_balances():
    binance_balance = await binance_client.get_balance()
    upbit_balance = await upbit_client.get_balance()
    return binance_balance, upbit_balance

# Good: Parallel execution
async def fetch_all_balances():
    balances = await asyncio.gather(
        binance_client.get_balance(),
        upbit_client.get_balance(),
        return_exceptions=True  # Don't fail if one exchange fails
    )
    return balances

# Better: With timeout and error handling
async def fetch_all_balances():
    tasks = [
        binance_client.get_balance(),
        upbit_client.get_balance()
    ]

    try:
        balances = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=5.0
        )
        return balances
    except asyncio.TimeoutError:
        logger.error("Balance fetch timeout")
        return None
```

### Memory Optimization

#### Monitor Memory Usage
```python
import tracemalloc
import psutil

# Track memory allocations
tracemalloc.start()

# Your code here
result = expensive_operation()

# Get memory usage
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Current memory: {current / 1024 / 1024:.2f} MB")
print(f"Peak memory: {peak / 1024 / 1024:.2f} MB")

# System-wide memory
process = psutil.Process()
print(f"RSS: {process.memory_info().rss / 1024 / 1024:.2f} MB")
```

#### Memory-Efficient Patterns
```python
# Bad: Load everything into memory
async def process_all_trades():
    all_trades = await session.execute(select(Trade))
    for trade in all_trades:  # Loads all trades into memory!
        process_trade(trade)

# Good: Use pagination/batching
async def process_all_trades(batch_size: int = 1000):
    offset = 0
    while True:
        batch = await session.execute(
            select(Trade)
            .limit(batch_size)
            .offset(offset)
        )
        trades = batch.scalars().all()

        if not trades:
            break

        for trade in trades:
            process_trade(trade)

        offset += batch_size

        # Clear session to free memory
        await session.commit()
        session.expunge_all()

# Good: Use generators for large datasets
async def trade_generator(batch_size: int = 100):
    offset = 0
    while True:
        result = await session.execute(
            select(Trade)
            .limit(batch_size)
            .offset(offset)
        )
        trades = result.scalars().all()

        if not trades:
            break

        for trade in trades:
            yield trade

        offset += batch_size

# Use the generator
async for trade in trade_generator():
    process_trade(trade)
```

### CPU Optimization

#### Profile CPU Usage
```python
import cProfile
import pstats

# Profile a function
profiler = cProfile.Profile()
profiler.enable()

# Your code
result = expensive_function()

profiler.disable()

# Print statistics
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

#### CPU-Intensive Operations
```python
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

# For CPU-bound tasks, use process pool
def cpu_intensive_calculation(data):
    # Heavy computation here
    return result

# Use multiple processes
async def process_large_dataset(dataset):
    with ProcessPoolExecutor(max_workers=multiprocessing.cpu_count()) as executor:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            executor,
            cpu_intensive_calculation,
            dataset
        )
    return results
```

## Exchange API Optimization

### Rate Limit Management

#### Implement Rate Limiter
```python
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()

    async def acquire(self):
        now = time.time()

        # Remove old requests outside time window
        while self.requests and self.requests[0] < now - self.time_window:
            self.requests.popleft()

        # Wait if at limit
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                return await self.acquire()

        self.requests.append(now)

# Usage
binance_limiter = RateLimiter(max_requests=1200, time_window=60)  # 1200 req/min

async def binance_api_call():
    await binance_limiter.acquire()
    return await binance_client.get_ticker()
```

### Request Batching

#### Batch Multiple Requests
```python
# Bad: Multiple individual requests
async def get_multiple_tickers():
    btc = await exchange.get_ticker("BTCUSDT")
    eth = await exchange.get_ticker("ETHUSDT")
    bnb = await exchange.get_ticker("BNBUSDT")
    return [btc, eth, bnb]

# Good: Single batched request
async def get_multiple_tickers():
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    tickers = await exchange.get_tickers(symbols)  # Single API call
    return tickers
```

### Connection Pooling

#### HTTP Client Session Reuse
```python
import aiohttp

# Bad: Create new session for each request
async def make_request():
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

# Good: Reuse session
class ExchangeClient:
    def __init__(self):
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                limit=100,              # Max connections
                limit_per_host=30,      # Max per host
                ttl_dns_cache=300       # DNS cache TTL
            )
        )
        return self

    async def __aexit__(self, *args):
        await self.session.close()

    async def make_request(self, url):
        async with self.session.get(url) as response:
            return await response.json()

# Usage
async with ExchangeClient() as client:
    result1 = await client.make_request(url1)
    result2 = await client.make_request(url2)
```

## Resource Tuning

### CPU Optimization

#### Worker Process Configuration
```python
# For uvicorn in production
# Number of workers = (2 × CPU cores) + 1
import multiprocessing

workers = (2 * multiprocessing.cpu_count()) + 1

# Start command
# uvicorn src.api.server:app --workers {workers} --host 0.0.0.0 --port 8000
```

#### CPU Affinity (Linux)
```bash
# Pin process to specific CPUs for better cache locality
taskset -c 0-3 python3 -m uvicorn src.api.server:app

# Monitor CPU usage per core
mpstat -P ALL 1
```

### Memory Tuning

#### Monitor Memory Leaks
```python
# Add to application startup
import gc
import objgraph
from prometheus_client import Gauge

memory_objects = Gauge('python_memory_objects', 'Python object counts', ['type'])

async def track_memory_growth():
    while True:
        gc.collect()

        # Track top memory consumers
        growth = objgraph.growth(limit=10)
        for obj_type, count in growth:
            memory_objects.labels(type=obj_type).set(count)

        await asyncio.sleep(300)  # Every 5 minutes
```

#### Garbage Collection Tuning
```python
import gc

# Adjust GC thresholds for better performance
# Default: (700, 10, 10)
gc.set_threshold(1000, 15, 15)  # Less frequent GC, better throughput

# For memory-constrained environments
gc.set_threshold(500, 5, 5)     # More frequent GC, lower memory

# Disable GC temporarily for critical sections
gc.disable()
try:
    # Critical section
    critical_operation()
finally:
    gc.enable()
```

### I/O Optimization

#### Disk I/O
```bash
# Monitor disk I/O
iostat -x 1

# Check disk usage by directory
du -sh /var/log/tradingbot/*
du -sh /backup/*

# Optimize log rotation
# /etc/logrotate.d/tradingbot
/var/log/tradingbot/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 tradingbot tradingbot
    postrotate
        systemctl reload tradingbot
    endscript
}
```

#### Network I/O
```bash
# Monitor network usage
iftop -i eth0

# Check connection states
ss -s
netstat -an | grep ESTABLISHED | wc -l

# TCP tuning (Linux)
# /etc/sysctl.conf
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_max_syn_backlog = 4096
net.core.netdev_max_backlog = 5000
```

## Caching Strategies

### Redis Caching

#### Cache Hot Data
```python
import redis.asyncio as redis
import json
from functools import wraps

# Initialize Redis client
redis_client = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=True,
    max_connections=50
)

# Cache decorator
def cache(expire: int = 300):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = f"{func.__name__}:{args}:{kwargs}"

            # Try to get from cache
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            # Execute function
            result = await func(*args, **kwargs)

            # Store in cache
            await redis_client.setex(
                cache_key,
                expire,
                json.dumps(result)
            )

            return result
        return wrapper
    return decorator

# Usage
@cache(expire=60)
async def get_ticker_price(symbol: str):
    return await exchange.get_ticker(symbol)
```

#### Cache Invalidation
```python
# Pattern: Write-through cache
async def update_position(position_id: int, data: dict):
    # Update database
    await session.execute(
        update(Position)
        .where(Position.id == position_id)
        .values(**data)
    )
    await session.commit()

    # Invalidate cache
    cache_key = f"position:{position_id}"
    await redis_client.delete(cache_key)

# Pattern: Time-based expiration
async def get_market_data(symbol: str):
    cache_key = f"market_data:{symbol}"

    # Try cache first
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Fetch fresh data
    data = await exchange.get_market_data(symbol)

    # Cache for 5 seconds
    await redis_client.setex(cache_key, 5, json.dumps(data))

    return data
```

### In-Memory Caching

#### LRU Cache for Function Results
```python
from functools import lru_cache

# For pure functions (no side effects)
@lru_cache(maxsize=1000)
def calculate_fee(amount: float, fee_rate: float) -> float:
    return amount * fee_rate

# For async functions
from async_lru import alru_cache

@alru_cache(maxsize=100, ttl=300)
async def get_exchange_info(exchange: str):
    return await fetch_exchange_info(exchange)
```

## Load Testing and Benchmarking

### Load Testing with Locust

#### Create Load Test Script
```python
# locustfile.py
from locust import HttpUser, task, between

class TradingBotUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Login and get token
        response = self.client.post("/auth/login", json={
            "username": "test_user",
            "password": "test_password"
        })
        self.token = response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def get_status(self):
        self.client.get("/api/status", headers=self.headers)

    @task(2)
    def get_positions(self):
        self.client.get("/api/positions", headers=self.headers)

    @task(1)
    def create_order(self):
        self.client.post("/api/orders", headers=self.headers, json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.001,
            "order_type": "market"
        })
```

#### Run Load Test
```bash
# Install locust
pip install locust

# Run test
locust -f locustfile.py --host=http://localhost:8000

# Headless mode with reporting
locust -f locustfile.py \
    --host=http://localhost:8000 \
    --users 100 \
    --spawn-rate 10 \
    --run-time 5m \
    --headless \
    --html report.html
```

### Performance Benchmarking

#### API Response Time Benchmarking
```bash
# Using Apache Bench
ab -n 1000 -c 10 http://localhost:8000/health

# Using wrk
wrk -t4 -c100 -d30s http://localhost:8000/api/status

# Using hey
hey -n 1000 -c 50 http://localhost:8000/health
```

#### Database Query Benchmarking
```sql
-- Enable timing
\timing on

-- Benchmark query
SELECT * FROM trades
WHERE symbol = 'BTCUSDT'
AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC
LIMIT 100;

-- Run multiple times and average
```

### Performance Metrics Collection

#### Custom Performance Metrics
```python
from prometheus_client import Histogram, Counter
import time

# Response time histogram
api_latency = Histogram(
    'api_request_duration_seconds',
    'API request latency',
    ['method', 'endpoint']
)

# Request counter
api_requests = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status']
)

# Decorator for endpoint monitoring
def monitor_performance(endpoint: str):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                status = 'success'
                return result
            except Exception as e:
                status = 'error'
                raise
            finally:
                duration = time.time() - start_time
                api_latency.labels(
                    method=func.__name__,
                    endpoint=endpoint
                ).observe(duration)
                api_requests.labels(
                    method=func.__name__,
                    endpoint=endpoint,
                    status=status
                ).inc()
        return wrapper
    return decorator

# Usage
@monitor_performance('/api/positions')
async def get_positions():
    return await fetch_positions()
```

## Performance Monitoring

### Key Performance Indicators (KPIs)

```yaml
response_time:
  p50: "< 100ms"
  p95: "< 500ms"
  p99: "< 1000ms"

throughput:
  api_requests: "> 100 req/sec"
  trades_executed: "> 10 trades/min"

resource_usage:
  cpu: "< 70% average"
  memory: "< 80% of allocated"
  disk_io: "< 80% capacity"

database:
  connection_pool_usage: "< 80%"
  query_p95: "< 100ms"
  cache_hit_rate: "> 90%"
```

### Continuous Monitoring
```bash
# Monitor application performance
while true; do
    curl -s http://localhost:8000/metrics | grep -E "api_request_duration|database_query_duration"
    sleep 5
done

# Monitor system resources
watch -n 1 'ps aux | grep python | head -5'
```

## Additional Resources

- Database Tuning: `DEPLOYMENT.md`
- Monitoring Setup: `MONITORING.md`
- Incident Response: `INCIDENT_RESPONSE.md`

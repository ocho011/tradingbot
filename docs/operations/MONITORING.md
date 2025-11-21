# Monitoring and Alert Definitions

## Table of Contents
1. [Monitoring Overview](#monitoring-overview)
2. [Metrics Collection](#metrics-collection)
3. [Alert Definitions](#alert-definitions)
4. [Dashboards](#dashboards)
5. [Log Aggregation](#log-aggregation)
6. [SLA and SLO Definitions](#sla-and-slo-definitions)

## Monitoring Overview

### Monitoring Stack
- **Metrics**: Prometheus (port 9090)
- **Visualization**: Grafana (port 3000)
- **Logging**: Structured JSON logs
- **Tracing**: Distributed tracing with correlation IDs
- **Alerting**: Prometheus Alertmanager

### Access
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **Metrics Endpoint**: http://localhost:8000/metrics

## Metrics Collection

### Application Metrics

#### Trading Metrics
```python
# Trades executed
trading_trades_total{exchange="binance",symbol="BTCUSDT",side="buy"} 150

# Trade success rate
trading_trade_success_rate{exchange="binance"} 0.98

# Average trade value (USD)
trading_trade_value_usd{exchange="binance"} 1000.50

# Active positions
trading_active_positions{exchange="binance",symbol="BTCUSDT"} 5

# Profit/Loss total
trading_pnl_total_usd{exchange="binance"} 5000.00

# Win rate
trading_win_rate{exchange="binance"} 0.65
```

#### System Health Metrics
```python
# Request rate
http_requests_total{method="GET",endpoint="/api/status"} 1000

# Request duration (p50, p95, p99)
http_request_duration_seconds{quantile="0.5"} 0.1
http_request_duration_seconds{quantile="0.95"} 0.5
http_request_duration_seconds{quantile="0.99"} 1.0

# Error rate
http_errors_total{status_code="500"} 5

# Active connections
http_active_connections 50

# Uptime
tradingbot_uptime_seconds 86400
```

#### Database Metrics
```python
# Connection pool
database_pool_size 20
database_pool_active_connections 15
database_pool_idle_connections 5

# Query performance
database_query_duration_seconds{operation="select"} 0.05
database_query_duration_seconds{operation="insert"} 0.02

# Query count
database_queries_total{operation="select"} 10000
```

#### Exchange Metrics
```python
# API calls
exchange_api_calls_total{exchange="binance",endpoint="/v3/order"} 500

# API errors
exchange_api_errors_total{exchange="binance",error_type="timeout"} 5

# API latency
exchange_api_latency_seconds{exchange="binance"} 0.15

# Rate limit usage
exchange_rate_limit_usage{exchange="binance"} 0.75

# WebSocket connections
exchange_websocket_connections{exchange="binance",status="connected"} 3
```

#### Strategy Metrics
```python
# Strategy executions
strategy_executions_total{strategy="mean_reversion"} 100

# Strategy profit
strategy_pnl_usd{strategy="mean_reversion"} 1000.00

# Strategy signals
strategy_signals_total{strategy="mean_reversion",signal="buy"} 50
```

#### Resource Metrics
```python
# CPU usage
process_cpu_percent 45.5

# Memory usage
process_memory_bytes 524288000

# Disk I/O
process_disk_read_bytes 1000000
process_disk_write_bytes 2000000

# Network I/O
process_network_sent_bytes 5000000
process_network_received_bytes 3000000
```

### Prometheus Scrape Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'tradingbot-production'
    environment: 'production'

scrape_configs:
  - job_name: 'tradingbot'
    static_configs:
      - targets: ['tradingbot:8000']
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: '/metrics'

  - job_name: 'postgresql'
    static_configs:
      - targets: ['postgresql:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:9121']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

## Alert Definitions

### Critical Alerts (P0)

#### Trading Bot Down
```yaml
- alert: TradingBotDown
  expr: up{job="tradingbot"} == 0
  for: 1m
  labels:
    severity: critical
    team: trading
  annotations:
    summary: "Trading bot is down"
    description: "Trading bot {{ $labels.instance }} has been down for more than 1 minute"
    runbook_url: "https://runbook/tradingbot-down"
```

#### High Error Rate
```yaml
- alert: HighErrorRate
  expr: rate(http_errors_total[5m]) > 10
  for: 5m
  labels:
    severity: critical
    team: trading
  annotations:
    summary: "High error rate detected"
    description: "Error rate is {{ $value }} errors/sec (threshold: 10)"
    runbook_url: "https://runbook/high-error-rate"
```

#### Database Connection Pool Exhausted
```yaml
- alert: DatabasePoolExhausted
  expr: database_pool_idle_connections == 0
  for: 2m
  labels:
    severity: critical
    team: infrastructure
  annotations:
    summary: "Database connection pool exhausted"
    description: "No idle database connections available for {{ $value }} minutes"
    runbook_url: "https://runbook/db-pool-exhausted"
```

#### Exchange API Failures
```yaml
- alert: ExchangeAPIFailures
  expr: rate(exchange_api_errors_total[5m]) > 5
  for: 5m
  labels:
    severity: critical
    team: trading
  annotations:
    summary: "High exchange API failure rate"
    description: "Exchange {{ $labels.exchange }} API error rate: {{ $value }}/sec"
    runbook_url: "https://runbook/exchange-api-failures"
```

#### Trading Halt Detected
```yaml
- alert: TradingHalt
  expr: |
    (time() - max(trading_signals_generated) > 60) or
    (time() - max(trading_trades_total) > 60)
  for: 10s
  labels:
    severity: critical
    team: trading
  annotations:
    summary: "Trading halt detected - no signals or trades"
    description: "No trading signals generated or trades executed for more than 60 seconds"
    runbook_url: "https://runbook/trading-halt"
```

#### High API Error Rate Percentage
```yaml
- alert: HighAPIErrorRatePercent
  expr: |
    (rate(http_errors_total[5m]) / rate(http_requests_total[5m])) * 100 > 10
  for: 5m
  labels:
    severity: critical
    team: trading
  annotations:
    summary: "Critical API error rate"
    description: "API error rate: {{ $value | humanizePercentage }} (threshold: 10%)"
    runbook_url: "https://runbook/high-api-error-rate"
```

#### Critical Memory Usage
```yaml
- alert: CriticalMemoryUsage
  expr: process_memory_percent > 90
  for: 5m
  labels:
    severity: critical
    team: infrastructure
  annotations:
    summary: "Critical memory usage detected"
    description: "Memory usage: {{ $value }}% (threshold: 90%)"
    runbook_url: "https://runbook/critical-memory-usage"
```

### High Priority Alerts (P1)

#### High Response Time
```yaml
- alert: HighResponseTime
  expr: http_request_duration_seconds{quantile="0.95"} > 1.0
  for: 10m
  labels:
    severity: high
    team: trading
  annotations:
    summary: "High API response time"
    description: "P95 response time: {{ $value }}s (threshold: 1s)"
    runbook_url: "https://runbook/high-response-time"
```

#### High Memory Usage
```yaml
- alert: HighMemoryUsage
  expr: process_memory_percent > 85
  for: 15m
  labels:
    severity: high
    team: infrastructure
  annotations:
    summary: "High memory usage detected"
    description: "Memory usage: {{ $value }}% (threshold: 85%)"
    runbook_url: "https://runbook/high-memory-usage"
```

#### Trading Strategy Losing Money
```yaml
- alert: StrategyLosingMoney
  expr: strategy_pnl_usd < -1000
  for: 1h
  labels:
    severity: high
    team: trading
  annotations:
    summary: "Strategy {{ $labels.strategy }} is losing money"
    description: "Current P&L: {{ $value }} USD"
    runbook_url: "https://runbook/strategy-losing-money"
```

#### Database Replication Lag
```yaml
- alert: DatabaseReplicationLag
  expr: pg_replication_lag_seconds > 60
  for: 5m
  labels:
    severity: high
    team: infrastructure
  annotations:
    summary: "Database replication lag detected"
    description: "Replication lag: {{ $value }} seconds (threshold: 60s)"
    runbook_url: "https://runbook/db-replication-lag"
```

#### Warning API Error Rate
```yaml
- alert: WarningAPIErrorRate
  expr: |
    (rate(http_errors_total[5m]) / rate(http_requests_total[5m])) * 100 > 5
  for: 5m
  labels:
    severity: high
    team: trading
  annotations:
    summary: "Elevated API error rate"
    description: "API error rate: {{ $value | humanizePercentage }} (threshold: 5%)"
    runbook_url: "https://runbook/elevated-api-error-rate"
```

#### Warning Memory Usage
```yaml
- alert: WarningMemoryUsage
  expr: process_memory_percent > 80
  for: 10m
  labels:
    severity: high
    team: infrastructure
  annotations:
    summary: "Warning memory usage detected"
    description: "Memory usage: {{ $value }}% (threshold: 80%)"
    runbook_url: "https://runbook/warning-memory-usage"
```

#### Position Risk High
```yaml
- alert: PositionRiskHigh
  expr: |
    (sum(abs(trading_active_positions)) / max(position_size_limit)) * 100 > 90
  for: 5m
  labels:
    severity: high
    team: trading
  annotations:
    summary: "Position risk approaching limit"
    description: "Total position size at {{ $value }}% of limit (threshold: 90%)"
    runbook_url: "https://runbook/position-risk-high"
```

#### Database Query Latency High
```yaml
- alert: DatabaseQueryLatencyHigh
  expr: database_query_duration_seconds{operation="select"} > 0.5
  for: 5m
  labels:
    severity: high
    team: infrastructure
  annotations:
    summary: "High database query latency"
    description: "Query latency: {{ $value }}s (threshold: 500ms)"
    runbook_url: "https://runbook/db-query-latency-high"
```

### Medium Priority Alerts (P2)

#### Increased Latency
```yaml
- alert: IncreasedLatency
  expr: exchange_api_latency_seconds > 1.0
  for: 15m
  labels:
    severity: medium
    team: trading
  annotations:
    summary: "Increased exchange API latency"
    description: "Exchange {{ $labels.exchange }} latency: {{ $value }}s"
    runbook_url: "https://runbook/increased-latency"
```

#### Low Trading Volume
```yaml
- alert: LowTradingVolume
  expr: rate(trading_trades_total[1h]) < 1
  for: 2h
  labels:
    severity: medium
    team: trading
  annotations:
    summary: "Low trading volume detected"
    description: "Trade rate: {{ $value }} trades/hour (expected: >1)"
    runbook_url: "https://runbook/low-trading-volume"
```

#### Disk Space Low
```yaml
- alert: DiskSpaceLow
  expr: node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.15
  for: 30m
  labels:
    severity: medium
    team: infrastructure
  annotations:
    summary: "Disk space running low"
    description: "Available disk space: {{ $value | humanizePercentage }}"
    runbook_url: "https://runbook/disk-space-low"
```

### Warning Alerts (P3)

#### Certificate Expiring Soon
```yaml
- alert: CertificateExpiringSoon
  expr: ssl_certificate_expiry_days < 30
  for: 1d
  labels:
    severity: warning
    team: infrastructure
  annotations:
    summary: "SSL certificate expiring soon"
    description: "Certificate expires in {{ $value }} days"
    runbook_url: "https://runbook/certificate-expiring"
```

#### Old Prometheus Data
```yaml
- alert: OldPrometheusData
  expr: time() - prometheus_tsdb_lowest_timestamp > 604800
  for: 1d
  labels:
    severity: warning
    team: infrastructure
  annotations:
    summary: "Old Prometheus data detected"
    description: "Oldest data is {{ $value | humanizeDuration }} old"
    runbook_url: "https://runbook/old-prometheus-data"
```

## Dashboards

### Main Overview Dashboard

**Sections**:
1. **System Health**
   - Uptime percentage (last 24h, 7d, 30d)
   - Request rate and error rate
   - P95/P99 response times
   - Active connections

2. **Trading Performance**
   - Total trades (24h, 7d, 30d)
   - Win rate and P&L
   - Active positions by exchange
   - Strategy performance comparison

3. **Resource Usage**
   - CPU usage graph
   - Memory usage graph
   - Disk I/O
   - Network I/O

4. **Exchange Health**
   - API call rate by exchange
   - API error rate
   - API latency (p95)
   - WebSocket connection status

5. **Database Performance**
   - Query rate
   - Query latency (p95)
   - Connection pool usage
   - Slow query count

### Trading Dashboard

**Panels**:
- Total P&L (gauge)
- Trades per hour (graph)
- Win rate by strategy (bar chart)
- Position sizes (table)
- Trade distribution by symbol (pie chart)
- Cumulative P&L (line graph)
- Trade success rate (gauge)
- Average trade value (stat)

### System Health Dashboard

**Panels**:
- Service status (stat panel)
- HTTP request rate (graph)
- HTTP error rate (graph)
- Response time percentiles (graph)
- CPU usage (graph)
- Memory usage (graph)
- Disk usage (graph)
- Network I/O (graph)

### Exchange Dashboard

**Panels**:
- API calls per exchange (graph)
- API error rate per exchange (graph)
- API latency per exchange (heatmap)
- Rate limit usage (gauge)
- WebSocket status (stat)
- Order book depth (graph)
- Account balance (table)

### Database Dashboard

**Panels**:
- Query rate (graph)
- Query latency (graph)
- Connection pool usage (graph)
- Cache hit rate (gauge)
- Slow queries (table)
- Database size (stat)
- Table sizes (table)

## Log Aggregation

### Log Structure
```json
{
  "timestamp": "2024-01-17T12:00:00Z",
  "level": "INFO",
  "logger": "src.trading.executor",
  "message": "Trade executed successfully",
  "request_id": "req-123456",
  "user_id": "system",
  "correlation_id": "corr-789",
  "source": {
    "file": "/app/src/trading/executor.py",
    "line": 45,
    "function": "execute_trade"
  },
  "process": {
    "pid": 1234,
    "name": "MainProcess"
  },
  "thread": {
    "id": 5678,
    "name": "ThreadPoolExecutor-0"
  },
  "extra": {
    "trade_id": "12345",
    "symbol": "BTCUSDT",
    "side": "buy",
    "quantity": 0.1,
    "price": 50000.00,
    "exchange": "binance"
  }
}
```

### Log Levels Usage
- **DEBUG**: Detailed diagnostic information
- **INFO**: General informational messages (trades, system state changes)
- **WARNING**: Warning messages (rate limits approaching, degraded performance)
- **ERROR**: Error messages (failed trades, API errors)
- **CRITICAL**: Critical issues requiring immediate attention

### Log Retention
- **DEBUG**: 7 days
- **INFO**: 30 days
- **WARNING**: 90 days
- **ERROR**: 180 days
- **CRITICAL**: 365 days

### Common Log Queries

#### Find failed trades
```json
{
  "level": "ERROR",
  "logger": "src.trading.executor",
  "message": "*trade failed*"
}
```

#### Find slow API calls
```json
{
  "level": "WARNING",
  "logger": "src.services.exchange.*",
  "extra.duration_ms": ">1000"
}
```

#### Find authentication failures
```json
{
  "level": "ERROR",
  "message": "*authentication*"
}
```

#### Track specific request
```json
{
  "request_id": "req-123456"
}
```

## SLA and SLO Definitions

### Service Level Agreements (SLAs)

#### Availability SLA
- **Target**: 99.5% uptime (monthly)
- **Measurement**: Percentage of time service is responding to health checks
- **Downtime Budget**: 3.6 hours per month

#### Response Time SLA
- **Target**: P95 < 500ms for API requests
- **Measurement**: 95th percentile response time
- **Breach Threshold**: P95 > 500ms for >5 minutes

#### Error Rate SLA
- **Target**: <1% error rate
- **Measurement**: Errors per total requests
- **Breach Threshold**: >1% for >5 minutes

### Service Level Objectives (SLOs)

#### Trading Execution SLO
- **Target**: 98% successful trade execution
- **Measurement**: Successful trades / total trade attempts
- **Alert Threshold**: <95% success rate

#### Data Freshness SLO
- **Target**: Market data <5 seconds old
- **Measurement**: Time since last market data update
- **Alert Threshold**: >10 seconds

#### Database Query SLO
- **Target**: P99 < 100ms for SELECT queries
- **Measurement**: 99th percentile query duration
- **Alert Threshold**: P99 > 200ms

## Alert Channel Configuration

### Alertmanager Configuration

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

  # PagerDuty configuration
  pagerduty_url: 'https://events.pagerduty.com/v2/enqueue'

  # SMTP configuration for email
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@tradingbot.com'
  smtp_auth_username: 'alerts@tradingbot.com'
  smtp_auth_password: '${SMTP_PASSWORD}'
  smtp_require_tls: true

# Alert routing based on severity
route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'default'

  routes:
    # Critical alerts - PagerDuty + Discord + SMS
    - match:
        severity: critical
      receiver: 'critical-multi-channel'
      continue: false

    # High priority alerts - Discord + Email
    - match:
        severity: high
      receiver: 'high-priority'
      continue: false

    # Medium/Warning alerts - Discord + Email
    - match_re:
        severity: medium|warning
      receiver: 'warning-alerts'
      continue: false

receivers:
  # Default receiver (should not be used if routing is correct)
  - name: 'default'
    discord_configs:
      - webhook_url: '${DISCORD_WEBHOOK_URL}'
        title: 'Unrouted Alert'

  # Critical alerts: PagerDuty + Discord + SMS
  - name: 'critical-multi-channel'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_SERVICE_KEY}'
        description: '{{ .CommonAnnotations.summary }}'
        details:
          firing: '{{ .Alerts.Firing | len }}'
          resolved: '{{ .Alerts.Resolved | len }}'
          num_firing: '{{ .Alerts.Firing | len }}'
          num_resolved: '{{ .Alerts.Resolved | len }}'
        severity: 'critical'

    discord_configs:
      - webhook_url: '${DISCORD_WEBHOOK_CRITICAL}'
        title: '🚨 CRITICAL ALERT'
        message: |
          **{{ .CommonAnnotations.summary }}**
          {{ .CommonAnnotations.description }}

          Runbook: {{ .CommonAnnotations.runbook_url }}

    webhook_configs:
      - url: '${SMS_WEBHOOK_URL}'
        send_resolved: true
        http_config:
          basic_auth:
            username: '${SMS_USERNAME}'
            password: '${SMS_PASSWORD}'

  # High priority alerts: Discord + Email
  - name: 'high-priority'
    discord_configs:
      - webhook_url: '${DISCORD_WEBHOOK_HIGH}'
        title: '⚠️ HIGH PRIORITY ALERT'
        message: |
          **{{ .CommonAnnotations.summary }}**
          {{ .CommonAnnotations.description }}

          Runbook: {{ .CommonAnnotations.runbook_url }}

    email_configs:
      - to: 'oncall@tradingbot.com'
        headers:
          Subject: '[HIGH] {{ .CommonAnnotations.summary }}'
        html: |
          <h2>{{ .CommonAnnotations.summary }}</h2>
          <p>{{ .CommonAnnotations.description }}</p>
          <p><strong>Runbook:</strong> <a href="{{ .CommonAnnotations.runbook_url }}">{{ .CommonAnnotations.runbook_url }}</a></p>

  # Warning/Medium alerts: Discord + Email
  - name: 'warning-alerts'
    discord_configs:
      - webhook_url: '${DISCORD_WEBHOOK_WARNING}'
        title: '⚡ Warning Alert'
        message: |
          **{{ .CommonAnnotations.summary }}**
          {{ .CommonAnnotations.description }}

    email_configs:
      - to: 'team@tradingbot.com'
        headers:
          Subject: '[WARNING] {{ .CommonAnnotations.summary }}'

inhibit_rules:
  # Inhibit warning alerts if critical alert is firing
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'high'
    equal: ['alertname']

  - source_match:
      severity: 'critical'
    target_match:
      severity: 'medium'
    equal: ['alertname']
```

### Channel Setup Instructions

#### PagerDuty Integration
1. Create a new service in PagerDuty dashboard
2. Generate integration key for Prometheus
3. Set `PAGERDUTY_SERVICE_KEY` environment variable
4. Configure escalation policies and on-call schedules
5. Test with manual alert trigger

#### Discord Webhook Setup
1. Create separate Discord channels for different severity levels:
   - `#alerts-critical` - Critical alerts (P0)
   - `#alerts-high` - High priority alerts (P1)
   - `#alerts-warning` - Warning/Medium alerts (P2/P3)

2. Generate webhooks for each channel:
   - Server Settings → Integrations → Webhooks → New Webhook
   - Copy webhook URL for each channel

3. Set environment variables:
   ```bash
   export DISCORD_WEBHOOK_CRITICAL="https://discord.com/api/webhooks/..."
   export DISCORD_WEBHOOK_HIGH="https://discord.com/api/webhooks/..."
   export DISCORD_WEBHOOK_WARNING="https://discord.com/api/webhooks/..."
   ```

#### SMS Configuration
1. Use Twilio or similar SMS gateway service
2. Create webhook endpoint for SMS delivery:
   ```python
   # Example SMS webhook endpoint
   @app.post("/alert/sms")
   async def send_sms_alert(alert: AlertPayload):
       client = TwilioClient(account_sid, auth_token)
       message = client.messages.create(
           body=f"CRITICAL: {alert.summary}",
           from_='+1234567890',
           to=['+1987654321', '+1555555555']  # On-call phone numbers
       )
       return {"status": "sent", "message_sid": message.sid}
   ```

3. Set `SMS_WEBHOOK_URL`, `SMS_USERNAME`, `SMS_PASSWORD` environment variables

#### Email Configuration
1. Configure SMTP settings in Alertmanager (Gmail example shown above)
2. Create application-specific password for Gmail account
3. Set `SMTP_PASSWORD` environment variable
4. Configure email distribution lists:
   - `oncall@tradingbot.com` - High priority alerts
   - `team@tradingbot.com` - Warning alerts
   - `ops@tradingbot.com` - Operational notifications

### Alert Routing Summary

| Severity | Channels | Response Time | Escalation |
|----------|----------|---------------|------------|
| Critical (P0) | PagerDuty + Discord + SMS | Immediate | Auto-page after 5 min |
| High (P1) | Discord + Email | < 15 minutes | Manual escalation |
| Medium (P2) | Discord + Email | < 1 hour | Next business day |
| Warning (P3) | Grafana Dashboard | Best effort | Weekly review |

## Alert Response Manual

### Critical Alert Response Procedures

#### TradingHalt
**Symptoms**: No trading signals or trades for 60+ seconds

**Immediate Actions**:
1. Check trading bot service status: `curl http://localhost:8000/health`
2. Review recent logs: `docker-compose logs -f tradingbot --tail=100`
3. Verify exchange connectivity: `python3 scripts/test_exchanges.py`
4. Check market data feed status

**Root Cause Investigation**:
- Strategy execution errors
- Exchange API connectivity issues
- Market data feed interruption
- Risk management circuit breaker triggered

**Remediation**:
```bash
# If service is down
docker-compose restart tradingbot

# If exchange connectivity issue
# Verify API keys and IP whitelist
python3 scripts/verify_api_keys.py

# If market data feed issue
# Check WebSocket connections
curl http://localhost:8000/api/exchange-status
```

**Escalation**: If not resolved in 5 minutes, escalate to DevOps Lead

#### HighAPIErrorRatePercent / WarningAPIErrorRate
**Symptoms**: API error rate >10% (Critical) or >5% (Warning)

**Immediate Actions**:
1. Identify error sources: Check Prometheus metrics `http_errors_total` by endpoint
2. Review error logs: `docker-compose logs tradingbot | grep ERROR`
3. Check external service status (exchange APIs)

**Common Causes**:
- Exchange API rate limiting
- Invalid API parameters
- Authentication failures
- Network connectivity issues

**Remediation**:
```bash
# Check rate limit status
curl http://localhost:8000/api/exchange-status

# Reduce trading frequency temporarily
# Update MAX_ORDERS_PER_MINUTE in .env

# Rotate API keys if authentication issues
python3 scripts/rotate_api_keys.py
```

**Threshold Tuning**: If false positives occur during normal trading volatility, consider:
- Increasing threshold to 7% for Warning, 12% for Critical
- Extending `for` duration from 5m to 10m
- Adding time-of-day filters to account for market hours

**Escalation**: If error rate persists for 15+ minutes, escalate to Engineering Lead

#### CriticalMemoryUsage / WarningMemoryUsage
**Symptoms**: Memory usage >90% (Critical) or >80% (Warning)

**Immediate Actions**:
1. Check memory usage: `docker stats tradingbot`
2. Identify memory-consuming processes
3. Review for memory leaks

**Remediation**:
```bash
# Restart service to free memory
docker-compose restart tradingbot

# Check for memory leaks
python3 -m memory_profiler scripts/diagnose_memory.py

# Reduce cache sizes if needed
# Update REDIS_MAX_MEMORY in .env
```

**Threshold Tuning**: Adjust based on actual memory requirements:
- If service normally runs at 70-75%, increase Warning to 85%, Critical to 95%
- If memory usage is cyclical (e.g., daily patterns), add time-based inhibition rules

**Escalation**: If memory continues growing after restart, escalate immediately

#### PositionRiskHigh
**Symptoms**: Total position size >90% of configured limit

**Immediate Actions**:
1. Review current positions: `curl http://localhost:8000/api/positions`
2. Check if positions are concentrated in single symbol
3. Verify position limits are correctly configured

**Remediation**:
```bash
# Reduce position sizes
python3 scripts/reduce_positions.py --target=70

# Temporarily halt new positions
# Set ENABLE_NEW_POSITIONS=false in .env
docker-compose restart tradingbot

# Review risk parameters
grep -E "MAX_POSITION_SIZE|RISK_PER_TRADE" .env
```

**Threshold Tuning**:
- Conservative: 85% Warning, 95% Critical
- Aggressive: 92% Warning, 98% Critical
- Consider market volatility when setting thresholds

**Escalation**: Alert trading desk immediately if >95%

### False Positive Handling

#### Identifying False Positives
1. Review alert history in Grafana
2. Correlate with deployment times, market events
3. Check if alert resolves quickly without intervention
4. Analyze alert frequency and duration

#### Common False Positive Scenarios

**Trading Halt During Market Close**:
- **Problem**: Alert fires during scheduled market closures
- **Solution**: Add time-based inhibition rules:
```yaml
# Inhibit TradingHalt outside trading hours
inhibit_rules:
  - source_match:
      alertname: 'MarketClosed'
    target_match:
      alertname: 'TradingHalt'
```

**High Error Rate During Deployments**:
- **Problem**: Temporary error spike during rolling updates
- **Solution**: Increase `for` duration from 5m to 10m, add deployment annotations

**Memory Spikes During Data Processing**:
- **Problem**: Scheduled analytics jobs cause temporary memory increase
- **Solution**: Increase threshold or add time-based inhibition

#### Threshold Adjustment Process
1. Collect baseline metrics for 7 days
2. Calculate P95 and P99 values for each metric
3. Set thresholds at:
   - Warning: P95 + 10%
   - Critical: P99 + 10%
4. Monitor for 2 weeks and adjust based on false positive rate
5. Document threshold changes in runbook

**Target Metrics**:
- False positive rate: <5%
- Alert response time: <15 minutes for Critical
- Alert accuracy: >95%

### Escalation Criteria

**Level 1 → Level 2** (On-call → DevOps Lead):
- Cannot resolve Critical alert within 5 minutes
- High priority alert persists >30 minutes
- Multiple related alerts firing simultaneously
- Uncertainty about root cause or remediation

**Level 2 → Level 3** (DevOps Lead → Engineering Manager):
- Issue requires code changes
- Impacts multiple systems/services
- Data loss or corruption risk
- Potential security incident

**Level 3 → Level 4** (Engineering Manager → Executive):
- Regulatory reporting required
- Legal/compliance implications
- Major financial impact (>$10K)
- Public communication needed

### Runbook Maintenance
1. Update runbooks after each incident (post-mortem process)
2. Test remediation procedures quarterly
3. Review and update thresholds monthly
4. Archive outdated runbooks annually

## Monitoring Best Practices

1. **Alert Fatigue Prevention**
   - Use appropriate thresholds
   - Implement `for` duration to avoid flapping
   - Group related alerts
   - Use severity levels correctly

2. **Metric Naming Conventions**
   - Use snake_case: `trading_trades_total`
   - Include units: `_seconds`, `_bytes`, `_total`
   - Use labels for dimensions: `{exchange="binance"}`

3. **Dashboard Design**
   - Most critical metrics at top
   - Use appropriate visualization types
   - Include time range selectors
   - Add annotations for deployments

4. **Log Management**
   - Use structured logging (JSON)
   - Include context (request_id, correlation_id)
   - Avoid logging sensitive data
   - Implement log rotation

5. **Regular Review**
   - Review alerts monthly
   - Adjust thresholds based on reality
   - Remove obsolete alerts
   - Update runbooks

## Additional Resources

- Incident Response: `INCIDENT_RESPONSE.md`
- Performance Tuning: `PERFORMANCE_TUNING.md`
- Deployment Guide: `DEPLOYMENT.md`

# Grafana Dashboard Setup Guide

## Overview

This document provides comprehensive instructions for setting up and using Grafana dashboards for the Trading Bot monitoring system.

## Architecture

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│             │      │             │      │             │
│  TradingBot │─────▶│ Prometheus  │─────▶│   Grafana   │
│   :8000     │      │   :9090     │      │    :3000    │
│             │      │             │      │             │
└─────────────┘      └─────────────┘      └─────────────┘
     Metrics              Scraping           Visualization
```

## Components

### 1. Prometheus Data Source
- **URL**: `http://prometheus:9090`
- **Scrape Interval**: 10 seconds (for trading metrics)
- **Retention**: 30 days

### 2. Dashboards

#### Trading Performance Dashboard
**Purpose**: Real-time monitoring of trading signals, execution, and P&L

**Panels**:
- **Signals Generated (5min)**: Total signals generated in 5-minute window
- **Risk Violations (5min)**: Risk management violations count
- **Position P&L by Symbol**: Current profit/loss per trading pair
- **Trading Signals Rate**: Signal generation rate by strategy
- **Order Execution Latency**: p50 and p95 execution times
- **Signals by Strategy**: Distribution pie chart
- **Risk Violations Summary**: Table of violations by type
- **Strategy Execution Time**: p95 strategy execution latency

**Key Metrics**:
```promql
# Signal generation rate
rate(trading_signals_generated_total[5m])

# Order execution latency percentiles
histogram_quantile(0.95, sum by (le, symbol) (rate(order_execution_latency_seconds_bucket[5m])))

# Current position P&L
sum by (symbol) (position_pnl_usdt)

# Risk violations
sum(rate(risk_violations_total[5m]))
```

#### System Monitoring Dashboard
**Purpose**: System health, API performance, and error tracking

**Panels**:
- **Active WebSocket Connections**: Live WebSocket connection count
- **API Errors (5min)**: Error count in 5-minute window
- **CPU Usage**: Process CPU utilization
- **Memory Usage**: Process memory percentage
- **WebSocket Connections by Type**: Breakdown by exchange/stream type
- **API Error Rate**: Errors per second by endpoint
- **API Errors by Type**: Table of error types
- **Process Memory Usage**: RSS and virtual memory trend

**Key Metrics**:
```promql
# WebSocket connections
sum(websocket_connections_active)

# API error rate
rate(api_errors_total[5m])

# Memory usage
process_resident_memory_bytes / machine_memory_bytes

# CPU usage (approximate)
rate(process_cpu_seconds_total[5m])
```

### 3. Alert Rules

#### Alert Definitions

| Alert | Condition | Severity | Duration |
|-------|-----------|----------|----------|
| No Trading Signals | No signals for 10min | Warning | 10min |
| High Risk Violations | >0.1 violations/sec | Critical | 2min |
| High Order Latency | p95 > 5 seconds | Warning | 5min |
| High API Errors | >0.5 errors/sec | Critical | 3min |
| WebSocket Disconnected | 0 active connections | Critical | 1min |
| High Memory Usage | >90% memory | Warning | 5min |

## Setup Instructions

### 1. Initial Setup

The Grafana service is automatically configured through Docker Compose provisioning:

```bash
# Start the entire stack
docker-compose up -d

# Verify Grafana is running
docker-compose ps grafana

# Check logs
docker-compose logs -f grafana
```

### 2. Access Grafana

1. Open browser: `http://localhost:3000`
2. Default credentials:
   - **Username**: `admin`
   - **Password**: `admin`
3. You'll be prompted to change the password on first login

### 3. Verify Data Source

The Prometheus data source is automatically provisioned. To verify:

1. Navigate to **Configuration** → **Data Sources**
2. Click on **Prometheus**
3. Scroll down and click **Test**
4. You should see "Data source is working"

### 4. Access Dashboards

Dashboards are auto-provisioned and available immediately:

1. Click **Dashboards** in the left sidebar
2. You'll see:
   - **Trading Performance Dashboard**
   - **System Monitoring Dashboard**

## Usage Guide

### Viewing Real-Time Data

1. **Time Range Selection**:
   - Top right corner dropdown
   - Trading Performance: Last 1 hour (default)
   - System Monitoring: Last 30 minutes (default)

2. **Auto-Refresh**:
   - Trading Performance: 5 seconds
   - System Monitoring: 10 seconds
   - Change via refresh interval dropdown (top right)

3. **Panel Interactions**:
   - Click and drag to zoom into time range
   - Double-click to reset zoom
   - Hover for tooltip details
   - Click legend items to show/hide series

### Interpreting Metrics

#### Trading Performance

**Healthy System Indicators**:
- ✅ Steady signal generation rate (not zero)
- ✅ Risk violations close to zero
- ✅ Order execution latency < 2 seconds (p95)
- ✅ Positive or controlled P&L trends

**Warning Signs**:
- ⚠️ No signals for >5 minutes (possible strategy issue)
- ⚠️ Sudden spike in risk violations
- ⚠️ Order latency > 5 seconds consistently
- ⚠️ Sharp P&L drops

#### System Health

**Healthy System Indicators**:
- ✅ All expected WebSocket connections active
- ✅ API error rate < 0.1/sec
- ✅ CPU < 70%, Memory < 80%
- ✅ Stable connection counts

**Warning Signs**:
- ⚠️ WebSocket disconnections
- ⚠️ High API error rates
- ⚠️ Memory usage > 90%
- ⚠️ Sustained high CPU usage

### Alert Management

#### Viewing Active Alerts

1. Click **Alerting** → **Alert Rules**
2. View firing alerts in **Alerts** tab
3. Filter by severity: `severity=critical` or `severity=warning`

#### Configuring Notifications

**Slack Integration** (Example):
```yaml
# Add to config/grafana/provisioning/alerting/contact-points.yml
apiVersion: 1
contactPoints:
  - orgId: 1
    name: Slack Alerts
    receivers:
      - uid: slack-alerts
        type: slack
        settings:
          url: https://hooks.slack.com/services/YOUR/WEBHOOK/URL
          text: |
            {{ range .Alerts }}
            *Alert:* {{ .Labels.alertname }}
            *Severity:* {{ .Labels.severity }}
            *Description:* {{ .Annotations.description }}
            {{ end }}
```

**Email Integration**:
```yaml
contactPoints:
  - orgId: 1
    name: Email Alerts
    receivers:
      - uid: email-alerts
        type: email
        settings:
          addresses: your-email@example.com
          singleEmail: true
```

### Dashboard Customization

#### Adding New Panels

1. Open dashboard → Click **Add** → **Visualization**
2. Select **Prometheus** as data source
3. Enter PromQL query
4. Configure visualization type and options
5. Click **Apply**

#### Example: Add Custom Panel
```promql
# Example: Average P&L per hour
avg_over_time(position_pnl_usdt[1h])

# Example: Total signals by direction
sum by (direction) (trading_signals_generated_total)

# Example: Error rate by exchange
sum by (exchange) (rate(api_errors_total[5m]))
```

#### Saving Dashboards

Dashboards are provisioned from JSON files and will reset on restart. To make permanent changes:

1. Edit the JSON file in `config/grafana/dashboards/`
2. Restart Grafana: `docker-compose restart grafana`

Or export from UI:
1. Click **Share dashboard** → **Export** → **Save to file**
2. Replace the corresponding JSON file in `config/grafana/dashboards/`

## Advanced Configuration

### User Management

#### Creating Read-Only Users

1. **Configuration** → **Users** → **Invite**
2. Set role to **Viewer**
3. Users can view but not edit dashboards

#### Creating Admin Users

1. Same process, set role to **Admin**
2. Admin users can modify dashboards and alerts

### Dashboard Variables

Add dynamic filtering with variables:

```json
"templating": {
  "list": [
    {
      "name": "symbol",
      "type": "query",
      "datasource": "Prometheus",
      "query": "label_values(trading_signals_generated_total, symbol)"
    }
  ]
}
```

Use in queries: `trading_signals_generated_total{symbol="$symbol"}`

### Custom Alert Rules

Add new alerts in `config/grafana/provisioning/alerting/alerts.yml`:

```yaml
- uid: custom_alert
  title: Custom Alert Name
  condition: A
  data:
    - refId: A
      relativeTimeRange:
        from: 300
        to: 0
      datasourceUid: prometheus
      model:
        expr: your_promql_query > threshold
        refId: A
  for: 5m
  annotations:
    description: "Alert description"
  labels:
    severity: warning
```

## Troubleshooting

### Dashboard Not Loading

**Symptom**: Dashboard shows "No data" or fails to load

**Solutions**:
1. Check Prometheus is running: `docker-compose ps prometheus`
2. Verify metrics endpoint: `curl http://localhost:8000/metrics`
3. Test Prometheus query: `http://localhost:9090/graph`
4. Check Grafana logs: `docker-compose logs grafana`

### Data Source Connection Failed

**Symptom**: "Data source is not working"

**Solutions**:
1. Verify Prometheus URL in data source config
2. Check network connectivity: `docker exec tradingbot-grafana ping prometheus`
3. Restart services: `docker-compose restart prometheus grafana`

### Missing Metrics

**Symptom**: Some panels show "No data"

**Solutions**:
1. Verify metric names in Prometheus: `http://localhost:9090/api/v1/label/__name__/values`
2. Check if metrics are being collected: Query in Prometheus UI
3. Verify scrape config in `config/prometheus.yml`
4. Check TradingBot is exposing metrics: `curl http://localhost:8000/metrics`

### Alerts Not Firing

**Symptom**: Expected alerts are not triggered

**Solutions**:
1. Test alert query in Prometheus UI
2. Check alert rule syntax in provisioning files
3. Verify alert manager is configured
4. Check notification channels are set up correctly

## Performance Optimization

### Reducing Query Load

1. **Increase scrape intervals** for less critical metrics
2. **Use recording rules** for complex queries:

```yaml
# In prometheus.yml
rule_files:
  - 'recording_rules.yml'

# In recording_rules.yml
groups:
  - name: trading_aggregates
    interval: 30s
    rules:
      - record: job:trading_signals:rate5m
        expr: sum(rate(trading_signals_generated_total[5m]))
```

3. **Adjust dashboard refresh** rates based on need

### Storage Optimization

1. Adjust Prometheus retention: `--storage.tsdb.retention.time=15d`
2. Use remote write for long-term storage
3. Enable Grafana dashboard caching

## Security Best Practices

### 1. Change Default Credentials

```yaml
# In docker-compose.yml
environment:
  - GF_SECURITY_ADMIN_USER=your_admin_user
  - GF_SECURITY_ADMIN_PASSWORD=your_secure_password
```

### 2. Enable HTTPS

Use reverse proxy (nginx/traefik) with SSL certificates:

```yaml
environment:
  - GF_SERVER_ROOT_URL=https://your-domain.com
  - GF_SERVER_PROTOCOL=https
```

### 3. IP Whitelisting

Restrict access to monitoring stack:

```yaml
# In docker-compose.yml under grafana
networks:
  tradingbot-network:
    ipv4_address: 172.20.0.5

# Add firewall rules or nginx access control
```

### 4. Anonymous Access

Disable anonymous access:

```yaml
environment:
  - GF_AUTH_ANONYMOUS_ENABLED=false
```

## Backup and Recovery

### Backing Up Dashboards

```bash
# Backup dashboard JSON files
cp -r config/grafana/dashboards /backup/grafana-dashboards-$(date +%Y%m%d)

# Backup provisioning config
cp -r config/grafana/provisioning /backup/grafana-provisioning-$(date +%Y%m%d)
```

### Backing Up Grafana Data

```bash
# Backup Grafana database
docker-compose exec grafana grafana-cli admin export-dashboard > backup.json

# Or backup entire volume
docker run --rm -v tradingbot_grafana_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/grafana-data-backup.tar.gz /data
```

### Restoring from Backup

```bash
# Restore dashboard files
cp -r /backup/grafana-dashboards-20241110/* config/grafana/dashboards/

# Restart Grafana
docker-compose restart grafana
```

## Reference

### Useful Links
- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana Alerting](https://grafana.com/docs/grafana/latest/alerting/)

### Metric Naming Convention
- `trading_*`: Trading-specific metrics
- `order_*`: Order execution metrics
- `risk_*`: Risk management metrics
- `position_*`: Position tracking metrics
- `api_*`: API interaction metrics
- `websocket_*`: WebSocket connection metrics

### Common PromQL Queries

```promql
# Rate of signals (per second)
rate(trading_signals_generated_total[5m])

# Sum across dimensions
sum by (symbol) (position_pnl_usdt)

# Aggregation functions
avg_over_time(metric[5m])
max_over_time(metric[1h])
min_over_time(metric[1h])

# Percentiles from histogram
histogram_quantile(0.95, rate(metric_bucket[5m]))

# Filtering
metric{label="value"}
metric{label=~"regex"}
```

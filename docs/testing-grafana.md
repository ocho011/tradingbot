# Grafana Dashboard Testing Guide

## Pre-Test Checklist

Before testing Grafana dashboards, ensure:

- [ ] Docker and Docker Compose are installed
- [ ] All services are running: `docker-compose ps`
- [ ] Prometheus is collecting metrics: `http://localhost:9090/targets`
- [ ] TradingBot is exposing metrics: `curl http://localhost:8000/metrics`

## Test Plan

### 1. Data Source Configuration Test

**Objective**: Verify Prometheus data source is correctly configured

**Steps**:
```bash
# 1. Start all services
docker-compose up -d

# 2. Wait for Grafana to be healthy
docker-compose ps grafana
# Should show "healthy"

# 3. Access Grafana
open http://localhost:3000
# Login: admin/admin

# 4. Navigate to Data Sources
# Configuration → Data Sources → Prometheus

# 5. Click "Test" button
# Expected: "Data source is working" message
```

**Expected Results**:
- ✅ Data source shows "Connected" status
- ✅ Test button returns success message
- ✅ Query timeout configured (60s)

**Troubleshooting**:
```bash
# If test fails, check Prometheus connectivity
docker exec tradingbot-grafana wget -O- http://prometheus:9090/-/healthy

# Check Prometheus is scraping tradingbot
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.service=="tradingbot")'
```

---

### 2. Dashboard Rendering Test

**Objective**: Verify all dashboard panels render correctly

#### Trading Performance Dashboard

**Steps**:
1. Navigate to **Dashboards** → **Trading Performance Dashboard**
2. Verify all 8 panels render without errors:
   - Signals Generated (5min) - Stat panel
   - Risk Violations (5min) - Stat panel
   - Position P&L by Symbol - Time series
   - Trading Signals Rate - Time series
   - Order Execution Latency - Time series
   - Signals by Strategy - Pie chart
   - Risk Violations Summary - Table
   - Strategy Execution Time - Time series

**Expected Results**:
- ✅ All panels load without "No data" errors
- ✅ Time series show data for last 1 hour
- ✅ Stat panels show current values
- ✅ Pie chart displays distribution
- ✅ Table shows at least header row

**Test Queries**:
```bash
# Generate test metrics (if no real trading data)
curl -X POST http://localhost:8000/test/generate-metrics

# Verify metrics exist
curl http://localhost:8000/metrics | grep trading_signals_generated_total
```

#### System Monitoring Dashboard

**Steps**:
1. Navigate to **Dashboards** → **System Monitoring Dashboard**
2. Verify all 8 panels render:
   - Active WebSocket Connections - Stat
   - API Errors (5min) - Stat
   - CPU Usage - Stat
   - Memory Usage - Stat
   - WebSocket Connections by Type - Time series
   - API Error Rate - Time series
   - API Errors by Type - Table
   - Process Memory Usage - Time series

**Expected Results**:
- ✅ All panels display data
- ✅ System metrics show realistic values
- ✅ Error counts are visible (even if zero)

---

### 3. Real-Time Data Update Test

**Objective**: Verify dashboards update automatically with new data

**Steps**:
1. Open **Trading Performance Dashboard**
2. Note the "Last updated" timestamp (top right)
3. Observe panel for 5-10 seconds (auto-refresh is 5s)
4. Verify timestamp updates automatically

**Expected Results**:
- ✅ Timestamp updates every 5 seconds
- ✅ Time series graphs extend to the right
- ✅ Stat panels reflect latest values
- ✅ No "stale" data warnings

**Manual Refresh Test**:
1. Click refresh button (circular arrow, top right)
2. All panels should reload immediately

---

### 4. Time Range Selection Test

**Objective**: Verify time range picker works correctly

**Steps**:
1. Click time range dropdown (top right)
2. Test various ranges:
   - Last 5 minutes
   - Last 15 minutes
   - Last 1 hour
   - Last 6 hours
   - Custom range: Select specific start/end times

**Expected Results**:
- ✅ Panels update to show selected time range
- ✅ X-axis labels adjust appropriately
- ✅ Data density matches time range (more data = denser plot)

**Zoom Test**:
1. Click and drag on any time series panel to select a time range
2. Panel should zoom into selected range
3. Double-click to reset zoom

---

### 5. Metric Accuracy Test

**Objective**: Verify displayed metrics match Prometheus raw data

**Test 1: Signal Count**
```bash
# Get signal count from Prometheus
curl -s "http://localhost:9090/api/v1/query?query=sum(trading_signals_generated_total)" | jq '.data.result[0].value[1]'

# Compare with Grafana "Signals Generated (5min)" panel
# They should match (accounting for 5-minute rate calculation)
```

**Test 2: Order Latency**
```bash
# Get p95 latency from Prometheus
curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,%20sum(rate(order_execution_latency_seconds_bucket[5m]))%20by%20(le))" | jq '.data.result[0].value[1]'

# Compare with "Order Execution Latency" panel p95 line
```

**Expected Results**:
- ✅ Values match within rounding (±2%)
- ✅ Trends are consistent
- ✅ No data gaps or anomalies

---

### 6. Alert Rule Test

**Objective**: Verify alert rules fire correctly

#### Test 1: No Signals Alert

**Simulate Condition**:
```bash
# Stop TradingBot to stop signal generation
docker-compose stop tradingbot

# Wait 10 minutes (alert threshold)
# Check alert status after 10+ minutes
```

**Verify Alert**:
1. Navigate to **Alerting** → **Alert Rules**
2. Find "No Trading Signals Generated" rule
3. Status should change to "Firing" after 10 minutes

**Expected Results**:
- ✅ Alert transitions from "Normal" to "Pending" to "Firing"
- ✅ Alert shows in "Alerts" tab
- ✅ Annotation appears on dashboard timeline

**Cleanup**:
```bash
# Restart TradingBot
docker-compose start tradingbot

# Alert should resolve after signals resume
```

#### Test 2: High API Errors Alert

**Simulate Condition**:
```bash
# Generate API errors (if test endpoint exists)
for i in {1..100}; do
  curl -X POST http://localhost:8000/test/trigger-error
  sleep 0.1
done
```

**Verify Alert**:
1. Check "High API Error Rate" alert
2. Should fire if error rate > 0.5/sec for 3 minutes

#### Test 3: WebSocket Disconnection Alert

**Simulate Condition**:
```bash
# If WebSocket manager is running, simulate disconnect
curl -X POST http://localhost:8000/test/disconnect-websocket
```

**Verify Alert**:
- Should fire after 1 minute of disconnection

---

### 7. Panel Interaction Test

**Objective**: Verify interactive features work

**Legend Interaction**:
1. Open "Trading Signals Rate" panel
2. Click on a legend item (strategy name)
3. That series should hide/show

**Expected Results**:
- ✅ Clicking legend toggles series visibility
- ✅ Y-axis rescales appropriately
- ✅ Colors remain consistent

**Tooltip Test**:
1. Hover over time series panel
2. Tooltip should show:
   - Timestamp
   - All series values at that point
   - Series names with colors

**Panel Menu Test**:
1. Click panel title → "Edit"
2. Panel editor should open
3. Test "View" without saving
4. Close without changes

---

### 8. Performance Test

**Objective**: Verify dashboard performs well under load

**Metrics to Monitor**:
```bash
# Check Grafana resource usage
docker stats tradingbot-grafana

# Monitor query execution time
# In Grafana: Panel → Query inspector → Stats
```

**Load Test**:
1. Open both dashboards in separate tabs
2. Set auto-refresh to 5s on both
3. Monitor for 15 minutes

**Expected Results**:
- ✅ Memory usage stable (< 400MB)
- ✅ CPU usage < 20%
- ✅ Query execution < 500ms
- ✅ No browser performance warnings

**Query Performance Test**:
```bash
# Test complex query performance
time curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95,%20sum(rate(order_execution_latency_seconds_bucket[5m]))%20by%20(le))"

# Should complete in < 100ms
```

---

### 9. Persistence Test

**Objective**: Verify configurations persist across restarts

**Steps**:
1. Note current dashboard state
2. Restart Grafana: `docker-compose restart grafana`
3. Wait for startup (check logs)
4. Re-access dashboards

**Expected Results**:
- ✅ Dashboards still exist
- ✅ Data source still configured
- ✅ Alert rules still active
- ✅ No configuration loss

**Volume Data Test**:
```bash
# Verify Grafana data persists
docker-compose down
docker-compose up -d

# Dashboards should still be available
```

---

### 10. Alert Notification Test

**Objective**: Verify alerts send notifications (if configured)

**Prerequisites**:
- Notification channel configured (Slack, email, etc.)

**Steps**:
1. Trigger an alert (use Test 1 from Alert Rule Test)
2. Wait for alert to fire
3. Check notification channel

**Expected Results**:
- ✅ Notification received within 1 minute of alert firing
- ✅ Notification contains:
  - Alert name
  - Severity level
  - Description
  - Link to dashboard
- ✅ Notification clears when alert resolves

---

## Automated Test Script

Create `test-grafana.sh`:

```bash
#!/bin/bash

echo "=== Grafana Dashboard Test Suite ==="

# Test 1: Services are running
echo "Test 1: Checking services..."
if docker-compose ps | grep -q "tradingbot-grafana.*Up.*healthy"; then
    echo "✅ Grafana is healthy"
else
    echo "❌ Grafana is not healthy"
    exit 1
fi

# Test 2: Grafana API is responding
echo "Test 2: Testing Grafana API..."
GRAFANA_STATUS=$(curl -s -u admin:admin http://localhost:3000/api/health | jq -r '.database')
if [ "$GRAFANA_STATUS" = "ok" ]; then
    echo "✅ Grafana API is responding"
else
    echo "❌ Grafana API is not responding"
    exit 1
fi

# Test 3: Prometheus data source exists
echo "Test 3: Checking Prometheus data source..."
DS_COUNT=$(curl -s -u admin:admin http://localhost:3000/api/datasources | jq '. | length')
if [ "$DS_COUNT" -ge 1 ]; then
    echo "✅ Data source configured ($DS_COUNT found)"
else
    echo "❌ No data sources found"
    exit 1
fi

# Test 4: Dashboards exist
echo "Test 4: Checking dashboards..."
DASHBOARD_COUNT=$(curl -s -u admin:admin http://localhost:3000/api/search?type=dash-db | jq '. | length')
if [ "$DASHBOARD_COUNT" -ge 2 ]; then
    echo "✅ Dashboards provisioned ($DASHBOARD_COUNT found)"
else
    echo "❌ Expected at least 2 dashboards, found $DASHBOARD_COUNT"
    exit 1
fi

# Test 5: Metrics are available
echo "Test 5: Checking metrics availability..."
METRIC_COUNT=$(curl -s http://localhost:9090/api/v1/label/__name__/values | jq '.data | length')
if [ "$METRIC_COUNT" -gt 0 ]; then
    echo "✅ Metrics available ($METRIC_COUNT metrics)"
else
    echo "❌ No metrics found"
    exit 1
fi

# Test 6: Trading metrics exist
echo "Test 6: Checking trading-specific metrics..."
if curl -s http://localhost:8000/metrics | grep -q "trading_signals_generated_total"; then
    echo "✅ Trading metrics are exposed"
else
    echo "❌ Trading metrics not found"
    exit 1
fi

echo ""
echo "=== All Tests Passed ==="
```

Run tests:
```bash
chmod +x test-grafana.sh
./test-grafana.sh
```

---

## Test Results Documentation

### Test Report Template

```markdown
# Grafana Dashboard Test Report

**Date**: YYYY-MM-DD
**Tester**: Name
**Environment**: Docker Compose / Kubernetes / Other

## Test Results Summary

| Test Category | Status | Notes |
|--------------|--------|-------|
| Data Source Config | ✅ Pass | |
| Dashboard Rendering | ✅ Pass | |
| Real-Time Updates | ✅ Pass | |
| Time Range Selection | ✅ Pass | |
| Metric Accuracy | ✅ Pass | |
| Alert Rules | ✅ Pass | |
| Panel Interactions | ✅ Pass | |
| Performance | ✅ Pass | |
| Persistence | ✅ Pass | |
| Notifications | ⚠️ Partial | Email not configured |

## Issues Found

1. **Issue**: Description
   - **Severity**: Low/Medium/High/Critical
   - **Reproduction**: Steps to reproduce
   - **Workaround**: Temporary solution if any

## Performance Metrics

- Dashboard load time: XXms
- Query execution avg: XXms
- Memory usage: XXX MB
- CPU usage: XX%

## Recommendations

1. List any improvements
2. Configuration changes
3. Performance optimizations
```

---

## Continuous Testing

### Monitoring Test Health

Add to cron for periodic testing:
```bash
# /etc/cron.d/test-grafana
0 */4 * * * /path/to/test-grafana.sh >> /var/log/grafana-test.log 2>&1
```

### Integration with CI/CD

Add to GitHub Actions or similar:
```yaml
- name: Test Grafana Dashboards
  run: |
    docker-compose up -d
    sleep 30
    ./test-grafana.sh
```

---

## Common Issues and Solutions

### "No data" on panels
- **Check**: Prometheus scraping targets
- **Fix**: Verify `config/prometheus.yml` includes tradingbot target

### Alert not firing
- **Check**: Alert rule PromQL syntax in Prometheus UI
- **Fix**: Test query in Prometheus, adjust thresholds

### Slow dashboard load
- **Check**: Query complexity and data retention
- **Fix**: Add recording rules, reduce time range

### Panels show wrong data
- **Check**: Metric label names match between code and query
- **Fix**: Update queries to use correct label names

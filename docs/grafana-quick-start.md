# Grafana Quick Start Guide

## 🚀 5-Minute Setup

### 1. Start Services
```bash
cd /path/to/tradingbot
docker-compose up -d
```

### 2. Access Grafana
Open browser: **http://localhost:3000**

**Default Login:**
- Username: `admin`
- Password: `admin`
- (Change password on first login)

### 3. View Dashboards
Navigate to **Dashboards** (left sidebar) and open:
- **Trading Performance Dashboard** - Real-time trading metrics
- **System Monitoring Dashboard** - System health and API status

### 4. Verify Data Flow
Check that panels show data:
- If "No data": Wait 1-2 minutes for metrics collection
- If still no data: See [Troubleshooting](#troubleshooting)

---

## 📊 Dashboard Overview

### Trading Performance Dashboard

**Key Panels:**
- **Signals Generated** - Trading signals in last 5 minutes
- **Position P&L** - Current profit/loss by symbol
- **Order Latency** - Execution time (p50 and p95)
- **Risk Violations** - Risk management alerts

**Refresh Rate:** 5 seconds
**Default Time Range:** Last 1 hour

### System Monitoring Dashboard

**Key Panels:**
- **WebSocket Connections** - Active connection count
- **API Errors** - Error rate and types
- **CPU & Memory** - System resource usage
- **Process Metrics** - Memory and connection trends

**Refresh Rate:** 10 seconds
**Default Time Range:** Last 30 minutes

---

## 🔔 Alert Rules

Alerts automatically configured for:

| Alert | Threshold | Action |
|-------|-----------|--------|
| No Trading Signals | 10 min no signals | Check strategy |
| High Risk Violations | >0.1 violations/sec | Review positions |
| High Order Latency | p95 > 5 seconds | Check exchange API |
| API Errors | >0.5 errors/sec | Investigate logs |
| WebSocket Down | 0 connections | Restart service |
| High Memory | >90% usage | Check for leaks |

View alerts: **Alerting** → **Alert Rules**

---

## 🔧 Common Tasks

### Change Time Range
Click time picker (top right) → Select range

### Auto-Refresh
Click refresh dropdown (top right) → Select interval

### Zoom In on Time Series
Click and drag on panel → Double-click to reset

### Export Dashboard
Click **Share** (top right) → **Export** → **Save to file**

### Add Panel to Dashboard
Click **Add** (top right) → **Visualization** → Configure → **Apply**

---

## 🐛 Troubleshooting

### Problem: "No data" on dashboards

**Solutions:**
```bash
# 1. Check all services are running
docker-compose ps

# 2. Verify Prometheus is scraping metrics
curl http://localhost:9090/targets

# 3. Check TradingBot metrics endpoint
curl http://localhost:8000/metrics | grep trading_

# 4. Restart services if needed
docker-compose restart prometheus grafana
```

### Problem: Dashboard shows old data

**Solutions:**
- Click refresh button (circular arrow, top right)
- Check auto-refresh is enabled
- Verify time range includes current time

### Problem: Can't login to Grafana

**Solutions:**
```bash
# Reset admin password
docker-compose exec grafana grafana-cli admin reset-admin-password newpassword
```

### Problem: Alert not firing

**Solutions:**
1. Test alert query in Prometheus: http://localhost:9090/graph
2. Check alert rule syntax in `config/grafana/provisioning/alerting/alerts.yml`
3. Verify data exists for alert condition

---

## 📚 Useful Links

- **Full Documentation:** [docs/grafana-setup.md](./grafana-setup.md)
- **Testing Guide:** [docs/testing-grafana.md](./testing-grafana.md)
- **Prometheus UI:** http://localhost:9090
- **Grafana Docs:** https://grafana.com/docs/

---

## 🎯 Key Metrics Reference

### Trading Metrics
```promql
# Signal generation rate
rate(trading_signals_generated_total[5m])

# Current P&L
sum by (symbol) (position_pnl_usdt)

# Order latency (95th percentile)
histogram_quantile(0.95, rate(order_execution_latency_seconds_bucket[5m]))

# Risk violations
rate(risk_violations_total[5m])
```

### System Metrics
```promql
# Active WebSocket connections
sum(websocket_connections_active)

# API error rate
rate(api_errors_total[5m])

# Memory usage percentage
process_resident_memory_bytes / machine_memory_bytes

# Strategy execution time
histogram_quantile(0.95, rate(strategy_execution_seconds_bucket[5m]))
```

---

## 🔐 Security Notes

**Production Deployment:**
1. ✅ Change default admin password
2. ✅ Enable HTTPS (use reverse proxy)
3. ✅ Restrict IP access (firewall rules)
4. ✅ Disable anonymous access
5. ✅ Set up proper authentication (OAuth, LDAP, etc.)

**Configuration:**
```yaml
# In docker-compose.yml
environment:
  - GF_SECURITY_ADMIN_USER=your_username
  - GF_SECURITY_ADMIN_PASSWORD=your_secure_password
  - GF_USERS_ALLOW_SIGN_UP=false
  - GF_AUTH_ANONYMOUS_ENABLED=false
```

---

## 📞 Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section above
2. Review full documentation in `docs/grafana-setup.md`
3. Check Grafana logs: `docker-compose logs grafana`
4. Check TradingBot logs: `docker-compose logs tradingbot`

---

## ⚡ Performance Tips

1. **Reduce query load:** Increase scrape intervals for less critical metrics
2. **Optimize dashboards:** Use recording rules for complex queries
3. **Adjust retention:** Set appropriate Prometheus retention (default: 30 days)
4. **Browser performance:** Close unused dashboard tabs

---

## 📊 Dashboard Customization

### Add Custom Panel

1. Open dashboard → Click **Add** → **Visualization**
2. Select **Prometheus** data source
3. Enter PromQL query (e.g., `rate(your_metric[5m])`)
4. Choose visualization type (Time series, Stat, Table, etc.)
5. Configure display options
6. Click **Apply**

### Save Changes

**Method 1:** Edit JSON file
```bash
# Export from UI: Share → Export → Save to file
# Replace: config/grafana/dashboards/your-dashboard.json
# Restart: docker-compose restart grafana
```

**Method 2:** Dashboard JSON API
```bash
# Save current state
curl -X POST -H "Content-Type: application/json" \
  -u admin:admin \
  http://localhost:3000/api/dashboards/db \
  -d @config/grafana/dashboards/your-dashboard.json
```

---

## 🎓 Learning Resources

**PromQL Basics:**
- Functions: `rate()`, `sum()`, `avg()`, `histogram_quantile()`
- Operators: `+`, `-`, `*`, `/`, `==`, `!=`, `>`, `<`
- Aggregations: `by (label)`, `without (label)`

**Example Queries:**
```promql
# Average over time
avg_over_time(metric[5m])

# Sum by label
sum by (symbol) (metric)

# Rate per second
rate(metric[5m])

# Percentile from histogram
histogram_quantile(0.95, rate(metric_bucket[5m]))
```

**Grafana Panel Types:**
- **Time Series:** Trends over time
- **Stat:** Single value with threshold colors
- **Table:** Tabular data view
- **Pie Chart:** Distribution percentages
- **Gauge:** Current value with min/max
- **Bar Chart:** Comparison bars

---

Happy monitoring! 🎉

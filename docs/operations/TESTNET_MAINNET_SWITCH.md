# Testnet to Mainnet Switch Guide

## Table of Contents
1. [Overview](#overview)
2. [Pre-Switch Checklist](#pre-switch-checklist)
3. [Configuration Changes](#configuration-changes)
4. [API Key Setup](#api-key-setup)
5. [Database Migration](#database-migration)
6. [Switch Procedure](#switch-procedure)
7. [Post-Switch Validation](#post-switch-validation)
8. [Rollback Procedure](#rollback-procedure)

## Overview

### Critical Differences Between Testnet and Mainnet

| Aspect | Testnet | Mainnet |
|--------|---------|---------|
| **Funds** | Fake/Test funds | Real money |
| **API Endpoints** | testnet.binance.vision | api.binance.com |
| **Order Execution** | Simulated | Real trades |
| **Market Data** | May differ from real | Live market data |
| **Risk Level** | Zero financial risk | Real financial risk |
| **Rate Limits** | More lenient | Stricter enforcement |

### When to Switch

**Ready to Switch When**:
- ✅ All features tested thoroughly on testnet
- ✅ Trading strategies validated with historical data
- ✅ Risk management systems tested
- ✅ Monitoring and alerts configured
- ✅ Backup and recovery procedures tested
- ✅ Team trained on production operations
- ✅ Emergency procedures documented

**DO NOT Switch If**:
- ❌ Untested code changes
- ❌ Unresolved bugs in critical features
- ❌ Missing monitoring or alerts
- ❌ Incomplete risk management
- ❌ Unclear rollback procedure
- ❌ Insufficient testing of edge cases

## Pre-Switch Checklist

### 1. Code and Configuration Review

```bash
# Verify all tests pass
python3 -m pytest tests/ -v --tb=short

# Check for testnet-specific code
grep -r "testnet" src/ --exclude-dir=venv
grep -r "sandbox" src/ --exclude-dir=venv

# Verify environment configuration
cat .env | grep -E "TESTNET|SANDBOX"

# Review trading configuration
cat .env | grep -E "TRADING_MODE|MAX_POSITION|RISK_PER_TRADE"
```

### 2. Database Backup

```bash
# Create full backup before switch
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump -h localhost -U tradingbot tradingbot > backup_pre_mainnet_${TIMESTAMP}.sql

# Verify backup
ls -lh backup_pre_mainnet_${TIMESTAMP}.sql

# Upload to secure storage
aws s3 cp backup_pre_mainnet_${TIMESTAMP}.sql s3://tradingbot-backups/mainnet-switch/
```

### 3. API Key Verification

```bash
# Test Binance mainnet API keys
python3 scripts/verify_api_keys.py --exchange binance --mainnet

# Test Upbit API keys
python3 scripts/verify_api_keys.py --exchange upbit --mainnet

# Verify IP whitelist
curl ipinfo.io/ip
# Add this IP to exchange API key whitelist
```

### 4. Risk Management Configuration

```bash
# Review risk settings for mainnet
cat <<EOF > mainnet_risk_settings.env
# Conservative settings for mainnet launch
MAX_POSITION_SIZE=100          # Start small
RISK_PER_TRADE=0.005          # 0.5% per trade
MAX_DAILY_LOSS=-500           # Stop if daily loss exceeds $500
MAX_OPEN_POSITIONS=3           # Limit concurrent positions
ENABLE_AUTO_TRADING=false     # Manual approval initially
EOF
```

### 5. Monitoring Setup

```bash
# Verify Prometheus is collecting metrics
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health == "up")'

# Verify Grafana dashboards accessible
curl http://localhost:3000/api/health

# Test alert notifications
python3 scripts/test_alerts.py --channel slack --channel email
```

## Configuration Changes

### Environment Variables

#### Testnet Configuration (Before)
```bash
# .env.testnet
ENVIRONMENT=testnet

# Binance Testnet
BINANCE_TESTNET=true
BINANCE_API_URL=https://testnet.binance.vision
BINANCE_WS_URL=wss://testnet.binance.vision/ws
BINANCE_API_KEY=testnet_key
BINANCE_API_SECRET=testnet_secret

# Upbit (No official testnet - use small amounts)
UPBIT_API_URL=https://api.upbit.com
UPBIT_API_KEY=upbit_key
UPBIT_API_SECRET=upbit_secret

# Trading Configuration
TRADING_MODE=paper
ENABLE_AUTO_TRADING=true
MAX_POSITION_SIZE=10000        # High for testing
RISK_PER_TRADE=0.02           # 2% for testing
```

#### Mainnet Configuration (After)
```bash
# .env.mainnet
ENVIRONMENT=production

# Binance Mainnet
BINANCE_TESTNET=false
BINANCE_API_URL=https://api.binance.com
BINANCE_WS_URL=wss://stream.binance.com:9443/ws
BINANCE_API_KEY=mainnet_key
BINANCE_API_SECRET=mainnet_secret

# Upbit Mainnet
UPBIT_API_URL=https://api.upbit.com
UPBIT_API_KEY=upbit_mainnet_key
UPBIT_API_SECRET=upbit_mainnet_secret

# Trading Configuration - CONSERVATIVE INITIALLY
TRADING_MODE=live
ENABLE_AUTO_TRADING=false      # Manual approval first!
MAX_POSITION_SIZE=100          # Start small
RISK_PER_TRADE=0.005          # 0.5% risk
MAX_DAILY_LOSS=-500           # Emergency brake
MAX_OPEN_POSITIONS=3           # Limit exposure
```

### Configuration Files

#### Update Docker Compose
```yaml
# docker-compose.yml
services:
  tradingbot:
    environment:
      - ENVIRONMENT=production
      - TRADING_MODE=live
      - BINANCE_TESTNET=false
    # Add resource limits for production
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

#### Update Kubernetes ConfigMap
```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tradingbot-config
data:
  ENVIRONMENT: "production"
  TRADING_MODE: "live"
  BINANCE_TESTNET: "false"
  LOG_LEVEL: "INFO"
```

## API Key Setup

### Binance API Key Configuration

#### Create Mainnet API Keys
```
1. Login to Binance.com (NOT testnet.binance.vision)
2. Navigate to API Management
3. Create New Key with label "TradingBot-Production"

Required Permissions:
✅ Enable Reading
✅ Enable Spot & Margin Trading
❌ Enable Withdrawals (NEVER enable!)
✅ Enable Futures (if using futures)

IP Whitelist:
- Add production server IPs
- NEVER use "Unrestricted" option

Settings:
- Enable IP Access Restriction
- Set Daily Withdrawal Limit to 0
- Enable Google 2FA for API key changes
```

#### Store API Keys Securely
```bash
# Never commit to git!
# Use environment variables or secrets manager

# Option 1: Environment variables
export BINANCE_API_KEY="your_mainnet_api_key"
export BINANCE_API_SECRET="your_mainnet_api_secret"

# Option 2: AWS Secrets Manager
aws secretsmanager create-secret \
    --name tradingbot/binance/mainnet \
    --secret-string '{"api_key":"xxx","api_secret":"yyy"}'

# Option 3: Kubernetes Secret
kubectl create secret generic binance-mainnet \
    --from-literal=api_key=xxx \
    --from-literal=api_secret=yyy
```

### Upbit API Key Configuration

#### Create Upbit API Keys
```
1. Login to Upbit.com
2. Navigate to Customer Center > Open API Management
3. Create new API key with label "TradingBot-Production"

Required Permissions:
✅ View assets
✅ Place orders
✅ Cancel orders
❌ Withdraw (NEVER enable!)

IP Whitelist:
- Add production server IPs
- Maximum 10 IPs allowed

Settings:
- Enable IP Access Restriction
- Set Daily Trading Limit (recommended)
- Enable Google OTP for API management
```

## Database Migration

### Data Separation Strategy

```sql
-- Create separate schemas for testnet and mainnet data
CREATE SCHEMA testnet;
CREATE SCHEMA mainnet;

-- Move testnet data to testnet schema
ALTER TABLE trades SET SCHEMA testnet;
ALTER TABLE orders SET SCHEMA testnet;
ALTER TABLE positions SET SCHEMA testnet;

-- Create fresh tables in mainnet schema
CREATE TABLE mainnet.trades (LIKE testnet.trades INCLUDING ALL);
CREATE TABLE mainnet.orders (LIKE testnet.orders INCLUDING ALL);
CREATE TABLE mainnet.positions (LIKE testnet.positions INCLUDING ALL);

-- Update application to use mainnet schema
-- In src/database/models.py
__table_args__ = {'schema': 'mainnet'}
```

### Migration Script

```python
#!/usr/bin/env python3
# scripts/migrate_to_mainnet.py

import asyncio
from sqlalchemy import text
from src.database.engine import get_session

async def migrate_to_mainnet():
    async with get_session() as session:
        # 1. Create mainnet schema
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS mainnet"))

        # 2. Move testnet data to testnet schema
        await session.execute(text("CREATE SCHEMA IF NOT EXISTS testnet"))
        await session.execute(text("ALTER TABLE IF EXISTS trades SET SCHEMA testnet"))
        await session.execute(text("ALTER TABLE IF EXISTS orders SET SCHEMA testnet"))

        # 3. Create fresh mainnet tables
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS mainnet.trades (
                LIKE testnet.trades INCLUDING ALL
            )
        """))

        # 4. Verify migration
        result = await session.execute(text("""
            SELECT schema_name, table_name
            FROM information_schema.tables
            WHERE table_schema IN ('testnet', 'mainnet')
            ORDER BY schema_name, table_name
        """))

        print("Migration completed successfully:")
        for row in result:
            print(f"  {row.schema_name}.{row.table_name}")

        await session.commit()

if __name__ == "__main__":
    asyncio.run(migrate_to_mainnet())
```

## Switch Procedure

### Step-by-Step Switch Process

```bash
#!/bin/bash
# scripts/switch_to_mainnet.sh

set -e  # Exit on error

echo "========================================="
echo "  Testnet to Mainnet Switch Procedure"
echo "========================================="
echo

# Step 1: Pre-flight checks
echo "Step 1: Running pre-flight checks..."
python3 -m pytest tests/ -v
python3 scripts/verify_api_keys.py --exchange binance --mainnet
python3 scripts/verify_api_keys.py --exchange upbit --mainnet
echo "✅ Pre-flight checks passed"
echo

# Step 2: Backup current state
echo "Step 2: Creating backup..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump -h localhost -U tradingbot tradingbot > backup_pre_mainnet_${TIMESTAMP}.sql
echo "✅ Backup created: backup_pre_mainnet_${TIMESTAMP}.sql"
echo

# Step 3: Stop application
echo "Step 3: Stopping application..."
docker-compose down
echo "✅ Application stopped"
echo

# Step 4: Database migration
echo "Step 4: Running database migration..."
python3 scripts/migrate_to_mainnet.py
echo "✅ Database migrated"
echo

# Step 5: Switch configuration
echo "Step 5: Switching to mainnet configuration..."
cp .env .env.testnet.backup
cp .env.mainnet .env
echo "✅ Configuration switched"
echo

# Step 6: Update schema in code
echo "Step 6: Updating application schema..."
# This step requires code changes to point to mainnet schema
# Verify this has been done manually
read -p "Have you updated the schema in src/database/models.py to 'mainnet'? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo "❌ Please update schema first"
    exit 1
fi
echo "✅ Schema configuration confirmed"
echo

# Step 7: Start application
echo "Step 7: Starting application with mainnet configuration..."
docker-compose up -d
sleep 10  # Wait for startup
echo "✅ Application started"
echo

# Step 8: Verify health
echo "Step 8: Verifying application health..."
curl http://localhost:8000/health | jq .
curl http://localhost:8000/ready | jq .
echo "✅ Health checks passed"
echo

# Step 9: Verify exchange connectivity
echo "Step 9: Verifying exchange connectivity..."
python3 scripts/test_exchanges.py
echo "✅ Exchange connectivity verified"
echo

# Step 10: Final checks
echo "Step 10: Running final verification..."
python3 scripts/verify_mainnet_switch.py
echo "✅ Mainnet switch completed successfully!"
echo

echo "========================================="
echo "  IMPORTANT: Trading is DISABLED"
echo "  Enable with: ENABLE_AUTO_TRADING=true"
echo "========================================="
```

### Verification Script

```python
#!/usr/bin/env python3
# scripts/verify_mainnet_switch.py

import asyncio
import os
from src.services.exchange.binance_manager import BinanceExchangeManager
from src.services.exchange.upbit_manager import UpbitExchangeManager

async def verify_mainnet_switch():
    print("Verifying mainnet configuration...")

    # Check environment
    env = os.getenv("ENVIRONMENT")
    if env != "production":
        raise ValueError(f"❌ ENVIRONMENT should be 'production', got '{env}'")
    print(f"✅ Environment: {env}")

    # Check trading mode
    trading_mode = os.getenv("TRADING_MODE")
    if trading_mode != "live":
        raise ValueError(f"❌ TRADING_MODE should be 'live', got '{trading_mode}'")
    print(f"✅ Trading mode: {trading_mode}")

    # Check Binance testnet flag
    binance_testnet = os.getenv("BINANCE_TESTNET", "false").lower()
    if binance_testnet != "false":
        raise ValueError(f"❌ BINANCE_TESTNET should be 'false', got '{binance_testnet}'")
    print(f"✅ Binance testnet: {binance_testnet}")

    # Test Binance connection
    binance = BinanceExchangeManager()
    await binance.initialize()
    account_info = await binance.get_account()
    print(f"✅ Binance connected (Account Type: {account_info.get('accountType')})")

    # Test Upbit connection
    upbit = UpbitExchangeManager()
    await upbit.initialize()
    balance = await upbit.get_balance()
    print(f"✅ Upbit connected (Balance keys: {list(balance.keys())[:3]}...)")

    # Verify auto-trading is disabled
    auto_trading = os.getenv("ENABLE_AUTO_TRADING", "false").lower()
    if auto_trading == "true":
        print("⚠️  WARNING: Auto-trading is ENABLED!")
        print("   Consider setting ENABLE_AUTO_TRADING=false initially")
    else:
        print(f"✅ Auto-trading disabled (safe mode)")

    print("\n✅ All mainnet verifications passed!")
    print("\nNext steps:")
    print("1. Monitor logs for 30 minutes")
    print("2. Execute test trades manually")
    print("3. Verify trades in exchange UI")
    print("4. Gradually enable auto-trading if all checks pass")

if __name__ == "__main__":
    asyncio.run(verify_mainnet_switch())
```

## Post-Switch Validation

### Immediate Validation (First 30 Minutes)

```bash
# 1. Monitor application logs
docker-compose logs -f tradingbot | grep -i -E "error|warning|exchange|trade"

# 2. Check system health
curl http://localhost:8000/health | jq .
curl http://localhost:8000/ready | jq .

# 3. Verify exchange connections
curl http://localhost:8000/api/exchange-status | jq .

# 4. Check database connectivity
docker exec -it tradingbot-db psql -U tradingbot -c "SELECT COUNT(*) FROM mainnet.trades;"

# 5. Verify monitoring metrics
curl http://localhost:8000/metrics | grep -E "trading|exchange"
```

### Manual Test Trade

```bash
# Execute a SMALL test trade manually
# 1. Via API (if enabled)
curl -X POST http://localhost:8000/api/orders \
    -H "Authorization: Bearer YOUR_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": 0.0001,
        "order_type": "market"
    }'

# 2. Via Python script
python3 scripts/test_trade.py \
    --exchange binance \
    --symbol BTCUSDT \
    --side buy \
    --quantity 0.0001 \
    --type market

# 3. Verify in exchange UI
# - Login to Binance.com
# - Check Trade History
# - Confirm order executed with correct parameters
```

### Extended Validation (First 24 Hours)

**Hour 1-2: Passive Monitoring**
- Monitor logs for errors
- Watch Grafana dashboards
- Check alert notifications
- Verify no unexpected behavior

**Hour 2-4: Small Manual Trades**
- Execute 3-5 small manual trades
- Verify correct execution
- Check P&L calculation
- Validate position tracking

**Hour 4-8: Gradual Automation**
- Enable one strategy at a time
- Monitor each strategy for 1 hour
- Verify strategy behavior matches testnet
- Check risk management enforcement

**Hour 8-24: Full Monitoring**
- All strategies enabled (if previous steps passed)
- Continuous monitoring
- Review all metrics hourly
- Be ready to disable auto-trading instantly

### Validation Checklist

```
Immediate (0-30 min):
- [ ] Application started successfully
- [ ] Health checks passing
- [ ] Exchange connections established
- [ ] Database accessible
- [ ] Monitoring collecting metrics
- [ ] No error logs

Short-term (30 min - 2 hours):
- [ ] Manual test trade executed successfully
- [ ] Trade visible in exchange UI
- [ ] Position tracking accurate
- [ ] P&L calculation correct
- [ ] Risk limits enforced
- [ ] Alerts working

Medium-term (2-8 hours):
- [ ] Multiple strategies tested
- [ ] No unexpected behavior
- [ ] Performance metrics normal
- [ ] Resource usage acceptable
- [ ] Exchange rate limits not exceeded

Long-term (8-24 hours):
- [ ] All strategies performing as expected
- [ ] No critical incidents
- [ ] Monitoring stable
- [ ] Team comfortable with operations
- [ ] Ready for normal operations
```

## Rollback Procedure

### Emergency Rollback

```bash
#!/bin/bash
# scripts/rollback_to_testnet.sh

echo "========================================="
echo "  EMERGENCY ROLLBACK TO TESTNET"
echo "========================================="

# Step 1: IMMEDIATELY stop application
echo "Step 1: Stopping application..."
docker-compose down
pkill -f "python3 -m uvicorn"  # Ensure all processes stopped
echo "✅ Application stopped"

# Step 2: Restore testnet configuration
echo "Step 2: Restoring testnet configuration..."
cp .env.testnet.backup .env
echo "✅ Configuration restored"

# Step 3: Restore database (if needed)
echo "Step 3: Database rollback..."
read -p "Restore database from backup? (yes/no): " restore_db
if [ "$restore_db" == "yes" ]; then
    read -p "Enter backup filename: " backup_file
    psql -h localhost -U tradingbot tradingbot < $backup_file
    echo "✅ Database restored"
else
    # Just switch schema back
    psql -h localhost -U tradingbot -c "ALTER TABLE mainnet.trades SET SCHEMA testnet"
    echo "✅ Schema switched back"
fi

# Step 4: Restart with testnet
echo "Step 4: Restarting with testnet..."
docker-compose up -d
sleep 10
echo "✅ Application restarted"

# Step 5: Verify testnet mode
echo "Step 5: Verifying testnet mode..."
curl http://localhost:8000/health | jq .
python3 scripts/verify_testnet.py
echo "✅ Rollback completed"

echo "========================================="
echo "  Rollback successful - Running on TESTNET"
echo "========================================="
```

### Rollback Decision Criteria

**Immediate Rollback Required If**:
- ❌ Application won't start on mainnet
- ❌ Exchange API authentication fails
- ❌ Unexpected trades being executed
- ❌ Critical bugs discovered
- ❌ Security concerns identified
- ❌ Database corruption detected

**Consider Rollback If**:
- ⚠️  High error rates (>5% of requests)
- ⚠️  Performance significantly degraded
- ⚠️  Monitoring/alerts not working
- ⚠️  Unexpected behavior in strategies
- ⚠️  Team not comfortable with stability

**Can Continue Despite**:
- ✅ Minor log warnings
- ✅ Small performance variations
- ✅ Non-critical feature issues
- ✅ Cosmetic UI problems

## Best Practices

### Progressive Rollout

1. **Day 1: Observation Mode**
   - ENABLE_AUTO_TRADING=false
   - Manual trades only
   - Small position sizes
   - Continuous monitoring

2. **Day 2-3: Single Strategy**
   - Enable one low-risk strategy
   - Limited position sizes
   - Frequent monitoring
   - Quick disable if issues

3. **Day 4-7: Multiple Strategies**
   - Gradually enable strategies
   - Increase position sizes slowly
   - Daily performance reviews
   - Team debriefs

4. **Week 2+: Full Operations**
   - All strategies enabled
   - Normal position sizes
   - Standard monitoring
   - Regular reviews

### Risk Management

```bash
# Start with conservative limits
MAX_POSITION_SIZE=100          # 10x smaller than testnet
RISK_PER_TRADE=0.005          # Half of testnet
MAX_DAILY_LOSS=-500           # Hard stop
MAX_OPEN_POSITIONS=3           # Limit exposure

# Gradually increase over weeks
Week 1: MAX_POSITION_SIZE=100
Week 2: MAX_POSITION_SIZE=250
Week 3: MAX_POSITION_SIZE=500
Week 4: MAX_POSITION_SIZE=1000  # Target level
```

### Team Communication

```yaml
# Communication Plan
before_switch:
  - Notify all team members 24 hours before
  - Schedule war room for switch window
  - Assign roles and responsibilities

during_switch:
  - Dedicated Slack channel
  - 15-minute status updates
  - Log all changes and observations

after_switch:
  - Hourly updates for first 8 hours
  - Daily summary for first week
  - Weekly review meetings
```

## Monitoring and Alerts

### Critical Alerts for Mainnet

```yaml
# Mainnet-specific alerts
- alert: MainnetUnauthorizedTrade
  expr: trading_trades_total{mode="live"} unless on() trading_manual_approval
  severity: critical
  action: IMMEDIATE SHUTDOWN

- alert: MainnetDailyLossExceeded
  expr: trading_pnl_total_usd < -500
  severity: critical
  action: DISABLE AUTO-TRADING

- alert: MainnetPositionSizeExceeded
  expr: trading_position_size_usd > 1000
  severity: critical
  action: REVIEW IMMEDIATELY
```

## Additional Resources

- Deployment Guide: `DEPLOYMENT.md`
- Incident Response: `INCIDENT_RESPONSE.md`
- Monitoring Setup: `MONITORING.md`
- Performance Tuning: `PERFORMANCE_TUNING.md`
- Backup Procedures: `BACKUP_RECOVERY.md`

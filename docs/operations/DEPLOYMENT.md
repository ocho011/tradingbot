# Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Secrets Configuration](#secrets-configuration)
4. [Deployment Steps](#deployment-steps)
5. [Verification](#verification)
6. [Rollback Procedures](#rollback-procedures)

## Prerequisites

### System Requirements
- **Python**: 3.11 or higher
- **Docker**: 24.0 or higher (for containerized deployment)
- **PostgreSQL**: 15.0 or higher
- **Redis**: 7.0 or higher
- **Memory**: Minimum 4GB RAM (8GB recommended for production)
- **CPU**: Minimum 2 cores (4 cores recommended for production)
- **Storage**: Minimum 20GB available disk space

### Required Access
- Database credentials with CREATE/ALTER/DROP permissions
- Exchange API keys (Binance, Upbit, etc.)
- Monitoring system access (Prometheus, Grafana)
- CI/CD pipeline credentials (GitHub Actions)

## Environment Setup

### 1. Clone and Setup Repository
```bash
# Clone repository
git clone https://github.com/your-org/tradingbot.git
cd tradingbot

# Create and activate virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Environment Configuration
Create `.env` file in the project root:

```bash
# Application Environment
ENVIRONMENT=production  # Options: development, staging, production
DEBUG=false
LOG_LEVEL=INFO

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/tradingbot
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# Redis Configuration
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=50

# API Server Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
API_TIMEOUT=30

# Trading Configuration
TRADING_MODE=live  # Options: paper, live
DEFAULT_LEVERAGE=1
MAX_POSITION_SIZE=1000
RISK_PER_TRADE=0.01

# Exchange API Keys (See Secrets Configuration section)
# BINANCE_API_KEY=
# BINANCE_API_SECRET=
# UPBIT_API_KEY=
# UPBIT_API_SECRET=

# Monitoring & Logging
PROMETHEUS_PORT=9090
GRAFANA_PORT=3000
STRUCTURED_LOGGING=true
JSON_LOGS=true

# Security
JWT_SECRET=  # Generate with: openssl rand -hex 32
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
CORS_ORIGINS=https://your-domain.com

# Feature Flags
ENABLE_WEBSOCKET=true
ENABLE_PAPER_TRADING=false
ENABLE_AUTO_TRADING=false
```

### 3. Database Setup
```bash
# Initialize database
alembic upgrade head

# Verify database connection
python3 -c "from src.database.engine import engine; engine.connect()"

# Run initial data migration if needed
python3 scripts/init_db.py
```

### 4. Redis Setup
```bash
# Verify Redis connection
python3 -c "import redis; r = redis.from_url('redis://localhost:6379/0'); r.ping()"
```

## Secrets Configuration

### Critical Secrets Checklist
- [ ] Database credentials
- [ ] Exchange API keys
- [ ] JWT secret key
- [ ] Redis password (if applicable)
- [ ] Prometheus/Grafana credentials
- [ ] GitHub webhook secrets

### Exchange API Keys Setup

#### Binance
```bash
# Testnet (for testing)
export BINANCE_TESTNET=true
export BINANCE_API_KEY="your_testnet_api_key"
export BINANCE_API_SECRET="your_testnet_api_secret"

# Mainnet (production)
export BINANCE_TESTNET=false
export BINANCE_API_KEY="your_mainnet_api_key"
export BINANCE_API_SECRET="your_mainnet_api_secret"
```

**API Permissions Required:**
- ✅ Enable Reading
- ✅ Enable Spot & Margin Trading
- ❌ Enable Withdrawals (NOT REQUIRED)
- ✅ Enable Futures (if using futures trading)

#### Upbit
```bash
export UPBIT_API_KEY="your_api_key"
export UPBIT_API_SECRET="your_api_secret"
```

**API Permissions Required:**
- ✅ View assets
- ✅ Place orders
- ✅ Cancel orders
- ❌ Withdraw (NOT REQUIRED)

### Secrets Management Best Practices

1. **Never commit secrets to version control**
   - Use `.env` files (add to `.gitignore`)
   - Use environment variables
   - Use secrets management tools (AWS Secrets Manager, HashiCorp Vault, etc.)

2. **Rotate secrets regularly**
   - Exchange API keys: Every 90 days
   - JWT secrets: Every 180 days
   - Database passwords: Every 90 days

3. **Use different secrets for each environment**
   - Development
   - Staging
   - Production

4. **Restrict API key permissions**
   - Only enable required permissions
   - Use IP whitelisting when available
   - Enable 2FA for exchange accounts

## Deployment Steps

### Docker Deployment (Recommended)

#### 1. Build Docker Images
```bash
# Build application image
docker build -t tradingbot:latest .

# Build with specific version tag
docker build -t tradingbot:v1.0.0 .
```

#### 2. Run with Docker Compose
```bash
# Start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f tradingbot

# Stop services
docker-compose down
```

#### 3. Docker Compose Configuration
The `docker-compose.yml` includes:
- Trading bot application
- PostgreSQL database
- Redis cache
- Prometheus monitoring
- Grafana dashboards

### Manual Deployment

#### 1. Install System Dependencies
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y postgresql-15 redis-server python3.11 python3.11-venv

# macOS
brew install postgresql@15 redis python@3.11
```

#### 2. Start Services
```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Start Redis
sudo systemctl start redis
sudo systemctl enable redis
```

#### 3. Run Application
```bash
# Activate virtual environment
source venv/bin/activate

# Run database migrations
alembic upgrade head

# Start the application
python3 -m uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 4

# Or using the startup script
./scripts/start.sh
```

### Kubernetes Deployment

```bash
# Apply Kubernetes configurations
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# Check deployment status
kubectl get pods -n tradingbot
kubectl get services -n tradingbot

# View logs
kubectl logs -f deployment/tradingbot -n tradingbot
```

## Verification

### 1. Health Checks
```bash
# Check application health
curl http://localhost:8000/health

# Expected response:
{
  "status": "healthy",
  "uptime_seconds": 123.45,
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "exchanges": "healthy"
  },
  "timestamp": "2024-01-17T12:00:00Z"
}
```

### 2. Readiness Checks
```bash
# Check if application is ready to receive traffic
curl http://localhost:8000/ready

# Expected response:
{
  "status": "ready",
  "components": {
    "database": "healthy",
    "orchestrator": "healthy",
    "monitoring": "healthy"
  }
}
```

### 3. Metrics Verification
```bash
# Check Prometheus metrics
curl http://localhost:8000/metrics

# Should return Prometheus-formatted metrics
```

### 4. Database Connectivity
```bash
# Test database connection
python3 -c "from src.database.engine import get_session; import asyncio; asyncio.run(get_session().__anext__())"
```

### 5. Exchange Connectivity
```bash
# Test exchange connections
python3 scripts/test_exchanges.py

# Should show successful connections to all configured exchanges
```

### 6. API Endpoints Test
```bash
# Test status endpoint (requires authentication)
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" http://localhost:8000/api/status

# Test trading endpoints
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" http://localhost:8000/api/strategies
```

## Rollback Procedures

### Application Rollback

#### Docker Deployment
```bash
# Rollback to previous version
docker-compose down
docker-compose up -d tradingbot:v0.9.0

# Or using image tag
docker tag tradingbot:v1.0.0 tradingbot:rollback
docker-compose up -d
```

#### Manual Deployment
```bash
# Stop current application
pkill -f "uvicorn src.api.server"

# Checkout previous version
git checkout v0.9.0

# Restart application
./scripts/start.sh
```

#### Kubernetes Deployment
```bash
# Rollback deployment
kubectl rollout undo deployment/tradingbot -n tradingbot

# Rollback to specific revision
kubectl rollout undo deployment/tradingbot --to-revision=2 -n tradingbot

# Check rollback status
kubectl rollout status deployment/tradingbot -n tradingbot
```

### Database Rollback

```bash
# View migration history
alembic history

# Rollback to previous migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade <revision_id>

# Rollback all migrations (DANGER!)
alembic downgrade base
```

### Configuration Rollback

```bash
# Restore from backup
cp /backup/.env.backup .env

# Restart services
docker-compose restart
# or
./scripts/restart.sh
```

## Post-Deployment Checklist

- [ ] All health checks passing
- [ ] Database migrations applied successfully
- [ ] Exchange connections established
- [ ] Monitoring dashboards showing data
- [ ] Logs being collected properly
- [ ] Alerts configured and tested
- [ ] Backup procedures verified
- [ ] Performance baselines established
- [ ] Documentation updated
- [ ] Team notified of deployment

## Troubleshooting

### Application Won't Start
```bash
# Check logs
docker-compose logs tradingbot
# or
tail -f /var/log/tradingbot/app.log

# Common issues:
# - Database connection failed: Check DATABASE_URL
# - Redis connection failed: Check REDIS_URL
# - Port already in use: Check if another instance is running
```

### Database Connection Issues
```bash
# Test PostgreSQL connection
psql -h localhost -U tradingbot -d tradingbot

# Check PostgreSQL status
sudo systemctl status postgresql
```

### Exchange Connection Issues
```bash
# Verify API keys are correct
python3 scripts/verify_api_keys.py

# Check IP whitelist settings on exchange
# Check API key permissions
```

## Support and Escalation

For deployment issues:
1. Check this documentation
2. Review logs and health checks
3. Consult incident response manual (INCIDENT_RESPONSE.md)
4. Contact DevOps team
5. Escalate to engineering team if needed

Emergency contacts in INCIDENT_RESPONSE.md

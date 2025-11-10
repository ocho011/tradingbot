# Docker Deployment Guide

Complete guide for deploying the Trading Bot using Docker and Docker Compose.

## 📋 Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+
- 4GB RAM minimum
- 10GB disk space

## 🚀 Quick Start

### 1. Configure Environment

```bash
# Copy the Docker environment template
cp .env.docker .env

# Edit .env with your Binance API credentials
nano .env
```

**Required Environment Variables:**
- `BINANCE_TESTNET_API_KEY`: Your Binance testnet API key
- `BINANCE_TESTNET_SECRET_KEY`: Your Binance testnet secret key
- `POSTGRES_PASSWORD`: Strong database password

### 2. Build and Start Services

```bash
# Build all images
docker-compose build

# Start all services in background
docker-compose up -d

# View logs
docker-compose logs -f tradingbot
```

### 3. Verify Services

```bash
# Check service status
docker-compose ps

# All services should show "healthy" status
# - tradingbot: healthy
# - redis: healthy
# - postgres: healthy
# - prometheus: healthy
# - grafana: healthy
```

### 4. Access Applications

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Trading Bot API | http://localhost:8000/docs | - |
| Prometheus | http://localhost:9090 | - |
| Grafana | http://localhost:3000 | admin/admin |
| Redis | localhost:6379 | - |
| PostgreSQL | localhost:5432 | tradingbot/[your-password] |

## 📦 Service Architecture

```
┌─────────────────┐
│   Trading Bot   │ :8000
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
┌───▼──┐  ┌──▼────┐
│Redis │  │Postgres│
│:6379 │  │:5432   │
└──────┘  └────────┘
    │
┌───▼────────┐
│ Prometheus │ :9090
└─────┬──────┘
      │
┌─────▼───┐
│ Grafana │ :3000
└─────────┘
```

## 🔧 Docker Commands

### Build & Start
```bash
# Build without cache
docker-compose build --no-cache

# Start specific service
docker-compose up -d tradingbot

# Scale services (not applicable for singleton services)
docker-compose up -d --scale tradingbot=1
```

### Logs & Debugging
```bash
# View logs from all services
docker-compose logs

# Follow logs for specific service
docker-compose logs -f tradingbot

# View last 100 lines
docker-compose logs --tail=100 tradingbot

# Check resource usage
docker stats
```

### Stop & Cleanup
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes all data)
docker-compose down -v

# Remove specific volume
docker volume rm tradingbot_postgres_data

# Prune unused images and containers
docker system prune -a
```

### Database Operations
```bash
# Access PostgreSQL shell
docker-compose exec postgres psql -U tradingbot -d tradingbot

# Backup database
docker-compose exec postgres pg_dump -U tradingbot tradingbot > backup.sql

# Restore database
docker-compose exec -T postgres psql -U tradingbot -d tradingbot < backup.sql

# View Redis data
docker-compose exec redis redis-cli
```

## 📊 Monitoring & Metrics

### Prometheus Metrics

Access Prometheus at http://localhost:9090

**Key Metrics:**
```promql
# Trading signals generated
trading_signals_generated_total

# Order execution latency
rate(order_execution_latency_seconds_sum[5m])

# Position P&L
trading_position_pnl

# API request rate
rate(http_requests_total[1m])
```

### Grafana Dashboards

Access Grafana at http://localhost:3000 (admin/admin)

**Setup:**
1. Add Prometheus data source: http://prometheus:9090
2. Import dashboard or create custom
3. Configure alerts for critical metrics

## 🔒 Security Best Practices

### 1. Secure Secrets

```bash
# Generate strong passwords
openssl rand -base64 32

# Use Docker secrets in production
docker secret create postgres_password ./postgres_password.txt
```

### 2. Network Security

```bash
# Restrict port exposure in production
# Edit docker-compose.yml to bind only to localhost:
ports:
  - "127.0.0.1:8000:8000"  # API only accessible from localhost
```

### 3. Update Regularly

```bash
# Pull latest base images
docker-compose pull

# Rebuild with latest dependencies
docker-compose build --pull
```

## 🐛 Troubleshooting

### Service Won't Start

```bash
# Check logs
docker-compose logs tradingbot

# Verify environment variables
docker-compose exec tradingbot env | grep BINANCE

# Check disk space
df -h
```

### Database Connection Issues

```bash
# Verify PostgreSQL is running
docker-compose ps postgres

# Test connection
docker-compose exec tradingbot nc -zv postgres 5432

# Check PostgreSQL logs
docker-compose logs postgres
```

### Build Failures

```bash
# Clear build cache
docker builder prune -a

# Build with verbose output
docker-compose build --progress=plain --no-cache

# Check Dockerfile syntax
docker build --check .
```

### Health Check Failures

```bash
# Inspect container health
docker inspect tradingbot | jq '.[0].State.Health'

# Manual health check
docker-compose exec tradingbot curl -f http://localhost:8000/health
```

## 📈 Performance Tuning

### Resource Limits

Edit `docker-compose.yml` to adjust resource limits:

```yaml
deploy:
  resources:
    limits:
      cpus: '2'      # Increase for better performance
      memory: 4G     # Increase if OOM errors occur
```

### Volume Performance

For better I/O performance on Linux:

```yaml
volumes:
  - ./data:/app/data:delegated  # macOS/Windows
  - ./data:/app/data:cached     # Linux
```

## 🔄 Updates & Maintenance

### Update Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

### Database Migrations

```bash
# Run migrations
docker-compose exec tradingbot alembic upgrade head

# Rollback migration
docker-compose exec tradingbot alembic downgrade -1
```

### Backup Strategy

```bash
# Create backup script
cat > backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker-compose exec -T postgres pg_dump -U tradingbot tradingbot | gzip > backup_${DATE}.sql.gz
docker-compose exec redis redis-cli BGSAVE
echo "Backup completed: backup_${DATE}.sql.gz"
EOF

chmod +x backup.sh

# Schedule with cron
crontab -e
# Add: 0 2 * * * /path/to/backup.sh
```

## 🌐 Production Deployment

### Environment-Specific Configurations

```bash
# Development
docker-compose up -d

# Staging
docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name trading.example.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### SSL/TLS Setup

```bash
# Using Let's Encrypt
certbot --nginx -d trading.example.com
```

## 📚 Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)

---

**Need Help?** Check the [main README](../README.md) or open an issue on GitHub.

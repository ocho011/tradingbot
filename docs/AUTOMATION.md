# Automation System Documentation

## Overview

This document describes the automation system for the Trading Bot, including backup, recovery, monitoring, and fault tolerance mechanisms.

## Components

### 1. Database Backup Automation

Automated daily backups of SQLite and PostgreSQL databases with retention policies.

#### Features
- **Scheduled Backups**: Daily automatic backups at 2:00 AM
- **Compression**: Automatic gzip compression of backup files
- **Integrity Verification**: Post-backup validation
- **Retention Policy**: Configurable retention (default: 7 days)
- **Multiple Database Support**: SQLite and PostgreSQL
- **Logging**: Comprehensive backup logs

#### Usage

**Manual Backup:**
```bash
./scripts/backup_database.sh
```

**Environment Variables:**
```bash
BACKUP_DIR=/path/to/backups       # Backup directory (default: ./backups)
LOG_FILE=/path/to/backup.log      # Log file path
RETENTION_DAYS=7                  # Days to keep backups
```

**Backup Files:**
- SQLite: `sqlite_backup_YYYYMMDD_HHMMSS.db.gz`
- PostgreSQL: `postgres_backup_YYYYMMDD_HHMMSS.sql.gz`

### 2. Database Restore

Automated database restore with validation and safety checks.

#### Features
- **Interactive Restore**: Confirmation prompts for safety
- **Latest Backup Selection**: Automatic selection of most recent backup
- **Pre-restore Backup**: Current database backed up before restore
- **Integrity Verification**: Post-restore validation
- **Rollback Capability**: Can restore from pre-restore backup

#### Usage

**Restore Latest Backup:**
```bash
./scripts/restore_database.sh --type sqlite
./scripts/restore_database.sh --type postgres
```

**Restore Specific Backup:**
```bash
./scripts/restore_database.sh --type sqlite --file backup_20240101_120000.db.gz
```

**Skip Confirmation:**
```bash
./scripts/restore_database.sh --type sqlite --yes
```

**List Available Backups:**
```bash
./scripts/restore_database.sh --type sqlite  # Shows list before restore
```

### 3. systemd Service Management

Production-ready systemd service configuration with automatic restart and monitoring.

#### Service Files

**Main Service:** `tradingbot.service`
- Automatic restart on failure
- Watchdog monitoring
- Resource limits
- Security hardening
- Health checks

**Backup Service:** `tradingbot-backup.service`
- One-shot backup execution
- Integrated with main service

**Backup Timer:** `tradingbot-backup.timer`
- Daily scheduling at 2:00 AM
- Persistent across reboots
- Randomized delay for load distribution

#### Installation

```bash
# Copy service files
sudo cp config/systemd/*.service /etc/systemd/system/
sudo cp config/systemd/*.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable tradingbot.service
sudo systemctl enable tradingbot-backup.timer

# Start services
sudo systemctl start tradingbot.service
sudo systemctl start tradingbot-backup.timer
```

#### Service Management

```bash
# Start/stop service
sudo systemctl start tradingbot
sudo systemctl stop tradingbot
sudo systemctl restart tradingbot

# Check status
sudo systemctl status tradingbot

# View logs
sudo journalctl -u tradingbot -f

# Backup management
sudo systemctl start tradingbot-backup.service  # Manual backup
sudo systemctl list-timers                       # Check timer status
```

### 4. Log Rotation

Automatic log rotation with compression and retention policies.

#### Features
- **Daily Rotation**: Automatic daily log rotation
- **Compression**: Old logs compressed with gzip
- **Retention**: 30 days for main logs, 12 weeks for backup logs
- **Size Limits**: Maximum 100MB before forced rotation
- **Service Reload**: Automatic service reload after rotation

#### Installation

```bash
# Copy logrotate config
sudo cp config/logrotate/tradingbot /etc/logrotate.d/tradingbot

# Test configuration
sudo logrotate -d /etc/logrotate.d/tradingbot

# Manual rotation
sudo logrotate -f /etc/logrotate.d/tradingbot
```

#### Configuration

Located in `/etc/logrotate.d/tradingbot`:
- Main logs: Daily rotation, 30 day retention
- Backup logs: Weekly rotation, 12 week retention
- Service logs: Daily rotation, 7 day retention

### 5. Circuit Breaker Pattern

Fault tolerance mechanism to prevent cascading failures and provide graceful degradation.

#### Features
- **Three States**: CLOSED → OPEN → HALF_OPEN
- **Failure Detection**: Configurable failure threshold
- **Failure Rate Monitoring**: Track failure percentage
- **Slow Call Detection**: Identify performance degradation
- **Automatic Recovery**: Self-healing after timeout
- **Statistics Tracking**: Comprehensive metrics

#### Usage

**Basic Usage:**
```python
from src.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

# Create circuit breaker
config = CircuitBreakerConfig(
    failure_threshold=5,      # Open after 5 failures
    success_threshold=2,      # Close after 2 successes in half-open
    timeout=60.0,            # Wait 60s before trying half-open
    failure_rate_threshold=0.5  # Open at 50% failure rate
)

breaker = CircuitBreaker("api_service", config)

# Use as decorator
@breaker
def call_api():
    response = requests.get("https://api.example.com")
    return response.json()

# Use as wrapper
try:
    result = call_api()
except CircuitBreakerError:
    # Circuit is open, use fallback
    result = get_cached_data()
```

**Advanced Usage:**
```python
from src.core.circuit_breaker import get_circuit_breaker, CircuitBreakerConfig

# Get breaker from global registry
breaker = get_circuit_breaker(
    "external_api",
    config=CircuitBreakerConfig(
        failure_threshold=3,
        timeout=30.0,
        slow_call_threshold=5.0  # Calls > 5s are failures
    ),
    on_state_change=lambda old, new: logger.warning(f"State changed: {old} -> {new}")
)

# Manual call
def risky_operation():
    # ... operation code ...
    return result

try:
    result = breaker.call(risky_operation)
except CircuitBreakerError as e:
    # Handle open circuit
    logger.error(f"Circuit breaker open: {e}")
    result = fallback_value
```

**Monitoring:**
```python
# Get statistics
stats = breaker.get_stats()
print(f"Total calls: {stats.total_calls}")
print(f"Failed calls: {stats.failed_calls}")
print(f"Rejection rate: {stats.rejected_calls / stats.total_calls:.2%}")
print(f"Current state: {stats.current_state.value}")

# Get failure rate
failure_rate = stats.get_failure_rate()
print(f"Failure rate: {failure_rate:.2%}")

# Manual reset
breaker.reset()
```

#### Circuit States

**CLOSED (Normal Operation)**
- All calls pass through
- Failure count tracked
- Opens if failure threshold exceeded

**OPEN (Fault Detected)**
- All calls rejected immediately with `CircuitBreakerError`
- Fast fail - no actual call made
- Prevents cascading failures
- Waits for timeout period

**HALF_OPEN (Testing Recovery)**
- Limited calls allowed
- Success → transition to CLOSED
- Failure → return to OPEN
- Used to test if service recovered

### 6. Recovery Testing

Automated test suite for validating backup and restore procedures.

#### Test Coverage
- Backup script validation
- Restore script validation
- SQLite backup/restore cycle
- PostgreSQL backup/restore (if available)
- Backup retention policy
- systemd configuration
- Logrotate configuration
- Circuit breaker implementation

#### Usage

```bash
# Run all tests
./scripts/test_recovery.sh

# View test log
cat logs/recovery_test.log
```

#### Test Output

```
==========================================
Recovery Test Summary
==========================================
Total tests: 8
Passed: 8
Failed: 0
Pass rate: 100%
==========================================
```

### 7. Installation Script

Complete automation system installation with user creation, service setup, and configuration.

#### Features
- User and directory creation
- File deployment
- Python virtual environment setup
- systemd service installation
- Logrotate configuration
- Backup automation setup
- Recovery testing
- Configuration validation

#### Usage

```bash
# Standard installation
sudo ./scripts/install_automation.sh

# Custom installation
sudo ./scripts/install_automation.sh --user myuser --dir /home/myuser/tradingbot

# Skip tests
sudo ./scripts/install_automation.sh --skip-tests
```

#### Installation Steps
1. Creates system user
2. Copies files to installation directory
3. Sets up Python virtual environment
4. Installs dependencies
5. Configures environment file
6. Installs systemd services
7. Sets up logrotate
8. Configures cron backups
9. Enables services
10. Runs recovery tests

## Configuration

### Environment Variables

```bash
# Database
DATABASE_PATH=/opt/tradingbot/data/tradingbot.db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=tradingbot
POSTGRES_USER=tradingbot
POSTGRES_PASSWORD=secure_password

# Backup
BACKUP_DIR=/opt/tradingbot/backups
LOG_FILE=/opt/tradingbot/logs/backup.log
RETENTION_DAYS=7

# Service
API_HOST=0.0.0.0
API_PORT=8000
```

### Circuit Breaker Configuration

```python
CircuitBreakerConfig(
    failure_threshold=5,           # Consecutive failures to open
    success_threshold=2,           # Successes to close from half-open
    timeout=60.0,                  # Seconds before trying half-open
    window_size=100,               # Size of rolling window
    failure_rate_threshold=0.5,    # Failure rate to open (50%)
    half_open_max_calls=1,         # Max concurrent calls in half-open
    slow_call_threshold=5.0,       # Slow call threshold (seconds)
    minimum_calls=10               # Min calls before checking rate
)
```

## Monitoring

### Service Status

```bash
# Check service status
systemctl status tradingbot

# View logs
journalctl -u tradingbot -f

# Check backup timer
systemctl list-timers tradingbot-backup.timer
```

### Backup Monitoring

```bash
# Check recent backups
ls -lh /opt/tradingbot/backups/

# View backup logs
tail -f /opt/tradingbot/logs/backup.log

# Verify backup integrity
gunzip -t /opt/tradingbot/backups/sqlite_backup_*.db.gz
```

### Circuit Breaker Monitoring

```python
from src.core.circuit_breaker import get_circuit_breaker

# Get breaker
breaker = get_circuit_breaker("service_name")

# Get stats
stats = breaker.get_stats()

# Log metrics
logger.info(f"Circuit: {breaker.name}")
logger.info(f"State: {stats.current_state.value}")
logger.info(f"Total calls: {stats.total_calls}")
logger.info(f"Failed calls: {stats.failed_calls}")
logger.info(f"Rejected calls: {stats.rejected_calls}")
logger.info(f"Failure rate: {stats.get_failure_rate():.2%}")
```

## Troubleshooting

### Backup Issues

**Problem:** Backup script fails
```bash
# Check script permissions
ls -l scripts/backup_database.sh

# Make executable
chmod +x scripts/backup_database.sh

# Check logs
tail -100 logs/backup.log
```

**Problem:** Not enough disk space
```bash
# Check disk usage
df -h

# Clean old backups
find backups/ -name "*.gz" -mtime +7 -delete
```

### Restore Issues

**Problem:** Restore fails
```bash
# Verify backup integrity
gunzip -t backups/sqlite_backup_*.db.gz

# Check database path
echo $DATABASE_PATH

# Manual restore
gunzip -c backup.db.gz > data/tradingbot.db
```

### Service Issues

**Problem:** Service won't start
```bash
# Check service status
systemctl status tradingbot

# View recent logs
journalctl -u tradingbot -n 50

# Validate configuration
/opt/tradingbot/venv/bin/python -m src --validate
```

**Problem:** Service keeps restarting
```bash
# Check restart limit
systemctl show tradingbot | grep Restart

# Reset failed state
systemctl reset-failed tradingbot

# Check resource limits
systemctl show tradingbot | grep Memory
systemctl show tradingbot | grep CPU
```

### Circuit Breaker Issues

**Problem:** Circuit stuck open
```python
# Check current state
breaker = get_circuit_breaker("service_name")
print(f"State: {breaker.state}")
print(f"Stats: {breaker.get_stats()}")

# Manual reset if needed
breaker.reset()
```

**Problem:** Circuit opening too frequently
```python
# Adjust configuration
config = CircuitBreakerConfig(
    failure_threshold=10,  # Increase threshold
    timeout=120.0,         # Longer timeout
    failure_rate_threshold=0.7  # Higher rate needed
)
breaker = CircuitBreaker("service", config)
```

## Best Practices

### Backup Strategy
1. Run daily automated backups
2. Keep at least 7 days of backups
3. Test restore procedures monthly
4. Monitor backup logs regularly
5. Store backups on separate storage if possible

### Service Management
1. Use systemd for process management
2. Monitor service health regularly
3. Set appropriate resource limits
4. Review logs for errors
5. Plan for graceful shutdowns

### Circuit Breaker Usage
1. Wrap all external API calls
2. Configure appropriate thresholds
3. Implement fallback mechanisms
4. Monitor circuit breaker states
5. Log state transitions
6. Set up alerts for open circuits

### Monitoring
1. Check service status daily
2. Review backup logs weekly
3. Test restore procedures monthly
4. Monitor disk usage
5. Track circuit breaker metrics

## Integration Examples

### API Service with Circuit Breaker

```python
from src.core.circuit_breaker import get_circuit_breaker, CircuitBreakerError
import requests

# Create breaker for API
api_breaker = get_circuit_breaker(
    "binance_api",
    config=CircuitBreakerConfig(
        failure_threshold=3,
        timeout=30.0,
        slow_call_threshold=5.0
    )
)

@api_breaker
def call_binance_api(endpoint, params):
    """Call Binance API with circuit breaker protection."""
    response = requests.get(
        f"https://api.binance.com{endpoint}",
        params=params,
        timeout=5.0
    )
    response.raise_for_status()
    return response.json()

# Usage
try:
    data = call_binance_api("/api/v3/ticker/price", {"symbol": "BTCUSDT"})
except CircuitBreakerError:
    # Circuit open - use cached data
    data = get_cached_price("BTCUSDT")
except requests.RequestException as e:
    # Other error - log and handle
    logger.error(f"API call failed: {e}")
    data = None
```

### Database Operations with Backup

```python
from src.database.engine import get_session
import subprocess

def perform_database_migration():
    """Perform database migration with automatic backup."""
    # Backup before migration
    subprocess.run(["./scripts/backup_database.sh"])

    try:
        # Perform migration
        with get_session() as session:
            # ... migration code ...
            session.commit()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        # Can restore from backup if needed
        raise
```

## References

- [systemd Service Documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [logrotate Manual](https://linux.die.net/man/8/logrotate)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [SQLite Backup API](https://www.sqlite.org/backup.html)
- [PostgreSQL Backup Documentation](https://www.postgresql.org/docs/current/backup.html)

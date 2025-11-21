# Backup and Recovery Procedures

## Table of Contents
1. [Backup Strategy](#backup-strategy)
2. [Database Backup](#database-backup)
3. [Configuration Backup](#configuration-backup)
4. [Recovery Procedures](#recovery-procedures)
5. [Disaster Recovery](#disaster-recovery)
6. [Testing and Validation](#testing-and-validation)

## Backup Strategy

### Backup Types

#### Full Backup
- **Frequency**: Daily at 02:00 UTC
- **Retention**: 30 days
- **Contents**: Complete database dump, configuration files, logs
- **Storage**: S3 or equivalent cloud storage

#### Incremental Backup
- **Frequency**: Every 6 hours
- **Retention**: 7 days
- **Contents**: Changed data since last backup
- **Storage**: S3 or equivalent cloud storage

#### Continuous Backup
- **Method**: Database WAL (Write-Ahead Logging) shipping
- **Frequency**: Real-time
- **Retention**: 7 days
- **Purpose**: Point-in-time recovery

### Backup Schedule

```
Daily:
00:00 UTC - Incremental backup (database)
02:00 UTC - Full backup (database + config + logs)
06:00 UTC - Incremental backup (database)
12:00 UTC - Incremental backup (database)
18:00 UTC - Incremental backup (database)

Weekly:
Sunday 03:00 UTC - Full system backup
Sunday 04:00 UTC - Backup verification test
```

### Retention Policy

| Backup Type | Retention Period | Storage Location |
|-------------|------------------|------------------|
| Hourly incremental | 7 days | S3/Standard |
| Daily full | 30 days | S3/Standard |
| Weekly full | 90 days | S3/Glacier |
| Monthly full | 1 year | S3/Deep Archive |

## Database Backup

### PostgreSQL Backup

#### Manual Backup
```bash
# Full database backup
pg_dump -h localhost -U tradingbot -Fc tradingbot > backup_$(date +%Y%m%d_%H%M%S).dump

# Plain SQL format
pg_dump -h localhost -U tradingbot tradingbot > backup_$(date +%Y%m%d_%H%M%S).sql

# Compressed backup
pg_dump -h localhost -U tradingbot tradingbot | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Backup specific tables
pg_dump -h localhost -U tradingbot -t trades -t orders tradingbot > trades_orders_backup.sql

# Directory format (parallel backup)
pg_dump -h localhost -U tradingbot -Fd -j 4 tradingbot -f backup_$(date +%Y%m%d)
```

#### Automated Backup Script
```bash
#!/bin/bash
# /scripts/backup_database.sh

# Configuration
BACKUP_DIR="/backup/database"
DB_NAME="tradingbot"
DB_USER="tradingbot"
DB_HOST="localhost"
S3_BUCKET="s3://tradingbot-backups/database"
RETENTION_DAYS=30

# Create backup directory
mkdir -p $BACKUP_DIR

# Generate backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"

# Perform backup
echo "Starting database backup: $BACKUP_FILE"
pg_dump -h $DB_HOST -U $DB_USER -Fc $DB_NAME > $BACKUP_FILE

# Verify backup
if [ $? -eq 0 ]; then
    echo "Backup successful"

    # Upload to S3
    aws s3 cp $BACKUP_FILE $S3_BUCKET/

    # Remove local backups older than retention period
    find $BACKUP_DIR -name "*.dump" -mtime +$RETENTION_DAYS -delete

    # Send success notification
    echo "Backup completed successfully: $BACKUP_FILE" | \
        mail -s "Database Backup Success" ops@company.com
else
    echo "Backup failed"

    # Send failure notification
    echo "Backup failed for database: $DB_NAME" | \
        mail -s "Database Backup FAILED" ops@company.com

    exit 1
fi
```

#### Continuous Archiving (WAL)
```bash
# Enable WAL archiving in postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /backup/wal/%f && cp %p /backup/wal/%f'
archive_timeout = 300  # Archive every 5 minutes

# Or use WAL-G for cloud storage
archive_command = 'wal-g wal-push %p'
restore_command = 'wal-g wal-fetch %f %p'
```

### Redis Backup

#### RDB Snapshot
```bash
# Manual snapshot
redis-cli SAVE

# Background snapshot
redis-cli BGSAVE

# Configure automatic snapshots in redis.conf
save 900 1      # Save after 900 seconds if at least 1 key changed
save 300 10     # Save after 300 seconds if at least 10 keys changed
save 60 10000   # Save after 60 seconds if at least 10000 keys changed

# Backup RDB file
cp /var/lib/redis/dump.rdb /backup/redis/dump_$(date +%Y%m%d_%H%M%S).rdb
```

#### AOF (Append-Only File)
```bash
# Enable AOF in redis.conf
appendonly yes
appendfilename "appendonly.aof"
appendfsync everysec

# Backup AOF file
cp /var/lib/redis/appendonly.aof /backup/redis/appendonly_$(date +%Y%m%d_%H%M%S).aof
```

## Configuration Backup

### Application Configuration
```bash
#!/bin/bash
# /scripts/backup_config.sh

BACKUP_DIR="/backup/config"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CONFIG_BACKUP="$BACKUP_DIR/config_$TIMESTAMP.tar.gz"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup configuration files
tar -czf $CONFIG_BACKUP \
    .env \
    docker-compose.yml \
    alembic.ini \
    src/core/config.py \
    .taskmaster/ \
    k8s/ \
    scripts/

# Upload to S3
aws s3 cp $CONFIG_BACKUP s3://tradingbot-backups/config/

# Remove old backups
find $BACKUP_DIR -name "config_*.tar.gz" -mtime +90 -delete

echo "Configuration backup completed: $CONFIG_BACKUP"
```

### Secrets Backup
```bash
# NEVER commit secrets to version control
# Store encrypted backups in secure location

#!/bin/bash
# /scripts/backup_secrets.sh

BACKUP_DIR="/backup/secrets"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SECRETS_FILE="$BACKUP_DIR/secrets_$TIMESTAMP.tar.gz.enc"
ENCRYPTION_KEY_FILE="/secure/encryption.key"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup and encrypt secrets
tar -czf - \
    .env \
    /secure/*.pem \
    /secure/*.key | \
    openssl enc -aes-256-cbc -salt -pbkdf2 -pass file:$ENCRYPTION_KEY_FILE > $SECRETS_FILE

# Upload to secure S3 bucket with encryption
aws s3 cp $SECRETS_FILE s3://tradingbot-secrets/backups/ \
    --sse aws:kms \
    --sse-kms-key-id alias/tradingbot-secrets

# Remove old backups
find $BACKUP_DIR -name "secrets_*.tar.gz.enc" -mtime +90 -delete

echo "Secrets backup completed: $SECRETS_FILE"
```

## Recovery Procedures

### Database Recovery

#### Full Database Restore
```bash
# Method 1: From custom format dump
pg_restore -h localhost -U tradingbot -d tradingbot -c backup.dump

# Method 2: From SQL file
psql -h localhost -U tradingbot tradingbot < backup.sql

# Method 3: From compressed SQL
gunzip -c backup.sql.gz | psql -h localhost -U tradingbot tradingbot

# Method 4: From directory format (parallel restore)
pg_restore -h localhost -U tradingbot -d tradingbot -Fd -j 4 backup_directory/
```

#### Point-in-Time Recovery (PITR)
```bash
# Stop PostgreSQL
sudo systemctl stop postgresql

# Restore base backup
cd /var/lib/postgresql/15/main
rm -rf *
tar -xzf /backup/base_backup.tar.gz

# Create recovery.conf or recovery.signal for PostgreSQL 12+
touch recovery.signal

# Configure recovery in postgresql.conf
restore_command = 'cp /backup/wal/%f %p'
recovery_target_time = '2024-01-17 12:00:00'
recovery_target_action = 'promote'

# Start PostgreSQL
sudo systemctl start postgresql

# Verify recovery
psql -h localhost -U tradingbot -d tradingbot -c "SELECT NOW();"
```

#### Selective Table Restore
```bash
# Restore specific tables only
pg_restore -h localhost -U tradingbot -d tradingbot -t trades -t orders backup.dump

# Or from SQL file
psql -h localhost -U tradingbot tradingbot < trades_orders_backup.sql
```

### Redis Recovery

#### RDB Recovery
```bash
# Stop Redis
sudo systemctl stop redis

# Copy RDB file
cp /backup/redis/dump_20240117_120000.rdb /var/lib/redis/dump.rdb

# Set correct permissions
chown redis:redis /var/lib/redis/dump.rdb

# Start Redis
sudo systemctl start redis

# Verify data
redis-cli DBSIZE
```

#### AOF Recovery
```bash
# Stop Redis
sudo systemctl stop redis

# Copy AOF file
cp /backup/redis/appendonly_20240117_120000.aof /var/lib/redis/appendonly.aof

# Check AOF integrity
redis-check-aof --fix /var/lib/redis/appendonly.aof

# Set correct permissions
chown redis:redis /var/lib/redis/appendonly.aof

# Start Redis
sudo systemctl start redis
```

### Configuration Recovery
```bash
#!/bin/bash
# /scripts/restore_config.sh

BACKUP_FILE=$1

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup_file>"
    exit 1
fi

# Extract configuration backup
tar -xzf $BACKUP_FILE

# Verify extracted files
echo "Extracted configuration files:"
ls -la .env docker-compose.yml alembic.ini

# Restart services
docker-compose down
docker-compose up -d

echo "Configuration restored from: $BACKUP_FILE"
```

### Secrets Recovery
```bash
#!/bin/bash
# /scripts/restore_secrets.sh

BACKUP_FILE=$1
ENCRYPTION_KEY_FILE="/secure/encryption.key"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <encrypted_backup_file>"
    exit 1
fi

# Decrypt and extract secrets
openssl enc -aes-256-cbc -d -pbkdf2 -pass file:$ENCRYPTION_KEY_FILE -in $BACKUP_FILE | tar -xzf -

# Set correct permissions
chmod 600 .env
chmod 600 /secure/*.pem
chmod 600 /secure/*.key

echo "Secrets restored from: $BACKUP_FILE"
echo "WARNING: Verify secrets are correct before restarting services"
```

## Disaster Recovery

### Complete System Recovery

#### Recovery Time Objective (RTO): 4 hours
#### Recovery Point Objective (RPO): 6 hours

#### Step-by-Step DR Procedure

```bash
# 1. Provision new infrastructure
# Use Terraform or CloudFormation to recreate infrastructure

# 2. Install base software
sudo apt-get update
sudo apt-get install -y postgresql-15 redis-server docker.io docker-compose

# 3. Restore database
# Download latest backup from S3
aws s3 cp s3://tradingbot-backups/database/tradingbot_latest.dump /tmp/

# Restore database
createdb -U postgres tradingbot
pg_restore -U postgres -d tradingbot /tmp/tradingbot_latest.dump

# 4. Restore Redis
aws s3 cp s3://tradingbot-backups/redis/dump_latest.rdb /tmp/
sudo cp /tmp/dump_latest.rdb /var/lib/redis/dump.rdb
sudo chown redis:redis /var/lib/redis/dump.rdb
sudo systemctl restart redis

# 5. Restore configuration
aws s3 cp s3://tradingbot-backups/config/config_latest.tar.gz /tmp/
tar -xzf /tmp/config_latest.tar.gz -C /app/tradingbot/

# 6. Restore secrets
aws s3 cp s3://tradingbot-secrets/backups/secrets_latest.tar.gz.enc /tmp/
cd /app/tradingbot
../scripts/restore_secrets.sh /tmp/secrets_latest.tar.gz.enc

# 7. Start application
docker-compose up -d

# 8. Verify recovery
curl http://localhost:8000/health
curl http://localhost:8000/ready

# 9. Verify trading functionality
python3 scripts/verify_system.py

# 10. Update DNS/Load Balancer
# Point traffic to new instance

# 11. Monitor for issues
# Watch dashboards and logs for 1 hour
```

### DR Testing Schedule

| Test Type | Frequency | Scope | Success Criteria |
|-----------|-----------|-------|------------------|
| Backup verification | Weekly | Restore to test environment | Successful restore |
| Partial DR | Monthly | Database + config restore | RTO < 2 hours |
| Full DR drill | Quarterly | Complete system recovery | RTO < 4 hours, RPO < 6 hours |
| Failover test | Annually | Switch to DR site | Zero data loss |

## Testing and Validation

### Backup Integrity Testing

#### Automated Backup Verification
```bash
#!/bin/bash
# /scripts/verify_backup.sh

BACKUP_FILE=$1
TEST_DB="tradingbot_test_restore"

# Create test database
createdb -U postgres $TEST_DB

# Attempt restore
pg_restore -U postgres -d $TEST_DB $BACKUP_FILE

if [ $? -eq 0 ]; then
    # Verify table count
    TABLE_COUNT=$(psql -U postgres -d $TEST_DB -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';")

    # Verify row count
    TRADE_COUNT=$(psql -U postgres -d $TEST_DB -t -c "SELECT COUNT(*) FROM trades;")

    echo "Backup verification successful"
    echo "Tables: $TABLE_COUNT"
    echo "Trades: $TRADE_COUNT"

    # Cleanup
    dropdb -U postgres $TEST_DB

    exit 0
else
    echo "Backup verification FAILED"

    # Send alert
    echo "Backup verification failed for: $BACKUP_FILE" | \
        mail -s "BACKUP VERIFICATION FAILED" ops@company.com

    exit 1
fi
```

### Recovery Testing Checklist

```
Pre-Recovery:
- [ ] Backup files accessible
- [ ] Backup integrity verified
- [ ] Recovery environment prepared
- [ ] Team notified of DR test
- [ ] Monitoring enabled

During Recovery:
- [ ] Database restore started
- [ ] Database restore completed
- [ ] Redis restore completed
- [ ] Configuration applied
- [ ] Services started
- [ ] Health checks passing

Post-Recovery:
- [ ] Data integrity verified
- [ ] Trading functionality tested
- [ ] API endpoints responding
- [ ] Exchange connections working
- [ ] Monitoring data flowing
- [ ] Performance acceptable
- [ ] Recovery time documented
- [ ] Issues documented

Final Steps:
- [ ] Cleanup test environment
- [ ] Update runbooks if needed
- [ ] Share results with team
- [ ] Schedule next test
```

### Data Validation Queries

```sql
-- Check record counts
SELECT
    'trades' as table_name, COUNT(*) as record_count FROM trades
UNION ALL
SELECT 'orders', COUNT(*) FROM orders
UNION ALL
SELECT 'positions', COUNT(*) FROM positions;

-- Verify date ranges
SELECT
    MIN(created_at) as oldest_record,
    MAX(created_at) as newest_record
FROM trades;

-- Check for data gaps
SELECT
    date_trunc('hour', created_at) as hour,
    COUNT(*) as trade_count
FROM trades
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;

-- Verify referential integrity
SELECT COUNT(*)
FROM trades t
LEFT JOIN orders o ON t.order_id = o.id
WHERE o.id IS NULL;
```

## Backup Monitoring

### Backup Metrics
```python
# Prometheus metrics for backup monitoring
backup_last_success_timestamp{type="database"} 1705488000
backup_last_duration_seconds{type="database"} 120.5
backup_size_bytes{type="database"} 1073741824
backup_verification_success{type="database"} 1
```

### Backup Alerts
```yaml
# Alert if backup hasn't run in 25 hours
- alert: BackupOverdue
  expr: time() - backup_last_success_timestamp > 90000
  for: 1h
  labels:
    severity: critical
  annotations:
    summary: "Backup overdue"
    description: "Last successful backup was {{ $value | humanizeDuration }} ago"

# Alert if backup failed
- alert: BackupFailed
  expr: backup_verification_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Backup verification failed"
    description: "Backup type: {{ $labels.type }}"
```

## Best Practices

1. **Automate Everything**
   - Use cron jobs for scheduled backups
   - Automate backup verification
   - Automate DR testing

2. **Test Regularly**
   - Verify backups weekly
   - Perform DR drills quarterly
   - Document all test results

3. **Multiple Locations**
   - Store backups in different regions
   - Use different storage tiers
   - Keep offline copies for critical data

4. **Encryption**
   - Encrypt backups at rest
   - Encrypt backups in transit
   - Secure encryption keys properly

5. **Documentation**
   - Document all procedures
   - Keep runbooks updated
   - Record lessons learned

6. **Monitoring**
   - Monitor backup completion
   - Track backup size trends
   - Alert on failures

## Additional Resources

- Deployment Guide: `DEPLOYMENT.md`
- Incident Response: `INCIDENT_RESPONSE.md`
- Monitoring Guide: `MONITORING.md`

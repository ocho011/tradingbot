# Incident Response Manual

## Table of Contents
1. [Emergency Contacts](#emergency-contacts)
2. [Incident Severity Levels](#incident-severity-levels)
3. [Incident Response Procedures](#incident-response-procedures)
4. [Common Issues and Solutions](#common-issues-and-solutions)
5. [Escalation Matrix](#escalation-matrix)
6. [Post-Incident Actions](#post-incident-actions)

## Emergency Contacts

### Primary Contacts
| Role | Name | Contact | Availability |
|------|------|---------|--------------|
| On-Call Engineer | TBD | phone: +XX-XXX-XXXX | 24/7 |
| DevOps Lead | TBD | phone: +XX-XXX-XXXX | 24/7 |
| Engineering Manager | TBD | phone: +XX-XXX-XXXX | Business hours |
| Product Owner | TBD | email: po@company.com | Business hours |

### Secondary Contacts
| Service | Contact | Purpose |
|---------|---------|---------|
| Database Admin | dba@company.com | Database issues |
| Security Team | security@company.com | Security incidents |
| Exchange Support | Binance: support@binance.com<br>Upbit: support@upbit.com | Exchange API issues |
| Infrastructure | infra@company.com | Server/network issues |

### Communication Channels
- **Slack**: `#tradingbot-incidents` (urgent notifications)
- **Email**: `tradingbot-team@company.com`
- **PagerDuty**: `tradingbot-oncall` group
- **Incident Management**: JIRA or similar system

## Incident Severity Levels

### P0 - Critical (Response Time: Immediate)
**Impact**: Complete service outage, financial loss, data corruption

**Examples**:
- Trading bot executing unauthorized trades
- Complete system failure (no trades can be executed)
- Database data loss or corruption
- Security breach or unauthorized access
- Exchange account compromised

**Response**:
- Immediate response required (within 5 minutes)
- Wake up on-call engineer if outside business hours
- Notify management immediately
- Create war room if needed

### P1 - High (Response Time: <15 minutes)
**Impact**: Partial service degradation, significant feature unavailable

**Examples**:
- One exchange connector down (others working)
- Trading strategy malfunction
- Monitoring system failure
- Performance degradation (>50% slower)
- Database replication lag

**Response**:
- On-call engineer response within 15 minutes
- Notify team lead
- Create incident ticket
- Provide status updates every 30 minutes

### P2 - Medium (Response Time: <1 hour)
**Impact**: Minor feature degradation, workaround available

**Examples**:
- Non-critical API endpoints failing
- Delayed alerts or notifications
- Minor data inconsistencies
- Dashboard display issues

**Response**:
- Response within 1 hour during business hours
- Create ticket for tracking
- Schedule fix based on priority
- Update stakeholders at end of day

### P3 - Low (Response Time: <24 hours)
**Impact**: Cosmetic issues, no business impact

**Examples**:
- Documentation issues
- UI glitches
- Non-critical logging errors
- Performance tuning opportunities

**Response**:
- Schedule for next sprint
- Create backlog ticket
- No immediate action required

## Incident Response Procedures

### Step 1: Detection and Assessment (0-5 minutes)
```
1. Identify the incident
   - Alert received from monitoring
   - User report
   - Automated health check failure

2. Assess severity using criteria above

3. Create incident ticket
   - Title: [P0/P1/P2] Brief description
   - Time detected: [timestamp]
   - Detected by: [alert/user/system]
   - Initial symptoms: [description]
```

### Step 2: Initial Response (5-15 minutes)
```
1. Acknowledge the incident
   - Update incident ticket status to "Investigating"
   - Send initial notification to team channel

2. Gather initial information
   - Check monitoring dashboards
   - Review recent logs
   - Check system health endpoints
   - Review recent deployments/changes

3. Implement immediate mitigation if possible
   - Stop affected services if needed
   - Enable circuit breakers
   - Switch to backup systems
   - Disable problematic features
```

### Step 3: Investigation and Diagnosis (15-60 minutes)
```
1. Deep dive into root cause
   - Review application logs
   - Check database queries and performance
   - Analyze exchange API responses
   - Review recent code changes
   - Check infrastructure metrics

2. Document findings
   - Update incident ticket with findings
   - Share relevant log excerpts
   - Screenshot error messages
   - List affected components

3. Form hypothesis
   - Identify likely root cause
   - List potential solutions
   - Assess risk of each solution
```

### Step 4: Resolution (Variable time)
```
1. Implement fix
   - Apply hotfix if needed
   - Deploy configuration changes
   - Restart affected services
   - Run database migrations if needed

2. Verify resolution
   - Check health endpoints
   - Monitor for error recurrence
   - Verify trading functionality
   - Test affected features

3. Monitor for stability
   - Observe for 30-60 minutes
   - Check metrics returning to normal
   - Verify no new issues introduced
```

### Step 5: Recovery and Verification (30-60 minutes)
```
1. Confirm full service restoration
   - All health checks passing
   - Trading operating normally
   - No error spikes in logs
   - Performance metrics normal

2. Communication
   - Update incident ticket to "Resolved"
   - Notify stakeholders of resolution
   - Post-mortem scheduled if P0/P1

3. Document resolution
   - Record exact fix applied
   - Note time to resolution
   - List any temporary workarounds
```

## Common Issues and Solutions

### 1. Application Won't Start

**Symptoms**:
- Container/process fails to start
- Health check endpoint unreachable
- "Connection refused" errors

**Common Causes and Solutions**:

```bash
# Cause: Database connection failure
# Solution: Check DATABASE_URL and database availability
python3 -c "from src.database.engine import engine; engine.connect()"
docker-compose ps postgresql
docker-compose logs postgresql

# Cause: Port already in use
# Solution: Find and kill process or change port
lsof -i :8000
kill -9 <PID>
# or change API_PORT in .env

# Cause: Missing environment variables
# Solution: Verify .env file exists and contains required vars
grep -E "DATABASE_URL|REDIS_URL|BINANCE_API_KEY" .env

# Cause: Redis connection failure
# Solution: Check Redis availability
redis-cli ping
docker-compose ps redis
```

### 2. Trading Bot Not Executing Trades

**Symptoms**:
- No trades in database
- Strategy signals generated but not executed
- Exchange API errors in logs

**Common Causes and Solutions**:

```bash
# Cause: Insufficient account balance
# Solution: Check account balances
python3 scripts/check_balances.py

# Cause: Exchange API errors
# Solution: Check API connectivity and permissions
python3 scripts/test_exchanges.py
# Verify API keys haven't expired
# Check IP whitelist on exchange

# Cause: Trading mode disabled
# Solution: Check configuration
grep ENABLE_AUTO_TRADING .env
# Should be: ENABLE_AUTO_TRADING=true for live trading

# Cause: Risk management limits exceeded
# Solution: Review risk settings
grep -E "MAX_POSITION_SIZE|RISK_PER_TRADE" .env
# Check current positions don't exceed limits

# Cause: Circuit breaker triggered
# Solution: Check circuit breaker status
curl http://localhost:8000/api/status | jq '.circuit_breakers'
# Reset if needed (only after confirming issue resolved)
```

### 3. Database Performance Issues

**Symptoms**:
- Slow query responses
- Database connection pool exhausted
- Timeout errors

**Common Causes and Solutions**:

```bash
# Cause: Long-running queries
# Solution: Identify and optimize slow queries
docker exec -it tradingbot-db psql -U tradingbot -c "
SELECT pid, now() - pg_stat_activity.query_start AS duration, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - pg_stat_activity.query_start > interval '5 seconds'
ORDER BY duration DESC;
"

# Cause: Missing indexes
# Solution: Analyze and create indexes
docker exec -it tradingbot-db psql -U tradingbot -c "
SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
"
# Review PERFORMANCE_TUNING.md for index recommendations

# Cause: Connection pool exhausted
# Solution: Increase pool size or find connection leaks
grep DB_POOL_SIZE .env
# Increase if needed (default: 20, try 30-40)
# Check for unclosed connections in code

# Cause: Database disk full
# Solution: Clear old data or increase storage
docker exec tradingbot-db df -h
# Clean up old trades if needed
docker exec -it tradingbot-db psql -U tradingbot -c "
DELETE FROM trades WHERE created_at < NOW() - INTERVAL '90 days';
VACUUM FULL trades;
"
```

### 4. Exchange Connection Failures

**Symptoms**:
- "Connection timeout" errors
- "Invalid API key" errors
- Rate limit exceeded

**Common Causes and Solutions**:

```bash
# Cause: API key expired or invalid
# Solution: Verify and rotate API keys
python3 scripts/verify_api_keys.py
# Generate new keys from exchange if needed
# Update .env with new keys
# Restart application

# Cause: IP not whitelisted
# Solution: Add current IP to exchange whitelist
# 1. Get current public IP
curl ifconfig.me
# 2. Add IP to exchange API key whitelist
# 3. Wait 5 minutes for changes to propagate

# Cause: Rate limiting
# Solution: Implement backoff and reduce request frequency
# Check current rate limit status
curl http://localhost:8000/api/exchange-status
# Adjust REQUEST_RATE in configuration if needed
# Review and optimize API call patterns

# Cause: Exchange maintenance
# Solution: Check exchange status
# Binance: https://www.binance.com/en/support/announcement
# Upbit: https://upbit.com/service_center/notice
# Enable fallback exchange if available
# Notify stakeholders of expected downtime
```

### 5. Memory Leaks

**Symptoms**:
- Gradually increasing memory usage
- Out of memory errors
- Container restarts

**Common Causes and Solutions**:

```bash
# Identify memory usage
docker stats tradingbot

# Check for memory leaks in Python
# Install memory_profiler if not already installed
pip install memory-profiler

# Profile specific function
python3 -m memory_profiler scripts/diagnose_memory.py

# Common fixes:
# 1. Clear caches periodically
# 2. Close database connections properly
# 3. Limit in-memory data structures
# 4. Review DataFrame usage in pandas
# 5. Implement pagination for large queries

# Temporary fix: Restart service
docker-compose restart tradingbot
```

### 6. High CPU Usage

**Symptoms**:
- CPU usage consistently >80%
- Slow API responses
- Delayed trade execution

**Common Causes and Solutions**:

```bash
# Check CPU usage
docker stats tradingbot

# Profile CPU usage
python3 -m cProfile -o profile.stats scripts/diagnose_cpu.py
python3 -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative'); p.print_stats(20)"

# Common fixes:
# 1. Optimize hot code paths
# 2. Reduce unnecessary calculations
# 3. Implement caching
# 4. Use async/await properly
# 5. Review trading strategy logic

# Immediate mitigation:
# Reduce number of active strategies
# Increase worker processes (if CPU has available cores)
# Scale horizontally (add more instances)
```

### 7. Logging Issues

**Symptoms**:
- No logs being generated
- Log file too large
- Logs not being shipped to central system

**Common Causes and Solutions**:

```bash
# Check log configuration
grep -E "LOG_LEVEL|JSON_LOGS|STRUCTURED_LOGGING" .env

# Check log file size
ls -lh /var/log/tradingbot/

# Rotate logs if too large
docker-compose exec tradingbot logrotate /etc/logrotate.conf

# Check log shipping (if using external logging)
# Verify Prometheus/Loki connectivity
curl http://localhost:9090/-/healthy
curl http://localhost:3100/ready

# Fix log level if too verbose
# Update LOG_LEVEL in .env to INFO or WARNING
# Restart services
```

## Escalation Matrix

### Level 1: On-Call Engineer (0-30 minutes)
**Handles**:
- All P2/P3 incidents
- Initial response for P0/P1
- Standard troubleshooting

**Escalate to Level 2 if**:
- Cannot resolve within 30 minutes
- Requires code changes
- Requires infrastructure changes
- Impacts multiple systems

### Level 2: DevOps Lead + Engineering Lead (30-60 minutes)
**Handles**:
- P0/P1 incidents
- Multi-system failures
- Performance optimization
- Infrastructure issues

**Escalate to Level 3 if**:
- Requires architectural changes
- Impacts business operations significantly
- Requires executive decision
- Potential data loss or security breach

### Level 3: Engineering Manager + CTO (>60 minutes)
**Handles**:
- Business-critical decisions
- Resource allocation
- External communications
- Major architectural changes

**Escalate to Level 4 if**:
- Legal or compliance implications
- Requires CEO involvement
- Major financial impact
- Regulatory reporting needed

### Level 4: Executive Team
**Handles**:
- Public communications
- Legal/compliance issues
- Strategic decisions
- Regulatory reporting

## Post-Incident Actions

### Immediate Actions (Within 24 hours)
```
1. Update incident ticket
   - Final status: Resolved/Mitigated
   - Total duration: [time]
   - Business impact: [description]
   - Resolution summary: [description]

2. Communication
   - Send resolution notification to stakeholders
   - Update status page if public-facing
   - Thank responders

3. Collect data
   - Save relevant logs
   - Export metrics/graphs
   - Document timeline
```

### Post-Mortem (P0/P1 within 72 hours)

**Template**:
```markdown
# Post-Mortem: [Incident Title]

## Incident Summary
- **Date**: [YYYY-MM-DD]
- **Duration**: [X hours Y minutes]
- **Severity**: [P0/P1/P2]
- **Impact**: [Description]

## Timeline
- HH:MM - Event 1
- HH:MM - Event 2
- HH:MM - Resolution

## Root Cause
[Detailed description]

## Resolution
[What was done to resolve]

## Action Items
- [ ] Action 1 - Owner: [Name] - Due: [Date]
- [ ] Action 2 - Owner: [Name] - Due: [Date]

## What Went Well
- [Positive aspect 1]
- [Positive aspect 2]

## What Could Be Improved
- [Improvement 1]
- [Improvement 2]

## Lessons Learned
[Key takeaways]
```

### Follow-up Actions
```
1. Implement preventive measures
   - Add monitoring/alerts
   - Update runbooks
   - Improve automation
   - Add tests

2. Documentation updates
   - Update this incident response guide
   - Update deployment documentation
   - Share lessons learned with team

3. Review and improve
   - Conduct blameless post-mortem
   - Update escalation procedures
   - Train team on new procedures
```

## Quick Reference Commands

```bash
# Check system status
docker-compose ps
curl http://localhost:8000/health

# View logs
docker-compose logs -f tradingbot
tail -f /var/log/tradingbot/app.log

# Restart services
docker-compose restart tradingbot
docker-compose restart postgresql redis

# Emergency shutdown
docker-compose down
pkill -f "python3 -m uvicorn"

# Database backup
pg_dump -h localhost -U tradingbot tradingbot > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore database
psql -h localhost -U tradingbot tradingbot < backup.sql
```

## Additional Resources

- Deployment Guide: `DEPLOYMENT.md`
- Performance Tuning: `PERFORMANCE_TUNING.md`
- Monitoring Guide: `MONITORING.md`
- Backup/Recovery: `BACKUP_RECOVERY.md`
- Environment Switch: `TESTNET_MAINNET_SWITCH.md`

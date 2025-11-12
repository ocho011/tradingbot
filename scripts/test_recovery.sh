#!/bin/bash

###############################################################################
# Recovery Testing Script
# Automated testing of backup and restore procedures
###############################################################################

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_LOG="${PROJECT_ROOT}/logs/recovery_test.log"
TEST_DB_PATH="${PROJECT_ROOT}/data/test_recovery.db"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$TEST_LOG"
}

# Status functions
pass_test() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
    log "PASS: $1"
    ((TESTS_PASSED++))
}

fail_test() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    log "FAIL: $1"
    ((TESTS_FAILED++))
}

warn_test() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1"
    log "WARN: $1"
}

# Setup test environment
setup() {
    log "=========================================="
    log "Starting recovery test suite"
    log "=========================================="

    mkdir -p "$(dirname "$TEST_LOG")"
    mkdir -p "${PROJECT_ROOT}/data"
    mkdir -p "${PROJECT_ROOT}/backups"

    # Create test database
    if command -v sqlite3 &> /dev/null; then
        sqlite3 "$TEST_DB_PATH" "CREATE TABLE IF NOT EXISTS test_data (id INTEGER PRIMARY KEY, value TEXT);"
        sqlite3 "$TEST_DB_PATH" "INSERT INTO test_data (value) VALUES ('test_value_1');"
        sqlite3 "$TEST_DB_PATH" "INSERT INTO test_data (value) VALUES ('test_value_2');"
        pass_test "Test database created"
    else
        fail_test "sqlite3 not available"
        return 1
    fi
}

# Test 1: Backup script exists and is executable
test_backup_script_exists() {
    log "Test 1: Checking backup script"

    if [ -f "${SCRIPT_DIR}/backup_database.sh" ]; then
        pass_test "Backup script exists"
    else
        fail_test "Backup script not found"
        return 1
    fi

    if [ -x "${SCRIPT_DIR}/backup_database.sh" ]; then
        pass_test "Backup script is executable"
    else
        warn_test "Backup script not executable (fixing)"
        chmod +x "${SCRIPT_DIR}/backup_database.sh"
    fi
}

# Test 2: Restore script exists and is executable
test_restore_script_exists() {
    log "Test 2: Checking restore script"

    if [ -f "${SCRIPT_DIR}/restore_database.sh" ]; then
        pass_test "Restore script exists"
    else
        fail_test "Restore script not found"
        return 1
    fi

    if [ -x "${SCRIPT_DIR}/restore_database.sh" ]; then
        pass_test "Restore script is executable"
    else
        warn_test "Restore script not executable (fixing)"
        chmod +x "${SCRIPT_DIR}/restore_database.sh"
    fi
}

# Test 3: SQLite backup creation
test_sqlite_backup() {
    log "Test 3: Testing SQLite backup"

    export DATABASE_PATH="$TEST_DB_PATH"
    export BACKUP_DIR="${PROJECT_ROOT}/backups"
    export LOG_FILE="$TEST_LOG"

    # Run backup
    if "${SCRIPT_DIR}/backup_database.sh" >> "$TEST_LOG" 2>&1; then
        pass_test "Backup script executed successfully"
    else
        fail_test "Backup script execution failed"
        return 1
    fi

    # Check if backup was created
    local backup_count=$(find "$BACKUP_DIR" -name "sqlite_backup_*.db.gz" -type f | wc -l)
    if [ "$backup_count" -gt 0 ]; then
        pass_test "Backup file created ($backup_count backups found)"
    else
        fail_test "No backup file created"
        return 1
    fi

    # Test backup integrity
    local latest_backup=$(find "$BACKUP_DIR" -name "sqlite_backup_*.db.gz" -type f -printf "%T@ %p\n" | sort -rn | head -1 | awk '{print $2}')
    if gunzip -t "$latest_backup" 2>/dev/null; then
        pass_test "Backup file integrity verified"
    else
        fail_test "Backup file corrupted"
        return 1
    fi
}

# Test 4: SQLite restore
test_sqlite_restore() {
    log "Test 4: Testing SQLite restore"

    # Modify test database
    sqlite3 "$TEST_DB_PATH" "INSERT INTO test_data (value) VALUES ('modified_value');"

    local row_count_before=$(sqlite3 "$TEST_DB_PATH" "SELECT COUNT(*) FROM test_data;")
    log "Rows before restore: $row_count_before"

    # Find latest backup
    local latest_backup=$(find "${PROJECT_ROOT}/backups" -name "sqlite_backup_*.db.gz" -type f -printf "%T@ %p\n" | sort -rn | head -1 | awk '{print $2}')

    if [ -z "$latest_backup" ]; then
        fail_test "No backup found for restore test"
        return 1
    fi

    # Restore database
    export DATABASE_PATH="$TEST_DB_PATH"
    export BACKUP_DIR="${PROJECT_ROOT}/backups"
    export LOG_FILE="$TEST_LOG"

    if "${SCRIPT_DIR}/restore_database.sh" --type sqlite --file "$latest_backup" -y >> "$TEST_LOG" 2>&1; then
        pass_test "Restore script executed successfully"
    else
        fail_test "Restore script execution failed"
        return 1
    fi

    # Verify restore
    local row_count_after=$(sqlite3 "$TEST_DB_PATH" "SELECT COUNT(*) FROM test_data;")
    log "Rows after restore: $row_count_after"

    if [ "$row_count_after" -lt "$row_count_before" ]; then
        pass_test "Database restored to earlier state (rows: $row_count_before → $row_count_after)"
    else
        fail_test "Database not properly restored"
        return 1
    fi

    # Verify data integrity
    if sqlite3 "$TEST_DB_PATH" "PRAGMA integrity_check;" | grep -q "ok"; then
        pass_test "Restored database integrity check passed"
    else
        fail_test "Restored database integrity check failed"
        return 1
    fi
}

# Test 5: Backup retention
test_backup_retention() {
    log "Test 5: Testing backup retention"

    # Create multiple old backups
    for i in {1..5}; do
        local old_date=$(date -d "$i days ago" +"%Y%m%d_%H%M%S" 2>/dev/null || date -v-${i}d +"%Y%m%d_%H%M%S")
        touch -t $(date -d "$i days ago" +"%Y%m%d%H%M" 2>/dev/null || date -v-${i}d +"%Y%m%d%H%M") \
            "${PROJECT_ROOT}/backups/sqlite_backup_${old_date}_test.db.gz" 2>/dev/null || true
    done

    local backup_count_before=$(find "${PROJECT_ROOT}/backups" -name "*.gz" -type f | wc -l)
    log "Backups before retention: $backup_count_before"

    # Run backup with retention
    export RETENTION_DAYS=3
    export DATABASE_PATH="$TEST_DB_PATH"
    export BACKUP_DIR="${PROJECT_ROOT}/backups"
    export LOG_FILE="$TEST_LOG"

    "${SCRIPT_DIR}/backup_database.sh" >> "$TEST_LOG" 2>&1 || true

    local backup_count_after=$(find "${PROJECT_ROOT}/backups" -name "*.gz" -type f | wc -l)
    log "Backups after retention: $backup_count_after"

    if [ "$backup_count_after" -le "$backup_count_before" ]; then
        pass_test "Backup retention policy applied"
    else
        warn_test "Backup retention may not be working"
    fi
}

# Test 6: Systemd service files
test_systemd_files() {
    log "Test 6: Testing systemd configuration files"

    local service_file="${PROJECT_ROOT}/config/systemd/tradingbot.service"
    local backup_service="${PROJECT_ROOT}/config/systemd/tradingbot-backup.service"
    local backup_timer="${PROJECT_ROOT}/config/systemd/tradingbot-backup.timer"

    if [ -f "$service_file" ]; then
        pass_test "Main service file exists"

        # Check for required fields
        if grep -q "ExecStart=" "$service_file" && grep -q "Restart=" "$service_file"; then
            pass_test "Service file contains required fields"
        else
            fail_test "Service file missing required fields"
        fi
    else
        fail_test "Main service file not found"
    fi

    if [ -f "$backup_service" ]; then
        pass_test "Backup service file exists"
    else
        fail_test "Backup service file not found"
    fi

    if [ -f "$backup_timer" ]; then
        pass_test "Backup timer file exists"

        # Check timer configuration
        if grep -q "OnCalendar=" "$backup_timer"; then
            pass_test "Timer has schedule configured"
        else
            fail_test "Timer missing schedule configuration"
        fi
    else
        fail_test "Backup timer file not found"
    fi
}

# Test 7: Logrotate configuration
test_logrotate_config() {
    log "Test 7: Testing logrotate configuration"

    local logrotate_file="${PROJECT_ROOT}/config/logrotate/tradingbot"

    if [ -f "$logrotate_file" ]; then
        pass_test "Logrotate configuration exists"

        # Check for required directives
        if grep -q "daily\|weekly" "$logrotate_file" && \
           grep -q "rotate" "$logrotate_file" && \
           grep -q "compress" "$logrotate_file"; then
            pass_test "Logrotate config contains required directives"
        else
            fail_test "Logrotate config missing required directives"
        fi
    else
        fail_test "Logrotate configuration not found"
    fi
}

# Test 8: Circuit breaker implementation
test_circuit_breaker() {
    log "Test 8: Testing circuit breaker implementation"

    local cb_file="${PROJECT_ROOT}/src/core/circuit_breaker.py"

    if [ -f "$cb_file" ]; then
        pass_test "Circuit breaker module exists"

        # Check for required classes/functions
        if grep -q "class CircuitBreaker" "$cb_file" && \
           grep -q "class CircuitState" "$cb_file"; then
            pass_test "Circuit breaker contains required classes"
        else
            fail_test "Circuit breaker missing required classes"
        fi
    else
        fail_test "Circuit breaker implementation not found"
    fi
}

# Cleanup
cleanup() {
    log "Cleaning up test environment"

    # Remove test database
    rm -f "$TEST_DB_PATH"

    # Remove test backup files
    find "${PROJECT_ROOT}/backups" -name "*test*.gz" -type f -delete 2>/dev/null || true

    log "Cleanup completed"
}

# Generate test report
generate_report() {
    local total=$((TESTS_PASSED + TESTS_FAILED))
    local pass_rate=0

    if [ $total -gt 0 ]; then
        pass_rate=$((TESTS_PASSED * 100 / total))
    fi

    log "=========================================="
    log "Recovery Test Report"
    log "=========================================="
    log "Total tests: $total"
    log "Passed: $TESTS_PASSED"
    log "Failed: $TESTS_FAILED"
    log "Pass rate: ${pass_rate}%"
    log "=========================================="

    echo ""
    echo "=========================================="
    echo "Recovery Test Summary"
    echo "=========================================="
    echo -e "Total tests: $total"
    echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    echo -e "Pass rate: ${pass_rate}%"
    echo "=========================================="
    echo ""
    echo "Detailed log: $TEST_LOG"

    if [ $TESTS_FAILED -gt 0 ]; then
        exit 1
    fi
}

# Main test execution
main() {
    setup

    test_backup_script_exists
    test_restore_script_exists
    test_sqlite_backup
    test_sqlite_restore
    test_backup_retention
    test_systemd_files
    test_logrotate_config
    test_circuit_breaker

    cleanup
    generate_report
}

# Run tests
main

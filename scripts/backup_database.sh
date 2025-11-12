#!/bin/bash

###############################################################################
# Database Backup Script
# Performs automated daily backups of SQLite and PostgreSQL databases
###############################################################################

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
LOG_FILE="${LOG_FILE:-$PROJECT_ROOT/logs/backup.log}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Source environment variables
if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

log "=========================================="
log "Starting database backup process"
log "=========================================="

# Backup SQLite database
backup_sqlite() {
    local db_path="${DATABASE_PATH:-$PROJECT_ROOT/data/tradingbot.db}"

    if [ ! -f "$db_path" ]; then
        log "WARNING: SQLite database not found at $db_path"
        return 1
    fi

    local backup_file="$BACKUP_DIR/sqlite_backup_${TIMESTAMP}.db"

    log "Backing up SQLite database: $db_path"

    # Create backup using sqlite3 .backup command for consistency
    if command -v sqlite3 &> /dev/null; then
        sqlite3 "$db_path" ".backup '$backup_file'" || error_exit "SQLite backup failed"
    else
        # Fallback to cp if sqlite3 is not available
        cp "$db_path" "$backup_file" || error_exit "SQLite backup copy failed"
    fi

    # Compress backup
    gzip "$backup_file" || error_exit "Backup compression failed"

    log "SQLite backup completed: ${backup_file}.gz"

    # Verify backup integrity
    gunzip -t "${backup_file}.gz" || error_exit "Backup verification failed"
    log "Backup integrity verified"

    echo "${backup_file}.gz"
}

# Backup PostgreSQL database
backup_postgres() {
    local pg_host="${POSTGRES_HOST:-postgres}"
    local pg_port="${POSTGRES_PORT:-5432}"
    local pg_db="${POSTGRES_DB:-tradingbot}"
    local pg_user="${POSTGRES_USER:-tradingbot}"

    if ! command -v pg_dump &> /dev/null; then
        log "WARNING: pg_dump not found, skipping PostgreSQL backup"
        return 1
    fi

    local backup_file="$BACKUP_DIR/postgres_backup_${TIMESTAMP}.sql"

    log "Backing up PostgreSQL database: $pg_db"

    # Check if PostgreSQL is accessible
    if ! pg_isready -h "$pg_host" -p "$pg_port" -U "$pg_user" &> /dev/null; then
        log "WARNING: PostgreSQL is not accessible, skipping backup"
        return 1
    fi

    # Perform backup
    PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
        -h "$pg_host" \
        -p "$pg_port" \
        -U "$pg_user" \
        -d "$pg_db" \
        --format=custom \
        --file="$backup_file" \
        --verbose 2>&1 | tee -a "$LOG_FILE" || error_exit "PostgreSQL backup failed"

    # Compress backup
    gzip "$backup_file" || error_exit "Backup compression failed"

    log "PostgreSQL backup completed: ${backup_file}.gz"

    echo "${backup_file}.gz"
}

# Clean up old backups
cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days"

    find "$BACKUP_DIR" -name "*.gz" -type f -mtime +"$RETENTION_DAYS" -delete

    local remaining=$(find "$BACKUP_DIR" -name "*.gz" -type f | wc -l)
    log "Cleanup completed. Remaining backups: $remaining"
}

# Main backup process
main() {
    local sqlite_backup=""
    local postgres_backup=""

    # Backup SQLite
    if sqlite_backup=$(backup_sqlite); then
        log "SQLite backup successful"
    else
        log "WARNING: SQLite backup failed or skipped"
    fi

    # Backup PostgreSQL
    if postgres_backup=$(backup_postgres); then
        log "PostgreSQL backup successful"
    else
        log "WARNING: PostgreSQL backup failed or skipped"
    fi

    # Cleanup old backups
    cleanup_old_backups

    # Report disk usage
    local disk_usage=$(du -sh "$BACKUP_DIR" | cut -f1)
    log "Total backup directory size: $disk_usage"

    log "=========================================="
    log "Backup process completed successfully"
    log "=========================================="
}

# Run main function
main

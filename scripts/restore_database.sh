#!/bin/bash

###############################################################################
# Database Restore Script
# Restores database from backup with validation
###############################################################################

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups}"
LOG_FILE="${LOG_FILE:-$PROJECT_ROOT/logs/restore.log}"

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

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
    -t, --type TYPE         Database type: sqlite or postgres (required)
    -f, --file FILE         Backup file to restore (optional, uses latest if not specified)
    -y, --yes              Skip confirmation prompt
    -h, --help             Show this help message

Examples:
    $0 --type sqlite
    $0 --type postgres --file backup_20240101_120000.sql.gz
    $0 -t sqlite -y

EOF
    exit 1
}

# List available backups
list_backups() {
    local db_type=$1
    local pattern=""

    case $db_type in
        sqlite)
            pattern="sqlite_backup_*.db.gz"
            ;;
        postgres)
            pattern="postgres_backup_*.sql.gz"
            ;;
        *)
            error_exit "Invalid database type: $db_type"
            ;;
    esac

    log "Available $db_type backups:"
    find "$BACKUP_DIR" -name "$pattern" -type f -printf "%T@ %p\n" | \
        sort -rn | \
        awk '{print NR". "$2" (Modified: "strftime("%Y-%m-%d %H:%M:%S", $1)")"}' | \
        tee -a "$LOG_FILE"
}

# Get latest backup
get_latest_backup() {
    local db_type=$1
    local pattern=""

    case $db_type in
        sqlite)
            pattern="sqlite_backup_*.db.gz"
            ;;
        postgres)
            pattern="postgres_backup_*.sql.gz"
            ;;
    esac

    find "$BACKUP_DIR" -name "$pattern" -type f -printf "%T@ %p\n" | \
        sort -rn | \
        head -1 | \
        awk '{print $2}'
}

# Restore SQLite database
restore_sqlite() {
    local backup_file=$1
    local db_path="${DATABASE_PATH:-$PROJECT_ROOT/data/tradingbot.db}"

    log "Restoring SQLite database from: $backup_file"

    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        error_exit "Backup file not found: $backup_file"
    fi

    gunzip -t "$backup_file" || error_exit "Backup file is corrupted"

    # Backup current database if it exists
    if [ -f "$db_path" ]; then
        local current_backup="${db_path}.pre-restore.$(date +%Y%m%d_%H%M%S)"
        log "Backing up current database to: $current_backup"
        cp "$db_path" "$current_backup"
    fi

    # Extract and restore
    local temp_file="${backup_file%.gz}"
    gunzip -c "$backup_file" > "$temp_file" || error_exit "Failed to extract backup"

    # Move restored database to target location
    mkdir -p "$(dirname "$db_path")"
    mv "$temp_file" "$db_path" || error_exit "Failed to restore database"

    # Verify restored database
    if command -v sqlite3 &> /dev/null; then
        sqlite3 "$db_path" "PRAGMA integrity_check;" || error_exit "Database integrity check failed"
        log "Database integrity verified"
    fi

    log "SQLite database restored successfully"
}

# Restore PostgreSQL database
restore_postgres() {
    local backup_file=$1
    local pg_host="${POSTGRES_HOST:-postgres}"
    local pg_port="${POSTGRES_PORT:-5432}"
    local pg_db="${POSTGRES_DB:-tradingbot}"
    local pg_user="${POSTGRES_USER:-tradingbot}"

    log "Restoring PostgreSQL database from: $backup_file"

    # Verify backup file
    if [ ! -f "$backup_file" ]; then
        error_exit "Backup file not found: $backup_file"
    fi

    gunzip -t "$backup_file" || error_exit "Backup file is corrupted"

    if ! command -v pg_restore &> /dev/null; then
        error_exit "pg_restore not found"
    fi

    # Check PostgreSQL connectivity
    if ! pg_isready -h "$pg_host" -p "$pg_port" -U "$pg_user" &> /dev/null; then
        error_exit "PostgreSQL is not accessible"
    fi

    # Extract backup
    local temp_file="${backup_file%.gz}"
    gunzip -c "$backup_file" > "$temp_file" || error_exit "Failed to extract backup"

    # Drop existing database (warning: destructive!)
    log "WARNING: Dropping existing database $pg_db"
    PGPASSWORD="${POSTGRES_PASSWORD}" dropdb \
        -h "$pg_host" \
        -p "$pg_port" \
        -U "$pg_user" \
        --if-exists \
        "$pg_db" 2>&1 | tee -a "$LOG_FILE"

    # Create fresh database
    log "Creating fresh database $pg_db"
    PGPASSWORD="${POSTGRES_PASSWORD}" createdb \
        -h "$pg_host" \
        -p "$pg_port" \
        -U "$pg_user" \
        "$pg_db" || error_exit "Failed to create database"

    # Restore from backup
    log "Restoring database from backup"
    PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore \
        -h "$pg_host" \
        -p "$pg_port" \
        -U "$pg_user" \
        -d "$pg_db" \
        --verbose \
        "$temp_file" 2>&1 | tee -a "$LOG_FILE" || error_exit "Database restore failed"

    # Cleanup temporary file
    rm -f "$temp_file"

    log "PostgreSQL database restored successfully"
}

# Main restore process
main() {
    local db_type=""
    local backup_file=""
    local skip_confirm=false

    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -t|--type)
                db_type="$2"
                shift 2
                ;;
            -f|--file)
                backup_file="$2"
                shift 2
                ;;
            -y|--yes)
                skip_confirm=true
                shift
                ;;
            -h|--help)
                usage
                ;;
            *)
                error_exit "Unknown option: $1"
                ;;
        esac
    done

    # Validate required arguments
    if [ -z "$db_type" ]; then
        usage
    fi

    # Create log directory
    mkdir -p "$(dirname "$LOG_FILE")"

    log "=========================================="
    log "Starting database restore process"
    log "Database type: $db_type"
    log "=========================================="

    # Get backup file if not specified
    if [ -z "$backup_file" ]; then
        backup_file=$(get_latest_backup "$db_type")
        if [ -z "$backup_file" ]; then
            error_exit "No backup files found for $db_type"
        fi
        log "Using latest backup: $backup_file"
    else
        # If relative path, prepend backup directory
        if [[ ! "$backup_file" = /* ]]; then
            backup_file="$BACKUP_DIR/$backup_file"
        fi
    fi

    # List available backups
    list_backups "$db_type"

    # Confirmation prompt
    if [ "$skip_confirm" = false ]; then
        echo ""
        read -p "WARNING: This will replace the current database. Continue? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            log "Restore cancelled by user"
            exit 0
        fi
    fi

    # Perform restore based on database type
    case $db_type in
        sqlite)
            restore_sqlite "$backup_file"
            ;;
        postgres)
            restore_postgres "$backup_file"
            ;;
        *)
            error_exit "Invalid database type: $db_type"
            ;;
    esac

    log "=========================================="
    log "Restore process completed successfully"
    log "=========================================="
}

# Run main function
main "$@"

#!/bin/bash
# =============================================================================
# Docker Entrypoint Script for Trading Bot
# =============================================================================
# This script is the entrypoint for the Docker container and handles:
# - Environment validation
# - Directory setup and permissions
# - Database migrations
# - Application startup
# =============================================================================

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions for logging
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# =============================================================================
# Environment Validation
# =============================================================================
validate_environment() {
    log_info "Validating environment variables..."

    # Check for required API keys
    if [ -z "$BINANCE_API_KEY" ] && [ -z "$BINANCE_TESTNET_API_KEY" ] && [ -z "$BINANCE_MAINNET_API_KEY" ]; then
        log_error "No Binance API key found!"
        log_error "Please set one of: BINANCE_API_KEY, BINANCE_TESTNET_API_KEY, or BINANCE_MAINNET_API_KEY"
        exit 1
    fi

    if [ -z "$BINANCE_SECRET_KEY" ] && [ -z "$BINANCE_TESTNET_SECRET_KEY" ] && [ -z "$BINANCE_MAINNET_SECRET_KEY" ]; then
        log_error "No Binance secret key found!"
        log_error "Please set one of: BINANCE_SECRET_KEY, BINANCE_TESTNET_SECRET_KEY, or BINANCE_MAINNET_SECRET_KEY"
        exit 1
    fi

    # Display configuration
    log_info "Configuration:"
    log_info "  - Trading Mode: ${TRADING_MODE:-paper}"
    log_info "  - Testnet: ${BINANCE_TESTNET:-true}"
    log_info "  - API Port: ${API_PORT:-8000}"
    log_info "  - Log Level: ${LOG_LEVEL:-INFO}"
    log_info "  - Database: ${DATABASE_PATH:-data/tradingbot.db}"

    log_success "Environment validation passed"
}

# =============================================================================
# Directory Setup
# =============================================================================
setup_directories() {
    log_info "Setting up directories..."

    # Create required directories if they don't exist
    mkdir -p /app/data
    mkdir -p /app/logs
    mkdir -p /app/config

    # Ensure proper permissions (should already be owned by tradingbot user)
    # This is a safety check in case volumes are mounted with incorrect permissions
    if [ -w /app/data ]; then
        log_success "Data directory is writable"
    else
        log_warning "Data directory may not be writable, database operations may fail"
    fi

    if [ -w /app/logs ]; then
        log_success "Logs directory is writable"
    else
        log_warning "Logs directory may not be writable, logging may fail"
    fi

    log_success "Directory setup complete"
}

# =============================================================================
# Database Migration
# =============================================================================
run_migrations() {
    log_info "Checking database migrations..."

    # Check if Alembic is configured
    if [ -f "/app/alembic.ini" ]; then
        log_info "Running Alembic migrations..."

        # Run migrations
        if alembic upgrade head; then
            log_success "Database migrations completed successfully"
        else
            log_error "Database migration failed"
            # Don't exit - allow app to start even if migrations fail
            # The app will handle database initialization
            log_warning "Continuing with application startup..."
        fi
    else
        log_info "No Alembic configuration found, skipping migrations"
        log_info "Database will be initialized by the application"
    fi
}

# =============================================================================
# Health Check
# =============================================================================
wait_for_dependencies() {
    log_info "Waiting for dependent services..."

    # Wait for Redis (if REDIS_HOST is set)
    if [ -n "$REDIS_HOST" ]; then
        log_info "Waiting for Redis at ${REDIS_HOST}:${REDIS_PORT:-6379}..."
        timeout=30
        while [ $timeout -gt 0 ]; do
            if nc -z "${REDIS_HOST}" "${REDIS_PORT:-6379}" 2>/dev/null; then
                log_success "Redis is ready"
                break
            fi
            timeout=$((timeout - 1))
            sleep 1
        done

        if [ $timeout -eq 0 ]; then
            log_warning "Redis connection timeout, continuing anyway..."
        fi
    fi

    # Wait for PostgreSQL (if POSTGRES_HOST is set)
    if [ -n "$POSTGRES_HOST" ]; then
        log_info "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
        timeout=30
        while [ $timeout -gt 0 ]; do
            if nc -z "${POSTGRES_HOST}" "${POSTGRES_PORT:-5432}" 2>/dev/null; then
                log_success "PostgreSQL is ready"
                break
            fi
            timeout=$((timeout - 1))
            sleep 1
        done

        if [ $timeout -eq 0 ]; then
            log_warning "PostgreSQL connection timeout, continuing anyway..."
        fi
    fi
}

# =============================================================================
# Main Startup Sequence
# =============================================================================
main() {
    echo "========================================================================"
    echo "  Trading Bot - Docker Container Startup"
    echo "========================================================================"
    echo ""

    # 1. Validate environment
    validate_environment

    # 2. Setup directories
    setup_directories

    # 3. Wait for dependencies
    wait_for_dependencies

    # 4. Run database migrations
    run_migrations

    echo ""
    echo "========================================================================"
    log_success "Initialization complete - Starting application..."
    echo "========================================================================"
    echo ""

    # Execute the main command
    exec "$@"
}

# Run main function with all script arguments
main "$@"

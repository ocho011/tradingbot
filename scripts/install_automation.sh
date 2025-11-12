#!/bin/bash

###############################################################################
# Automation System Installation Script
# Installs systemd services, backup automation, and monitoring
###############################################################################

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_USER="${INSTALL_USER:-tradingbot}"
INSTALL_DIR="${INSTALL_DIR:-/opt/tradingbot}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Usage: sudo $0"
    exit 1
fi

log() {
    echo -e "${GREEN}==>${NC} $1"
}

warn() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

error() {
    echo -e "${RED}Error:${NC} $1"
    exit 1
}

# Create user if doesn't exist
create_user() {
    if id "$INSTALL_USER" &>/dev/null; then
        log "User $INSTALL_USER already exists"
    else
        log "Creating user $INSTALL_USER"
        useradd -r -s /bin/bash -d "$INSTALL_DIR" -m "$INSTALL_USER"
    fi
}

# Copy files to installation directory
copy_files() {
    log "Copying files to $INSTALL_DIR"

    # Create directory structure
    mkdir -p "$INSTALL_DIR"/{data,logs,backups,config,scripts}

    # Copy project files
    rsync -av --exclude='venv' --exclude='.git' --exclude='__pycache__' \
        "$PROJECT_ROOT/" "$INSTALL_DIR/" || error "Failed to copy files"

    # Set ownership
    chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR"

    # Make scripts executable
    chmod +x "$INSTALL_DIR/scripts"/*.sh
}

# Install systemd services
install_systemd() {
    log "Installing systemd services"

    # Copy service files
    cp "$INSTALL_DIR/config/systemd/tradingbot.service" /etc/systemd/system/
    cp "$INSTALL_DIR/config/systemd/tradingbot-backup.service" /etc/systemd/system/
    cp "$INSTALL_DIR/config/systemd/tradingbot-backup.timer" /etc/systemd/system/

    # Update paths in service files
    sed -i "s|/opt/tradingbot|$INSTALL_DIR|g" /etc/systemd/system/tradingbot*.service

    # Reload systemd
    systemctl daemon-reload

    log "Systemd services installed"
}

# Install logrotate configuration
install_logrotate() {
    log "Installing logrotate configuration"

    # Copy logrotate config
    cp "$INSTALL_DIR/config/logrotate/tradingbot" /etc/logrotate.d/tradingbot

    # Update paths
    sed -i "s|/opt/tradingbot|$INSTALL_DIR|g" /etc/logrotate.d/tradingbot
    sed -i "s|tradingbot tradingbot|$INSTALL_USER $INSTALL_USER|g" /etc/logrotate.d/tradingbot

    # Test configuration
    if logrotate -d /etc/logrotate.d/tradingbot &>/dev/null; then
        log "Logrotate configuration validated"
    else
        warn "Logrotate configuration validation failed"
    fi
}

# Setup cron job for backup (alternative to systemd timer)
setup_cron() {
    log "Setting up cron job for backups"

    local cron_entry="0 2 * * * $INSTALL_DIR/scripts/backup_database.sh >> $INSTALL_DIR/logs/backup.log 2>&1"

    # Check if cron entry exists
    if crontab -u "$INSTALL_USER" -l 2>/dev/null | grep -q "backup_database.sh"; then
        log "Cron job already exists"
    else
        # Add cron job
        (crontab -u "$INSTALL_USER" -l 2>/dev/null; echo "$cron_entry") | crontab -u "$INSTALL_USER" -
        log "Cron job added"
    fi
}

# Setup Python virtual environment
setup_venv() {
    log "Setting up Python virtual environment"

    if [ ! -d "$INSTALL_DIR/venv" ]; then
        sudo -u "$INSTALL_USER" python3 -m venv "$INSTALL_DIR/venv"
        log "Virtual environment created"
    fi

    # Install dependencies
    if [ -f "$INSTALL_DIR/pyproject.toml" ]; then
        sudo -u "$INSTALL_USER" "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR" || warn "Failed to install dependencies"
    fi
}

# Setup environment file
setup_env() {
    log "Setting up environment file"

    if [ ! -f "$INSTALL_DIR/.env" ]; then
        if [ -f "$INSTALL_DIR/.env.example" ]; then
            cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
            chown "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR/.env"
            chmod 600 "$INSTALL_DIR/.env"
            warn "Created .env from example - please configure API keys"
        else
            warn "No .env.example found"
        fi
    else
        log "Environment file already exists"
    fi
}

# Enable and start services
enable_services() {
    log "Enabling services"

    # Enable main service
    systemctl enable tradingbot.service

    # Enable backup timer
    systemctl enable tradingbot-backup.timer
    systemctl start tradingbot-backup.timer

    log "Services enabled"
    log "Use 'systemctl start tradingbot' to start the main service"
}

# Run tests
run_tests() {
    log "Running recovery tests"

    if sudo -u "$INSTALL_USER" "$INSTALL_DIR/scripts/test_recovery.sh"; then
        log "Recovery tests passed"
    else
        warn "Some recovery tests failed - check logs"
    fi
}

# Display status
show_status() {
    echo ""
    echo "=========================================="
    echo "Installation Complete"
    echo "=========================================="
    echo ""
    echo "Installation directory: $INSTALL_DIR"
    echo "User: $INSTALL_USER"
    echo ""
    echo "Services:"
    echo "  - tradingbot.service (main application)"
    echo "  - tradingbot-backup.timer (daily backups)"
    echo ""
    echo "Configuration files:"
    echo "  - Environment: $INSTALL_DIR/.env"
    echo "  - Systemd: /etc/systemd/system/tradingbot*.service"
    echo "  - Logrotate: /etc/logrotate.d/tradingbot"
    echo ""
    echo "Useful commands:"
    echo "  Start service:     systemctl start tradingbot"
    echo "  Stop service:      systemctl stop tradingbot"
    echo "  Service status:    systemctl status tradingbot"
    echo "  View logs:         journalctl -u tradingbot -f"
    echo "  Backup status:     systemctl list-timers tradingbot-backup.timer"
    echo "  Manual backup:     systemctl start tradingbot-backup.service"
    echo "  Run tests:         $INSTALL_DIR/scripts/test_recovery.sh"
    echo ""
    echo "Next steps:"
    echo "  1. Configure API keys in $INSTALL_DIR/.env"
    echo "  2. Review and customize configuration files"
    echo "  3. Start the service: systemctl start tradingbot"
    echo "  4. Monitor logs: journalctl -u tradingbot -f"
    echo ""
    echo "=========================================="
}

# Main installation
main() {
    log "Starting automation system installation"
    log "Target directory: $INSTALL_DIR"
    log "User: $INSTALL_USER"

    create_user
    copy_files
    setup_venv
    setup_env
    install_systemd
    install_logrotate
    setup_cron
    enable_services
    run_tests
    show_status

    log "Installation completed successfully"
}

# Show usage
usage() {
    cat << EOF
Usage: sudo $0 [OPTIONS]

Options:
    --user USER         Installation user (default: tradingbot)
    --dir DIR          Installation directory (default: /opt/tradingbot)
    --skip-tests       Skip recovery tests
    --help             Show this help message

Example:
    sudo $0 --user myuser --dir /home/myuser/tradingbot

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --user)
            INSTALL_USER="$2"
            shift 2
            ;;
        --dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            ;;
    esac
done

# Run main installation
main

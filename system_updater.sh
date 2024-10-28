#!/bin/bash

# Configuration
REPO_URL="https://github.com/eishan05/necris.git"
GITHUB_TOKEN="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"
INSTALL_DIR="/home/necris-user/necris"
BACKUP_DIR="/home/necris-user/necris-backup"
LOG_FILE="/var/log/necris-nas-update.log"

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to clean up temporary files and old backups
cleanup() {
    log_message "Cleaning up temporary files..."
    rm -rf "$BACKUP_DIR"
    # Remove logs older than 7 days
    find /var/log -name "necris-nas-update.log.*" -mtime +7 -delete
}

# Function to handle errors
handle_error() {
    local error_message="$1"
    log_message "ERROR: $error_message"
    
    if [ -d "$BACKUP_DIR" ]; then
        log_message "Restoring from backup..."
        systemctl stop necris-nas
        rm -rf "$INSTALL_DIR"/*
        cp -r "$BACKUP_DIR"/* "$INSTALL_DIR"/
        systemctl start necris-nas
        cleanup
    fi
    
    exit 1
}

# Function to check if this is a fresh installation
check_installation_status() {
    # Check if service unit file exists
    if [ ! -f "/etc/systemd/system/necris-nas.service" ]; then
        log_message "Service unit file not found - fresh installation"
        return 0
    fi
    
    # Check if service is enabled
    if ! systemctl is-enabled --quiet necris-nas 2>/dev/null; then
        log_message "Service not enabled - fresh installation"
        return 0
    fi
    
    log_message "Existing installation detected"
    return 1
}

# Function to setup git configuration
setup_git_config() {
    # Configure git to allow root to operate on the repository
    git config --system --add safe.directory "$INSTALL_DIR"
    
    # Configure git credentials
    git config --system credential.helper store
    echo "https://oauth2:${GITHUB_TOKEN}@github.com" > /root/.git-credentials
    chmod 600 /root/.git-credentials
    
    # Set git user info for root
    git config --system user.email "root@necris-nas.local"
    git config --system user.name "Necris NAS System"
}

# Create log file if it doesn't exist
touch "$LOG_FILE"

# Rotate log file if it exceeds 10MB
if [ -f "$LOG_FILE" ]; then
    FILE_SIZE=$(stat -c%s "$LOG_FILE")
    if [ "$FILE_SIZE" -gt 10485760 ]; then
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d)"
    fi
fi

# Main update process
main() {
    log_message "Starting update process"
    
    # Check if update is already running
    if [ -f /tmp/necris-update.lock ]; then
        log_message "Update already in progress. Exiting."
        exit 0
    fi
    
    # Create lock file
    touch /tmp/necris-update.lock
    trap 'rm -f /tmp/necris-update.lock' EXIT
    
    # Ensure required directories exist
    mkdir -p "$INSTALL_DIR"

    # Setup git configuration
    setup_git_config
    
    # Check if this is a fresh installation
    check_installation_status
    IS_FRESH_INSTALL=$?
    
    # Create backup of current installation if it's an update
    if [ "$IS_FRESH_INSTALL" -eq 1 ] && [ -d "$INSTALL_DIR" ] && [ "$(ls -A $INSTALL_DIR)" ]; then
        log_message "Creating backup..."
        mkdir -p "$BACKUP_DIR"
        cp -r "$INSTALL_DIR"/* "$BACKUP_DIR"/ || handle_error "Failed to create backup"
    fi
    
    # Configure git credentials
    git config --global credential.helper store
    echo "https://oauth2:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials
    
    # Clone/pull latest changes
    if [ ! -d "$INSTALL_DIR/.git" ]; then
        log_message "Stashing any local changes..."
        git stash || handle_error "Failed to stash local changes"
        log_message "Performing initial clone..."
        git clone "https://oauth2:${GITHUB_TOKEN}@${REPO_URL#https://}" "$INSTALL_DIR" || handle_error "Failed to clone repository"
        cd "$INSTALL_DIR" || handle_error "Failed to change to install directory"
    else
        cd "$INSTALL_DIR" || handle_error "Failed to change to install directory"
        log_message "Checking for updates..."
        CURRENT_HASH=$(git rev-parse HEAD)
        git fetch origin || handle_error "Failed to fetch updates"
        REMOTE_HASH=$(git rev-parse origin/main)
        
        if [ "$CURRENT_HASH" = "$REMOTE_HASH" ]; then
            log_message "Already up to date"
            cleanup
            exit 0
        fi
        
        git pull origin main || handle_error "Failed to pull updates"
    fi
    
    # Stop the service before updates if it's running and not a fresh install
    if [ "$IS_FRESH_INSTALL" -eq 1 ]; then
        if systemctl is-active --quiet necris-nas; then
            log_message "Stopping necris-nas service for update..."
            systemctl stop necris-nas
        fi
    fi
    
    # Update dependencies if setup.sh exists
    if [ -f "$INSTALL_DIR/setup.sh" ]; then
        log_message "Running setup script..."
        if [ "$IS_FRESH_INSTALL" -eq 0 ]; then
            # For fresh install, let setup.sh handle everything
            log_message "Fresh install: letting setup.sh handle service installation and start"
            bash "$INSTALL_DIR/setup.sh" || handle_error "Failed to run setup script"
        else
            # For updates, skip service management in setup.sh
            log_message "Update: running setup.sh with service management disabled"
            bash "$INSTALL_DIR/setup.sh" true || handle_error "Failed to run setup script"
            # Start the service after setup
            log_message "Starting necris-nas service..."
            systemctl start necris-nas || handle_error "Failed to start service"
        fi
    fi
    
    # Verify service is running
    sleep 5
    if ! systemctl is-active --quiet necris-nas; then
        handle_error "Service failed to start after update"
    fi
    
    # Cleanup
    cleanup
    log_message "Update completed successfully"
}

# Run main function
main
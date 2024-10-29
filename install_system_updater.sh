#!/bin/bash

# Get the absolute path of the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
UPDATER_SCRIPT="$SCRIPT_DIR/system_updater.sh"

# Function to log installation steps
log_step() {
    echo "===> $1"
}

# Function to handle errors
handle_error() {
    echo "ERROR: $1"
    exit 1
}

# Check if system_updater.sh exists
if [ ! -f "$UPDATER_SCRIPT" ]; then
    handle_error "system_updater.sh not found in the current directory"
fi

# Make system_updater.sh executable
log_step "Making system_updater.sh executable"
chmod +x "$UPDATER_SCRIPT" || handle_error "Failed to make system_updater.sh executable"

# Create systemd service file
log_step "Creating systemd service file"
cat << EOF | sudo tee /etc/systemd/system/necris-updater.service > /dev/null
[Unit]
Description=Necris NAS System Updater
After=network.target

[Service]
Type=oneshot
Environment="HOME=/root"
ExecStart=/bin/bash $UPDATER_SCRIPT
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create systemd timer file
log_step "Creating systemd timer file"
cat << EOF | sudo tee /etc/systemd/system/necris-updater.timer > /dev/null
[Unit]
Description=Run Necris NAS System Updater periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Unit=necris-updater.service
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Configure git to handle root repository access
log_step "Configuring git for root access"
sudo git config --system --add safe.directory '*' || handle_error "Failed to configure git"

# Reload systemd daemon
log_step "Reloading systemd daemon"
sudo systemctl daemon-reload || handle_error "Failed to reload systemd daemon"

# Stop any running instances
log_step "Stopping any running instances"
sudo systemctl stop necris-updater.service 2>/dev/null
sudo systemctl stop necris-updater.timer 2>/dev/null

# Enable and start timer (which will trigger the service)
log_step "Enabling and starting the updater timer"
sudo systemctl enable necris-updater.timer || handle_error "Failed to enable updater timer"
sudo systemctl start necris-updater.timer || handle_error "Failed to start updater timer"

# Run the updater once immediately
log_step "Running initial update"
sudo systemctl start necris-updater.service || handle_error "Failed to start initial update"

# Check status
log_step "Checking service and timer status"
echo -e "\nTimer status:"
sudo systemctl status necris-updater.timer --no-pager
echo -e "\nService status:"
sudo systemctl status necris-updater.service --no-pager

# Show next scheduled run
log_step "Next scheduled runs:"
sudo systemctl list-timers | grep necris-updater

log_step "Installation completed successfully!"
echo "The system updater will run:"
echo "  - 5 minutes after each boot"
echo "  - Every hour after its last run"
echo "You can manually trigger an update with: sudo systemctl start necris-updater"
echo "You can check the update logs with: sudo journalctl -u necris-updater"
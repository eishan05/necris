#!/bin/bash

# Update package lists
sudo apt update

# Install required packages
sudo apt install -y avahi-daemon
sudo apt install -y python3-flask
sudo apt install -y python3-werkzeug
sudo apt install -y python3-watchdog
sudo apt install -y python3-pyudev
sudo apt install -y python3-psutil
sudo apt install -y ntfs-3g exfat-fuse lsof
sudo apt install -y samba

# Make orchestrator executable
sudo chmod +x orchestrator.py

# Get the absolute path of the orchestrator script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ORCHESTRATOR_PATH="$SCRIPT_DIR/orchestrator.py"

# Create systemd service file
cat << EOF | sudo tee /etc/systemd/system/necris-nas.service
[Unit]
Description=Necris NAS Server
After=network.target samba.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 ${ORCHESTRATOR_PATH}
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable and start the service
sudo systemctl enable necris-nas
sudo systemctl start necris-nas

# Print status
echo "Setup complete! Necris NAS server service has been installed and started."
echo "You can check the status with: sudo systemctl status necris-nas"
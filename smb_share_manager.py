#!/usr/bin/env python3

import os
import subprocess
import logging
import time
import pwd
import grp
from pathlib import Path
import configparser
import psutil
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SMBShareManager:
    def __init__(self):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filename='/var/log/smb_share_manager.log'
        )
        self.logger = logging.getLogger(__name__)
        
        # Set default user (same as USB monitor)
        self.user = os.environ.get('SUDO_USER', 'necris-user')
        try:
            self.uid = pwd.getpwnam(self.user).pw_uid
            self.gid = grp.getgrnam(self.user).gr_gid
        except KeyError:
            self.logger.error(f"Could not find user {self.user}")
            raise SystemExit(f"User {self.user} not found in system")
            
        # Base mount directory (same as USB monitor)
        self.mount_base = Path(f'/media/{self.user}')
        
        # Samba configuration
        self.smb_conf_path = '/etc/samba/smb.conf'
        self.shares_conf_path = '/etc/samba/shares.conf'
        self.active_shares = set()
        
        # Initialize
        self.setup_samba_config()
        self.validate_existing_shares()
        
        # Setup filesystem watchdog
        self.observer = Observer()
        self.setup_watchdog()

    def setup_samba_config(self):
        """Ensure Samba configuration is properly set up"""
        try:
            # Create shares.conf if it doesn't exist
            if not os.path.exists(self.shares_conf_path):
                with open(self.shares_conf_path, 'w') as f:
                    f.write('; USB Share configurations\n')
            
            # Check if main smb.conf includes our shares.conf
            include_line = f'include = {self.shares_conf_path}'
            
            with open(self.smb_conf_path, 'r') as f:
                smb_conf_content = f.read()
                
            if include_line not in smb_conf_content:
                # Add include directive and guest access configuration to main smb.conf
                with open(self.smb_conf_path, 'a') as f:
                    f.write(f'''
; USB Share configurations
{include_line}

[global]
    map to guest = Bad User
    guest account = nobody
    server min protocol = NT1
    client min protocol = NT1
    ntlm auth = yes
    lanman auth = yes
''')
                    
            self.logger.info("Samba configuration setup completed")
            
        except Exception as e:
            self.logger.error(f"Failed to setup Samba configuration: {e}")
            raise


    def validate_existing_shares(self):
        """Check for and clean up stale shares"""
        self.logger.info("Validating existing Samba shares...")
        
        try:
            config = configparser.ConfigParser(strict=False)
            config.read(self.shares_conf_path)
            
            shares_to_remove = []
            
            for share_name in config.sections():
                if share_name.startswith('USB_'):
                    share_path = config[share_name].get('path')
                    
                    if not share_path or not os.path.exists(share_path) or not os.path.ismount(share_path):
                        shares_to_remove.append(share_name)
                        self.logger.warning(f"Found stale share: {share_name} for path {share_path}")
            
            # Remove stale shares
            if shares_to_remove:
                self.remove_shares(shares_to_remove)
                
            # Update active shares set
            self.update_active_shares()
            
        except Exception as e:
            self.logger.error(f"Error validating existing shares: {e}")

    def update_active_shares(self):
        """Update the set of currently active shares"""
        config = configparser.ConfigParser(strict=False)
        config.read(self.shares_conf_path)
        self.active_shares = {section for section in config.sections() if section.startswith('USB_')}

    def create_share(self, mount_point):
        """Create a new Samba share for a mounted device with guest access"""
        try:
            device_name = mount_point.name
            share_name = f"USB_{device_name}"
            
            # Skip if share already exists
            if share_name in self.active_shares:
                self.logger.info(f"Share {share_name} already exists")
                return True
            
            config = configparser.ConfigParser(strict=False)
            config.read(self.shares_conf_path)
            
            # Simplified share configuration with guest access and write permissions
            config[share_name] = {
                'comment': f'USB Drive {device_name}',
                'path': str(mount_point),
                'browseable': 'yes',
                'read only': 'no',
                'guest ok': 'yes',
                'create mask': '0777',
                'directory mask': '0777',
                'force create mode': '0777',
                'force directory mode': '0777',
                'public': 'yes'
            }
            
            # Write configuration
            with open(self.shares_conf_path, 'w') as f:
                config.write(f)
            
            # Reload Samba configuration
            subprocess.run(['systemctl', 'reload', 'smbd'], check=True)
            
            # Update active shares
            self.active_shares.add(share_name)
            
            self.logger.info(f"Successfully created share {share_name} for {mount_point}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create share for {mount_point}: {e}")
            return False


    def remove_shares(self, share_names):
        """Remove one or more Samba shares"""
        if not isinstance(share_names, list):
            share_names = [share_names]
            
        try:
            config = configparser.ConfigParser(strict=False)
            config.read(self.shares_conf_path)
            
            modified = False
            for share_name in share_names:
                if share_name in config.sections():
                    config.remove_section(share_name)
                    self.active_shares.discard(share_name)
                    modified = True
                    self.logger.info(f"Removed share {share_name}")
            
            if modified:
                # Write updated configuration
                with open(self.shares_conf_path, 'w') as f:
                    config.write(f)
                    
                # Reload Samba configuration
                subprocess.run(['systemctl', 'reload', 'smbd'], check=True)
                
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to remove shares {share_names}: {e}")
            return False

    class USBMountHandler(FileSystemEventHandler):
        def __init__(self, manager):
            self.manager = manager
            
        def on_created(self, event):
            if event.is_directory and str(event.src_path).startswith(str(self.manager.mount_base)):
                self.manager.logger.info(f"New mount point detected: {event.src_path}")
                # Small delay to ensure mount is complete
                time.sleep(1)
                if os.path.ismount(event.src_path):
                    self.manager.create_share(Path(event.src_path))
                    
        def on_deleted(self, event):
            if event.is_directory and str(event.src_path).startswith(str(self.manager.mount_base)):
                self.manager.logger.info(f"Mount point removed: {event.src_path}")
                share_name = f"USB_{os.path.basename(event.src_path)}"
                self.manager.remove_shares([share_name])

    def setup_watchdog(self):
        """Setup filesystem monitoring for mount points"""
        event_handler = self.USBMountHandler(self)
        self.observer.schedule(event_handler, str(self.mount_base), recursive=False)

    def scan_existing_mounts(self):
        """Scan and create shares for existing mounted devices"""
        self.logger.info("Scanning for existing mounted devices...")
        
        try:
            for item in self.mount_base.iterdir():
                if item.is_dir() and os.path.ismount(item):
                    self.logger.info(f"Found existing mount: {item}")
                    self.create_share(item)
                    
        except Exception as e:
            self.logger.error(f"Error scanning existing mounts: {e}")

    def start(self):
        """Start the SMB share manager"""
        self.logger.info("Starting SMB Share Manager...")
        
        # First scan for existing mounts
        self.scan_existing_mounts()
        
        # Start watching for new mounts
        self.observer.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.observer.stop()
        self.observer.join()

def main():
    logging.basicConfig(level=logging.DEBUG)
    try:
        manager = SMBShareManager()
        manager.start()
    except KeyboardInterrupt:
        print("\nStopping SMB Share Manager...")
    except Exception as e:
        logging.error(f"Critical error: {e}")
        raise

if __name__ == "__main__":
    main()
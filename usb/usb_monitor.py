#!/usr/bin/env python3

import pyudev
import subprocess
import os
import logging
from pathlib import Path
import time
import pwd
import grp
import psutil

class USBMonitor:
    def __init__(self):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filename='/var/log/usb_monitor.log'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize pyudev
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='block', device_type='partition')
        
        # Set default user to eishan05
        self.user = os.environ.get('SUDO_USER', 'eishan05')
        try:
            self.uid = pwd.getpwnam(self.user).pw_uid
            self.gid = grp.getgrnam(self.user).gr_gid
        except KeyError:
            self.logger.error(f"Could not find user {self.user}")
            raise SystemExit(f"User {self.user} not found in system")
        
        # Mount point base directory
        self.mount_base = Path(f'/media/{self.user}')
        self.setup_mount_directory()
        
        # Keep track of mounted devices
        self.mounted_devices = set()
        self.update_mounted_devices()

    def update_mounted_devices(self):
        """Update the set of currently mounted devices"""
        self.mounted_devices.clear()
        partitions = psutil.disk_partitions(all=True)
        for partition in partitions:
            self.mounted_devices.add(partition.device)
            self.logger.debug(f"Found mounted device: {partition.device}")

    def is_device_mounted(self, device_path):
        """Check if a device is already mounted"""
        return device_path in self.mounted_devices

    def is_usb_device(self, device):
        """Check if a device is a USB device"""
        for parent in device.ancestors:
            if parent.subsystem == 'usb':
                return True
        return False

    def setup_mount_directory(self):
        """Setup mount directory with proper permissions"""
        try:
            self.mount_base.mkdir(parents=True, exist_ok=True)
            # Give user full access to mount directory
            os.chown(self.mount_base, self.uid, self.gid)
            os.chmod(self.mount_base, 0o755)
            self.logger.info(f"Successfully set up mount directory for user {self.user}")
        except Exception as e:
            self.logger.error(f"Failed to setup mount directory: {e}")
            raise

    def set_permissions(self, path, is_directory=True):
        """Set appropriate permissions for mounted files and directories"""
        try:
            os.chown(path, self.uid, self.gid)
            if is_directory:
                # rwxr-xr-x for directories
                os.chmod(path, 0o755)
            else:
                # rw-r--r-- for files
                os.chmod(path, 0o644)
            return True
        except Exception as e:
            self.logger.error(f"Failed to set permissions for {path}: {e}")
            return False

    def recursively_set_permissions(self, path):
        """Recursively set permissions on a directory"""
        try:
            for root, dirs, files in os.walk(path):
                # Set directory permissions
                self.set_permissions(root, True)
                # Set file permissions
                for file in files:
                    self.set_permissions(os.path.join(root, file), False)
            return True
        except Exception as e:
            self.logger.error(f"Failed to recursively set permissions: {e}")
            return False

    def scan_existing_devices(self):
        """Scan and mount already connected USB devices"""
        self.logger.info("Scanning for existing USB devices...")
        
        # Get all block devices
        for device in self.context.list_devices(subsystem='block', DEVTYPE='partition'):
            try:
                # Skip if not a USB device
                if not self.is_usb_device(device):
                    continue
                
                device_path = device.device_node
                
                # Skip if already mounted
                if self.is_device_mounted(device_path):
                    self.logger.info(f"Device {device_path} is already mounted")
                    continue
                
                self.logger.info(f"Found existing USB device: {device_path}")
                fs_type = self.get_filesystem_type(device_path)
                
                if fs_type:
                    self.logger.info(f"Mounting existing device {device_path} with filesystem {fs_type}")
                    self.mount_device(device_path, fs_type)
                    
            except Exception as e:
                self.logger.error(f"Error processing existing device {device.device_node}: {e}")

    def get_filesystem_type(self, device_path):
        """Detect filesystem type using blkid"""
        try:
            for _ in range(3):
                result = subprocess.run(
                    ['blkid', '-o', 'value', '-s', 'TYPE', device_path],
                    capture_output=True,
                    text=True
                )
                if result.stdout.strip():
                    return result.stdout.strip()
                time.sleep(1)
            return None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to detect filesystem type: {e}")
            return None

    def mount_device(self, device_path, filesystem_type):
        """Mount the device with appropriate filesystem type and permissions"""
        # Skip if already mounted
        if self.is_device_mounted(device_path):
            self.logger.info(f"Device {device_path} is already mounted")
            return True

        device_name = os.path.basename(device_path)
        mount_point = self.mount_base / device_name
        mount_point.mkdir(exist_ok=True)
        os.chown(mount_point, self.uid, self.gid)

        # Prepare mount options based on filesystem type
        mount_options = []
        
        if filesystem_type == 'vfat':
            # For FAT filesystems
            mount_options.extend([
                f'uid={self.uid}',
                f'gid={self.gid}',
                'rw',
                'dmask=022',  # rwxr-xr-x for directories
                'fmask=133',  # rw-r--r-- for files
                'utf8',
                'flush'
            ])
        elif filesystem_type == 'ntfs':
            # For NTFS filesystems
            mount_options.extend([
                f'uid={self.uid}',
                f'gid={self.gid}',
                'rw',
                'dmask=022',
                'fmask=133',
                'windows_names',
                'big_writes',
                'ntfs-3g'
            ])
        elif filesystem_type == 'exfat':
            # For exFAT filesystems
            mount_options.extend([
                f'uid={self.uid}',
                f'gid={self.gid}',
                'rw',
                'dmask=022',
                'fmask=133'
            ])
        elif filesystem_type in ['ext4', 'ext3', 'ext2']:
            # For ext filesystems
            mount_options.extend([
                'rw',
                'defaults',
                'user_xattr'
            ])

        # Build mount command
        mount_cmd = ['mount']
        if mount_options:
            mount_cmd.extend(['-o', ','.join(mount_options)])
        mount_cmd.extend([device_path, str(mount_point)])

        try:
            # Mount with retry mechanism
            for attempt in range(3):
                try:
                    subprocess.run(mount_cmd, check=True, capture_output=True, text=True)
                    self.logger.info(f"Successfully mounted {device_path} at {mount_point}")
                    
                    # Update mounted devices list
                    self.mounted_devices.add(device_path)
                    
                    # For ext filesystems, we need to set permissions after mounting
                    if filesystem_type in ['ext4', 'ext3', 'ext2']:
                        self.logger.info("Setting permissions for ext filesystem...")
                        self.recursively_set_permissions(str(mount_point))
                    
                    # Verify mount was successful
                    if not os.path.ismount(str(mount_point)):
                        raise Exception("Mount point verification failed")
                    
                    return True
                except subprocess.CalledProcessError as e:
                    if attempt == 2:  # Last attempt
                        raise
                    time.sleep(1)
            return False
        except Exception as e:
            self.logger.error(f"Failed to mount {device_path}: {str(e)}")
            try:
                mount_point.rmdir()
            except OSError:
                pass
            return False

    def unmount_device(self, device_path):
        """Unmount the device"""
        try:
            # First try with regular umount
            subprocess.run(['umount', device_path], check=True)
            # Update mounted devices list
            self.mounted_devices.discard(device_path)
        except subprocess.CalledProcessError:
            try:
                # If regular unmount fails, try forced unmount
                subprocess.run(['umount', '-f', device_path], check=True)
                self.mounted_devices.discard(device_path)
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to force unmount {device_path}: {e}")
                return False

        # Remove mount point directory
        try:
            device_name = os.path.basename(device_path)
            mount_point = self.mount_base / device_name
            if mount_point.exists():
                mount_point.rmdir()
            self.logger.info(f"Successfully unmounted {device_path}")
            return True
        except OSError as e:
            self.logger.error(f"Failed to remove mount point directory: {e}")
            return False

    def device_handler(self, device):
        """Handle device events"""
        if device.action == 'add':
            self.logger.info(f"New device detected: {device.device_node}")
            time.sleep(1)
            fs_type = self.get_filesystem_type(device.device_node)
            if fs_type:
                self.logger.info(f"Detected filesystem: {fs_type}")
                self.mount_device(device.device_node, fs_type)
        elif device.action == 'remove':
            self.logger.info(f"Device removed: {device.device_node}")
            self.unmount_device(device.device_node)

    def start_monitoring(self):
        """Start monitoring for USB events"""
        self.logger.info(f"Starting USB monitor for user {self.user}...")
        
        # First scan for existing devices
        self.scan_existing_devices()
        
        # Then start monitoring for new events
        self.logger.info("Starting monitoring for new USB events...")
        self.monitor.start()
        for device in iter(self.monitor.poll, None):
            try:
                self.device_handler(device)
            except Exception as e:
                self.logger.error(f"Error handling device: {e}")
                continue

def main():
    monitor = USBMonitor()
    try:
        monitor.start_monitoring()
    except KeyboardInterrupt:
        print("\nStopping USB monitor...")
    except Exception as e:
        logging.error(f"Critical error: {e}")
        raise

if __name__ == "__main__":
    main()
import pyudev
import subprocess
import os
import logging
from pathlib import Path
import time
import pwd
import grp

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
        
        # Mount point base directory - using /media/eishan05
        self.mount_base = Path(f'/media/{self.user}')
        self.setup_mount_directory()

    def setup_mount_directory(self):
        """Setup mount directory with proper permissions"""
        try:
            self.mount_base.mkdir(parents=True, exist_ok=True)
            os.chown(self.mount_base, self.uid, self.gid)
            os.chmod(self.mount_base, 0o755)
            self.logger.info(f"Successfully set up mount directory for user {self.user}")
        except Exception as e:
            self.logger.error(f"Failed to setup mount directory: {e}")
            raise

    def get_filesystem_type(self, device_path):
        """Detect filesystem type using blkid"""
        try:
            # Add retry mechanism as sometimes Raspberry Pi needs a moment
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
        """Mount the device with appropriate filesystem type"""
        # Create unique mount point
        device_name = os.path.basename(device_path)
        mount_point = self.mount_base / device_name
        mount_point.mkdir(exist_ok=True)
        os.chown(mount_point, self.uid, self.gid)

        # Prepare mount options based on filesystem type
        mount_options = [f'uid={self.uid}', f'gid={self.gid}']
        
        if filesystem_type == 'vfat':
            mount_options.extend(['dmask=027', 'fmask=137'])
        elif filesystem_type == 'ntfs':
            # Check if ntfs-3g is installed
            if subprocess.run(['which', 'ntfs-3g'], capture_output=True).returncode == 0:
                mount_options.append('ntfs-3g')
        elif filesystem_type in ['ext4', 'ext3', 'ext2']:
            mount_options.append('defaults')
        elif filesystem_type == 'exfat':
            mount_options.extend(['dmask=027', 'fmask=137'])

        # Build mount command
        mount_cmd = ['mount']
        if mount_options:
            mount_cmd.extend(['-o', ','.join(mount_options)])
        mount_cmd.extend([device_path, str(mount_point)])

        try:
            # Add retry mechanism
            for attempt in range(3):
                try:
                    subprocess.run(mount_cmd, check=True, capture_output=True, text=True)
                    self.logger.info(f"Successfully mounted {device_path} at {mount_point}")
                    # Ensure correct permissions after mounting
                    os.chown(str(mount_point), self.uid, self.gid)
                    return True
                except subprocess.CalledProcessError as e:
                    if attempt == 2:  # Last attempt
                        raise
                    time.sleep(1)
            return False
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to mount {device_path}: {e.stderr}")
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
        except subprocess.CalledProcessError:
            try:
                # If regular unmount fails, try forced unmount
                subprocess.run(['umount', '-f', device_path], check=True)
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
            # Add a small delay to ensure device is ready
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
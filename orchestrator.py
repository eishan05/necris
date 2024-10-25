#!/usr/bin/env python3

import subprocess
import threading
import time
import logging
import signal
import sys
import os
from pathlib import Path

class ServiceOrchestrator:
    def __init__(self):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filename='/var/log/file_server_orchestrator.log'
        )
        self.logger = logging.getLogger(__name__)
        
        # Store process handles
        self.processes = {
            'usb_monitor': None,
            'smb_share_manager': None,
            'server': None
        }
        
        # Threading control
        self.should_run = threading.Event()
        self.should_run.set()
        
        # Monitor restart interval (4 hours)
        self.monitor_restart_interval = 4 * 60 * 60
        
        # Get script directory
        self.script_dir = Path(__file__).parent.resolve()
        
    def start_service(self, service_name, script_name):
        """Start a service and return its process handle"""
        try:
            script_path = self.script_dir / script_name
            # USB monitor and SMB manager need root privileges
            process = subprocess.Popen(
                ['python3', str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.logger.info(f"Started {service_name} (PID: {process.pid})")
            return process
            
        except Exception as e:
            self.logger.error(f"Failed to start {service_name}: {e}")
            return None
            
    def stop_service(self, service_name):
        """Stop a service gracefully"""
        process = self.processes.get(service_name)
        if process:
            try:
                self.logger.info(f"Stopping {service_name} (PID: {process.pid})")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.logger.warning(f"{service_name} didn't terminate, forcing...")
                    process.kill()
                self.processes[service_name] = None
                return True
            except Exception as e:
                self.logger.error(f"Error stopping {service_name}: {e}")
                return False
        return True
            
    def restart_usb_monitor(self):
        """Restart the USB monitor service"""
        self.logger.info("Restarting USB monitor...")
        self.stop_service('usb_monitor')
        time.sleep(2)  # Give it time to clean up
        self.processes['usb_monitor'] = self.start_service('usb_monitor', 'usb_monitor.py')
        
    def monitor_service(self, service_name):
        """Monitor a service and restart it if it crashes"""
        while self.should_run.is_set():
            process = self.processes.get(service_name)
            if process:
                return_code = process.poll()
                if return_code is not None:
                    self.logger.warning(f"{service_name} exited with code {return_code}, restarting...")
                    self.processes[service_name] = self.start_service(
                        service_name,
                        f"{service_name.lower()}.py"
                    )
            time.sleep(5)
            
    def periodic_monitor_restart(self):
        """Periodically restart the USB monitor"""
        while self.should_run.is_set():
            time.sleep(self.monitor_restart_interval)
            if self.should_run.is_set():
                self.logger.info("Performing periodic USB monitor restart")
                self.restart_usb_monitor()
                
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()
        
    def shutdown(self):
        """Shutdown all services"""
        self.should_run.clear()
        
        # Stop all services
        for service_name in self.processes.keys():
            self.stop_service(service_name)
            
        self.logger.info("All services stopped")
        sys.exit(0)
        
    def start(self):
        """Start all services and monitoring"""
        self.logger.info("Starting File Server Orchestrator...")
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        
        try:
            # Start all services
            for service_name in self.processes.keys():
                self.processes[service_name] = self.start_service(
                    service_name,
                    f"{service_name.lower()}.py"
                )
                
            # Start service monitoring threads
            monitor_threads = []
            for service_name in self.processes.keys():
                thread = threading.Thread(
                    target=self.monitor_service,
                    args=(service_name,),
                    daemon=True
                )
                thread.start()
                monitor_threads.append(thread)
                
            # Start periodic USB monitor restart thread
            restart_thread = threading.Thread(
                target=self.periodic_monitor_restart,
                daemon=True
            )
            restart_thread.start()
            
            # Keep the main thread alive
            while self.should_run.is_set():
                time.sleep(1)
                
        except Exception as e:
            self.logger.error(f"Critical error: {e}")
            self.shutdown()

def main():
    logging.basicConfig(level=logging.DEBUG)
    if os.geteuid() != 0:
        print("This script must be run as root!")
        sys.exit(1)
        
    orchestrator = ServiceOrchestrator()
    orchestrator.start()

if __name__ == "__main__":
    main()
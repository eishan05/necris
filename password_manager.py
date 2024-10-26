# password_manager.py

import json
import hashlib
import subprocess
import logging
import os

class PasswordManager:
    def __init__(self, credentials_file='/etc/necris/credentials.json'):
        self.credentials_file = credentials_file
        self.logger = logging.getLogger(__name__)
        
        # Ensure credentials directory exists
        os.makedirs(os.path.dirname(credentials_file), exist_ok=True)
        
        # Initialize default credentials if they don't exist
        if not os.path.exists(credentials_file):
            self.init_credentials()
    
    def init_credentials(self):
        """Initialize default credentials"""
        credentials = {
            'username': 'necris-client',
            'password': hashlib.sha256('necris-is-awesome'.encode()).hexdigest()
        }
        self._save_credentials(credentials)
        self._update_samba_password('necris-is-awesome')
    
    def _save_credentials(self, credentials):
        """Save credentials to file with secure permissions"""
        with open(self.credentials_file, 'w') as f:
            json.dump(credentials, f)
        os.chmod(self.credentials_file, 0o600)
    
    def get_credentials(self):
        """Get current credentials"""
        with open(self.credentials_file, 'r') as f:
            return json.load(f)
    
    def _update_samba_password(self, new_password):
        """Update Samba user password"""
        try:
            proc = subprocess.Popen(
                ['smbpasswd', 'necris-client'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            # Send password twice (for confirmation)
            proc.communicate(input=f"{new_password}\n{new_password}\n".encode())
            
            if proc.returncode == 0:
                self.logger.info("Successfully updated Samba password")
                return True
            else:
                self.logger.error("Failed to update Samba password")
                return False
                
        except Exception as e:
            self.logger.error(f"Error updating Samba password: {e}")
            return False
    
    def update_password(self, new_password):
        """Update both file credentials and Samba password"""
        try:
            # First update Samba password
            if self._update_samba_password(new_password):
                # Then update credentials file
                credentials = self.get_credentials()
                credentials['password'] = hashlib.sha256(new_password.encode()).hexdigest()
                self._save_credentials(credentials)
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Error updating password: {e}")
            return False
    
    def verify_password(self, password):
        """Verify if a password matches stored credentials"""
        credentials = self.get_credentials()
        return hashlib.sha256(password.encode()).hexdigest() == credentials['password']
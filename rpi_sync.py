import sys
import os
import time
import datetime
import paramiko
import shutil
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                              QFileDialog, QProgressBar, QTextEdit, QCheckBox)
from PySide6.QtCore import Qt, QThread, Signal

class SftpWorker(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, hostname, username, password, remote_dir, local_dir):
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        self.stop_flag = False
        self.files_to_transfer = []
        self.total_files = 0
        self.files_copied = 0
        self.new_files = 0
        
    def get_remote_files_recursive(self, sftp, remote_path, relative_path=""):
        """Recursively get all files from remote directory and subdirectories"""
        try:
            items = sftp.listdir(remote_path)
            
            for item in items:
                item_remote_path = f"{remote_path}/{item}"
                item_relative_path = f"{relative_path}/{item}" if relative_path else item
                
                try:
                    # Check if it's a directory
                    sftp.listdir(item_remote_path)
                    # It's a directory, recursively get files
                    self.get_remote_files_recursive(sftp, item_remote_path, item_relative_path)
                except:
                    # It's a file, add to the list
                    self.files_to_transfer.append((item_remote_path, item_relative_path))
        except Exception as e:
            self.status_update.emit(f"Error accessing {remote_path}: {str(e)}")
            
    def run(self):
        try:
            # Connect to the Raspberry Pi
            self.status_update.emit("Connecting to Raspberry Pi...")
            transport = paramiko.Transport((self.hostname, 22))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            # Get list of files in remote directory recursively
            self.status_update.emit("Getting file list recursively...")
            self.files_to_transfer = []
            self.get_remote_files_recursive(sftp, self.remote_dir)
            
            if not self.files_to_transfer:
                self.status_update.emit("No files found in the remote directory.")
                self.finished_signal.emit(False, "No files found")
                transport.close()
                return
                
            # Create local directory if it doesn't exist
            os.makedirs(self.local_dir, exist_ok=True)
            
            # Copy files
            self.total_files = len(self.files_to_transfer)
            self.status_update.emit(f"Found {self.total_files} files. Starting transfer...")
            
            self.files_copied = 0
            self.new_files = 0
            
            for i, (remote_path, relative_path) in enumerate(self.files_to_transfer):
                if self.stop_flag:
                    self.status_update.emit("Transfer stopped by user.")
                    self.finished_signal.emit(False, "Transfer stopped")
                    break
                
                local_path = os.path.join(self.local_dir, relative_path)
                local_dir = os.path.dirname(local_path)
                
                # Create local directory structure if it doesn't exist
                os.makedirs(local_dir, exist_ok=True)
                
                # Check if file already exists locally
                if os.path.exists(local_path):
                    # Compare file sizes to see if they're different
                    remote_stat = sftp.stat(remote_path)
                    local_stat = os.stat(local_path)
                    
                    if remote_stat.st_size == local_stat.st_size:
                        # File exists and is the same size, skip it
                        self.files_copied += 1
                        self.progress_update.emit(int((self.files_copied / self.total_files) * 100))
                        continue
                
                # Copy the file
                sftp.get(remote_path, local_path)
                self.files_copied += 1
                self.new_files += 1
                
                # Update progress
                self.progress_update.emit(int((self.files_copied / self.total_files) * 100))
                if self.files_copied % 10 == 0 or self.files_copied == self.total_files:
                    self.status_update.emit(f"Copied {self.files_copied}/{self.total_files} files")
            
            # Close connection
            sftp.close()
            transport.close()
            
            self.status_update.emit(f"Transfer complete! Copied {self.new_files} new files out of {self.total_files} total files.")
            self.finished_signal.emit(True, f"Transferred {self.new_files} new files")
            
        except Exception as e:
            self.status_update.emit(f"Error: {str(e)}")
            self.finished_signal.emit(False, str(e))
    
    def stop(self):
        self.stop_flag = True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Raspberry Pi File Transfer")
        self.setGeometry(100, 100, 600, 500)
        
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)
        
        # Connection settings
        self.create_connection_section()
        
        # Directory settings
        self.create_directory_section()
        
        # Options
        self.create_options_section()
        
        # Progress section
        self.create_progress_section()
        
        # Log section
        self.create_log_section()
        
        # Action buttons
        self.create_action_buttons()
        
        # Initialize worker
        self.worker = None
        
        self.load_settings()
        
    def create_connection_section(self):
        conn_layout = QVBoxLayout()
        
        # Raspberry Pi connection
        conn_layout.addWidget(QLabel("Raspberry Pi Connection"))
        
        # Hostname
        host_layout = QHBoxLayout()
        host_layout.addWidget(QLabel("Hostname/IP:"))
        self.hostname_input = QLineEdit("raspberrypi.local")
        host_layout.addWidget(self.hostname_input)
        conn_layout.addLayout(host_layout)
        
        # Username
        user_layout = QHBoxLayout()
        user_layout.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit("pi")
        user_layout.addWidget(self.username_input)
        conn_layout.addLayout(user_layout)
        
        # Password
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit("raspberry")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        pass_layout.addWidget(self.password_input)
        conn_layout.addLayout(pass_layout)
        
        self.layout.addLayout(conn_layout)
    
    def create_directory_section(self):
        dir_layout = QVBoxLayout()
        
        # Remote directory
        dir_layout.addWidget(QLabel("Remote Directory on Raspberry Pi:"))
        self.remote_dir_input = QLineEdit("/home/pi/data")
        dir_layout.addWidget(self.remote_dir_input)
        
        # Local directory
        local_dir_layout = QHBoxLayout()
        local_dir_layout.addWidget(QLabel("Local Directory:"))
        self.local_dir_input = QLineEdit()
        local_dir_layout.addWidget(self.local_dir_input)
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_local_dir)
        local_dir_layout.addWidget(self.browse_btn)
        dir_layout.addLayout(local_dir_layout)
        
        self.layout.addLayout(dir_layout)
    
    def create_options_section(self):
        options_layout = QVBoxLayout()
        
        self.delete_after_copy = QCheckBox("Delete files from Raspberry Pi after copying")
        options_layout.addWidget(self.delete_after_copy)
        
        self.auto_date_folder = QCheckBox("Create date-based subfolder for transferred files")
        self.auto_date_folder.setChecked(True)
        options_layout.addWidget(self.auto_date_folder)
        
        self.layout.addLayout(options_layout)
    
    def create_progress_section(self):
        progress_layout = QVBoxLayout()
        
        self.progress_label = QLabel("Ready")
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.layout.addLayout(progress_layout)
    
    def create_log_section(self):
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.layout.addWidget(self.log_text)
    
    def create_action_buttons(self):
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start Transfer")
        self.start_btn.clicked.connect(self.start_transfer)
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_transfer)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        
        self.save_settings_btn = QPushButton("Save Settings")
        self.save_settings_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(self.save_settings_btn)
        
        self.layout.addLayout(btn_layout)
    
    def browse_local_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.local_dir_input.setText(dir_path)
    
    def start_transfer(self):
        if self.worker and self.worker.isRunning():
            self.log_message("Transfer already in progress")
            return
        
        hostname = self.hostname_input.text()
        username = self.username_input.text()
        password = self.password_input.text()
        remote_dir = self.remote_dir_input.text()
        local_dir = self.local_dir_input.text()
        
        # Validate inputs
        if not hostname or not username or not password or not remote_dir or not local_dir:
            self.log_message("Error: Please fill in all fields")
            return
        
        # Create date subfolder if option is checked
        if self.auto_date_folder.isChecked():
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            local_dir = os.path.join(local_dir, today)
        
        # Initialize and start worker thread
        self.worker = SftpWorker(hostname, username, password, remote_dir, local_dir)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.status_update.connect(self.log_message)
        self.worker.finished_signal.connect(self.transfer_finished)
        
        self.worker.start()
        
        # Update UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_message(f"Starting transfer from {hostname}:{remote_dir} to {local_dir}")
    
    def stop_transfer(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log_message("Stopping transfer... Please wait.")
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"Progress: {value}%")
    
    def log_message(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def transfer_finished(self, success, message):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        if success:
            self.log_message(f"Transfer completed successfully: {message}")
            
            # Delete files if option is checked
            if self.delete_after_copy.isChecked():
                self.log_message("Deleting files from Raspberry Pi is not implemented yet.")
                # Implementation would go here in a separate worker thread
        else:
            self.log_message(f"Transfer failed: {message}")
    
    def save_settings(self):
        try:
            settings_dir = os.path.join(str(Path.home()), ".rpi_transfer")
            os.makedirs(settings_dir, exist_ok=True)
            
            settings_file = os.path.join(settings_dir, "settings.txt")
            
            with open(settings_file, "w") as f:
                f.write(f"hostname={self.hostname_input.text()}\n")
                f.write(f"username={self.username_input.text()}\n")
                f.write(f"remote_dir={self.remote_dir_input.text()}\n")
                f.write(f"local_dir={self.local_dir_input.text()}\n")
                f.write(f"auto_date_folder={1 if self.auto_date_folder.isChecked() else 0}\n")
                f.write(f"delete_after_copy={1 if self.delete_after_copy.isChecked() else 0}\n")
            
            self.log_message("Settings saved successfully")
        except Exception as e:
            self.log_message(f"Error saving settings: {str(e)}")
    
    def load_settings(self):
        try:
            settings_file = os.path.join(str(Path.home()), ".rpi_transfer", "settings.txt")
            
            if not os.path.exists(settings_file):
                return
            
            with open(settings_file, "r") as f:
                for line in f:
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        
                        if key == "hostname":
                            self.hostname_input.setText(value)
                        elif key == "username":
                            self.username_input.setText(value)
                        elif key == "remote_dir":
                            self.remote_dir_input.setText(value)
                        elif key == "local_dir":
                            self.local_dir_input.setText(value)
                        elif key == "auto_date_folder":
                            self.auto_date_folder.setChecked(value == "1")
                        elif key == "delete_after_copy":
                            self.delete_after_copy.setChecked(value == "1")
            
            self.log_message("Settings loaded successfully")
        except Exception as e:
            self.log_message(f"Error loading settings: {str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
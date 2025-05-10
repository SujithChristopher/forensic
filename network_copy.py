import sys
import os
import time
import datetime
import paramiko
import shutil
import socket
import threading
import ipaddress
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                              QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                              QFileDialog, QProgressBar, QTextEdit, QCheckBox,
                              QComboBox, QMessageBox)
from PySide6.QtCore import Qt, QThread, Signal

class NetworkScanner(QThread):
    device_found = Signal(str, str)
    scan_progress = Signal(int)
    scan_complete = Signal()
    
    def __init__(self, network_range):
        super().__init__()
        self.network_range = network_range
        self.stop_flag = False
        
    def run(self):
        try:
            # Parse the network range
            network = ipaddress.IPv4Network(self.network_range)
            total_hosts = network.num_addresses - 2  # Subtract network and broadcast addresses
            scanned_hosts = 0
            
            # Function to check a single host
            def check_host(ip):
                nonlocal scanned_hosts
                
                if self.stop_flag:
                    return
                
                # Try to resolve hostname
                hostname = ""
                try:
                    hostname = socket.getfqdn(str(ip))
                    if hostname == str(ip):  # If resolution failed
                        hostname = ""
                except:
                    pass
                
                # Check if port 22 is open (SSH)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    result = sock.connect_ex((str(ip), 22))
                    sock.close()
                    
                    if result == 0:  # Port is open
                        # Check if it might be a Raspberry Pi
                        is_pi = False
                        if "raspberry" in hostname.lower() or not hostname:
                            is_pi = True
                        
                        if is_pi:
                            display_name = f"{hostname} ({ip})" if hostname else str(ip)
                            self.device_found.emit(str(ip), display_name)
                except:
                    pass
                
                # Update progress
                scanned_hosts += 1
                self.scan_progress.emit(int((scanned_hosts / total_hosts) * 100))
            
            # Skip the network and broadcast addresses
            hosts = [ip for ip in network.hosts()]
            
            # Use threads for faster scanning
            threads = []
            max_threads = 50
            
            for i in range(0, len(hosts), max_threads):
                if self.stop_flag:
                    break
                    
                batch = hosts[i:i + max_threads]
                threads = []
                
                for ip in batch:
                    if self.stop_flag:
                        break
                    t = threading.Thread(target=check_host, args=(ip,))
                    threads.append(t)
                    t.start()
                
                # Wait for all threads to complete
                for t in threads:
                    t.join()
            
            self.scan_complete.emit()
            
        except Exception as e:
            print(f"Scan error: {str(e)}")
            self.scan_complete.emit()
    
    def stop(self):
        self.stop_flag = True


class SftpWorker(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, hostname, username, password, remote_dir, local_dir, delete_after=False):
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        self.delete_after = delete_after
        self.stop_flag = False
        self.files_to_transfer = []
        self.total_files = 0
        self.files_copied = 0
        self.new_files = 0
        self.successful_transfers = []  # Track successfully transferred files for deletion
        
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
            self.successful_transfers = []
            
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
                copy_file = True
                if os.path.exists(local_path):
                    # Compare file sizes to see if they're different
                    remote_stat = sftp.stat(remote_path)
                    local_stat = os.stat(local_path)
                    
                    if remote_stat.st_size == local_stat.st_size:
                        # File exists and is the same size, skip it
                        copy_file = False
                
                if copy_file:
                    # Copy the file
                    sftp.get(remote_path, local_path)
                    self.new_files += 1
                    # Add to successful transfers for deletion later
                    self.successful_transfers.append(remote_path)
                
                self.files_copied += 1
                
                # Update progress
                self.progress_update.emit(int((self.files_copied / self.total_files) * 100))
                if self.files_copied % 10 == 0 or self.files_copied == self.total_files:
                    self.status_update.emit(f"Copied {self.files_copied}/{self.total_files} files")
            
            # Delete files if requested
            if self.delete_after and self.successful_transfers and not self.stop_flag:
                self.status_update.emit(f"Deleting {len(self.successful_transfers)} files from Raspberry Pi...")
                
                # Open SSH client for deletion
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(self.hostname, username=self.username, password=self.password)
                
                # Delete files in smaller batches to avoid command-line length limits
                batch_size = 20
                deleted_count = 0
                
                for i in range(0, len(self.successful_transfers), batch_size):
                    if self.stop_flag:
                        break
                        
                    batch = self.successful_transfers[i:i + batch_size]
                    for remote_path in batch:
                        try:
                            # Delete the file
                            sftp.remove(remote_path)
                            deleted_count += 1
                            
                            # Update progress occasionally
                            if deleted_count % 10 == 0:
                                self.status_update.emit(f"Deleted {deleted_count}/{len(self.successful_transfers)} files")
                        except Exception as e:
                            self.status_update.emit(f"Error deleting {remote_path}: {str(e)}")
                
                # Delete empty directories (from bottom up)
                if deleted_count > 0 and not self.stop_flag:
                    self.status_update.emit("Cleaning up empty directories...")
                    
                    # Get all unique directories from file paths
                    all_dirs = set()
                    for remote_path in self.successful_transfers:
                        # Get the directory part of the path
                        dir_path = os.path.dirname(remote_path)
                        all_dirs.add(dir_path)
                    
                    # Sort directories by depth (deepest first)
                    sorted_dirs = sorted(all_dirs, key=lambda x: x.count('/'), reverse=True)
                    
                    # Try to remove each directory (will only work if empty)
                    removed_dirs = 0
                    for dir_path in sorted_dirs:
                        if dir_path == self.remote_dir:
                            # Don't delete the root transfer directory
                            continue
                            
                        try:
                            # Check if directory is empty
                            if not sftp.listdir(dir_path):
                                sftp.rmdir(dir_path)
                                removed_dirs += 1
                        except Exception as e:
                            # Ignore errors - directory might not be empty
                            pass
                    
                    if removed_dirs > 0:
                        self.status_update.emit(f"Removed {removed_dirs} empty directories")
                
                ssh.close()
                
                self.status_update.emit(f"Deleted {deleted_count} files from Raspberry Pi")
            
            # Close SFTP connection
            sftp.close()
            transport.close()
            
            success_msg = f"Transferred {self.new_files} new files out of {self.total_files} total files."
            if self.delete_after:
                success_msg += f" Deleted {len(self.successful_transfers)} files from Raspberry Pi."
                
            self.status_update.emit(f"Transfer complete! {success_msg}")
            self.finished_signal.emit(True, success_msg)
            
        except Exception as e:
            self.status_update.emit(f"Error: {str(e)}")
            self.finished_signal.emit(False, str(e))
    
    def stop(self):
        self.stop_flag = True


class FileDeleter(QThread):
    progress_update = Signal(int)
    status_update = Signal(str)
    finished_signal = Signal(bool, str)
    
    def __init__(self, hostname, username, password, file_list):
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.file_list = file_list
        self.stop_flag = False
        
    def run(self):
        try:
            # Connect to Raspberry Pi
            self.status_update.emit("Connecting to Raspberry Pi...")
            transport = paramiko.Transport((self.hostname, 22))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)
            
            total_files = len(self.file_list)
            deleted_count = 0
            
            self.status_update.emit(f"Deleting {total_files} files...")
            
            # Delete files
            for i, file_path in enumerate(self.file_list):
                if self.stop_flag:
                    self.status_update.emit("Deletion stopped by user.")
                    self.finished_signal.emit(False, "Deletion stopped")
                    break
                
                try:
                    # Delete the file
                    sftp.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    self.status_update.emit(f"Error deleting {file_path}: {str(e)}")
                
                # Update progress
                self.progress_update.emit(int((i + 1) / total_files * 100))
                if (i + 1) % 10 == 0 or (i + 1) == total_files:
                    self.status_update.emit(f"Deleted {i + 1}/{total_files} files")
            
            # Delete empty directories (bottom-up approach)
            if deleted_count > 0 and not self.stop_flag:
                self.status_update.emit("Cleaning up empty directories...")
                
                # Get all directories from file paths
                all_dirs = set()
                for file_path in self.file_list:
                    dir_path = os.path.dirname(file_path)
                    all_dirs.add(dir_path)
                
                # Sort directories by depth (deepest first)
                sorted_dirs = sorted(all_dirs, key=lambda x: x.count('/'), reverse=True)
                
                removed_dirs = 0
                for dir_path in sorted_dirs:
                    try:
                        # Check if directory is empty before removing
                        if not sftp.listdir(dir_path):
                            sftp.rmdir(dir_path)
                            removed_dirs += 1
                    except Exception as e:
                        # Directory might not be empty or might have been already removed
                        pass
                
                if removed_dirs > 0:
                    self.status_update.emit(f"Removed {removed_dirs} empty directories")
            
            # Close connection
            sftp.close()
            transport.close()
            
            self.status_update.emit(f"Deletion complete. {deleted_count} files deleted.")
            self.finished_signal.emit(True, f"Deleted {deleted_count} files")
            
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
        
        # Initialize workers
        self.worker = None
        self.scanner = None
        self.deleter = None
        
        # Dictionary to store found devices
        self.devices = {}
        
        # Store transferred files for deletion
        self.transferred_files = []
        
        self.load_settings()
        
    def create_connection_section(self):
        conn_layout = QVBoxLayout()
        
        # Raspberry Pi connection
        conn_layout.addWidget(QLabel("Raspberry Pi Connection"))
        
        # Hostname - now with dropdown and scan button
        host_layout = QHBoxLayout()
        host_layout.addWidget(QLabel("Hostname/IP:"))
        
        # Create a combo box for the hostname/IP selection
        self.hostname_combo = QComboBox()
        self.hostname_combo.setEditable(True)
        self.hostname_combo.addItem("raspberrypi.local")
        # Connect the combo box to update hostname when selected
        self.hostname_combo.currentTextChanged.connect(self.update_hostname)
        host_layout.addWidget(self.hostname_combo)
        
        # Add scan button
        self.scan_btn = QPushButton("Scan Network")
        self.scan_btn.clicked.connect(self.start_network_scan)
        host_layout.addWidget(self.scan_btn)
        
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
        
        # Subnet input for scanning
        subnet_layout = QHBoxLayout()
        subnet_layout.addWidget(QLabel("Network Range:"))
        self.subnet_input = QLineEdit()
        self.subnet_input.setPlaceholderText("e.g., 192.168.1.0/24")
        subnet_layout.addWidget(self.subnet_input)
        
        # Auto-detect subnet button
        self.detect_subnet_btn = QPushButton("Auto-detect")
        self.detect_subnet_btn.clicked.connect(self.auto_detect_subnet)
        subnet_layout.addWidget(self.detect_subnet_btn)
        
        conn_layout.addLayout(subnet_layout)
        
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
        self.stop_btn.clicked.connect(self.stop_current_operation)
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
    
    def update_hostname(self, text):
        # When a device is selected from dropdown, get its actual IP
        if text in self.devices:
            # Use the IP address, not the display name
            actual_ip = self.devices[text]
            self.hostname_combo.setCurrentText(actual_ip)
    
    def auto_detect_subnet(self):
        try:
            # Get local IP address
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # Connect to Google DNS to determine local IP
            local_ip = s.getsockname()[0]
            s.close()
            
            # Extract network part
            ip_parts = local_ip.split('.')
            network = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
            
            self.subnet_input.setText(network)
            self.log_message(f"Auto-detected network: {network}")
            
        except Exception as e:
            self.log_message(f"Error detecting network: {str(e)}")
            # Fallback to common subnet
            self.subnet_input.setText("192.168.1.0/24")
    
    def start_network_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.log_message("Scan already in progress")
            return
        
        network_range = self.subnet_input.text()
        if not network_range:
            self.auto_detect_subnet()
            network_range = self.subnet_input.text()
        
        try:
            # Validate network range
            ipaddress.IPv4Network(network_range)
            
            # Clear previous devices
            self.devices = {}
            current_text = self.hostname_combo.currentText()
            self.hostname_combo.clear()
            self.hostname_combo.addItem(current_text)  # Keep current entry
            
            # Start scanner
            self.scanner = NetworkScanner(network_range)
            self.scanner.device_found.connect(self.add_device)
            self.scanner.scan_progress.connect(self.update_scan_progress)
            self.scanner.scan_complete.connect(self.scan_finished)
            
            self.scanner.start()
            
            # Update UI
            self.scan_btn.setText("Stop Scan")
            self.scan_btn.clicked.disconnect()
            self.scan_btn.clicked.connect(self.stop_network_scan)
            self.progress_bar.setValue(0)
            self.log_message(f"Starting network scan on {network_range}...")
            
        except Exception as e:
            self.log_message(f"Invalid network range: {str(e)}")
    
    def stop_network_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.log_message("Stopping scan...")
    
    def add_device(self, ip, display_name):
        self.devices[display_name] = ip
        self.hostname_combo.addItem(display_name)
        self.log_message(f"Found device with SSH: {display_name}")
    
    def update_scan_progress(self, value):
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"Scan progress: {value}%")
    
    def scan_finished(self):
        self.scan_btn.setText("Scan Network")
        self.scan_btn.clicked.disconnect()
        self.scan_btn.clicked.connect(self.start_network_scan)
        self.progress_label.setText("Ready")
        self.log_message("Network scan complete.")
        
        if not self.devices:
            self.log_message("No devices with SSH found on the network.")
    
    def start_transfer(self):
        if self.worker and self.worker.isRunning():
            self.log_message("Transfer already in progress")
            return
        
        hostname = self.hostname_combo.currentText()
        username = self.username_input.text()
        password = self.password_input.text()
        remote_dir = self.remote_dir_input.text()
        local_dir = self.local_dir_input.text()
        delete_after = self.delete_after_copy.isChecked()
        
        # Extract IP if a display name was selected
        if hostname in self.devices:
            hostname = self.devices[hostname]
        
        # Validate inputs
        if not hostname or not username or not password or not remote_dir or not local_dir:
            self.log_message("Error: Please fill in all fields")
            return
        
        # Create date subfolder if option is checked
        if self.auto_date_folder.isChecked():
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            local_dir = os.path.join(local_dir, today)
        
        # Show confirmation dialog if deleting files
        if delete_after:
            reply = QMessageBox.question(
                self, 
                "Confirm Deletion",
                "Files will be deleted from the Raspberry Pi after copying. Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                self.log_message("Transfer canceled by user")
                return
        
        # Initialize and start worker thread
        self.worker = SftpWorker(hostname, username, password, remote_dir, local_dir, delete_after)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.status_update.connect(self.log_message)
        self.worker.finished_signal.connect(self.transfer_finished)
        
        self.worker.start()
        
        # Update UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_message(f"Starting transfer from {hostname}:{remote_dir} to {local_dir}")
    
    def stop_current_operation(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log_message("Stopping transfer... Please wait.")
        elif self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.log_message("Stopping scan... Please wait.")
        elif self.deleter and self.deleter.isRunning():
            self.deleter.stop()
            self.log_message("Stopping deletion... Please wait.")
    
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
        else:
            self.log_message(f"Transfer failed: {message}")
    
    def save_settings(self):
        try:
            settings_dir = os.path.join(str(Path.home()), ".rpi_transfer")
            os.makedirs(settings_dir, exist_ok=True)
            
            settings_file = os.path.join(settings_dir, "settings.txt")
            
            with open(settings_file, "w") as f:
                f.write(f"hostname={self.hostname_combo.currentText()}\n")
                f.write(f"username={self.username_input.text()}\n")
                f.write(f"remote_dir={self.remote_dir_input.text()}\n")
                f.write(f"local_dir={self.local_dir_input.text()}\n")
                f.write(f"subnet={self.subnet_input.text()}\n")
                f.write(f"auto_date_folder={1 if self.auto_date_folder.isChecked() else 0}\n")
                f.write(f"delete_after_copy={1 if self.delete_after_copy.isChecked() else 0}\n")
            
            self.log_message("Settings saved successfully")
        except Exception as e:
            self.log_message(f"Error saving settings: {str(e)}")
    
    
    def load_settings(self):
        try:
            settings_file = os.path.join(str(Path.home()), ".rpi_transfer", "settings.txt")
            
            if not os.path.exists(settings_file):
                # Auto-detect subnet on first run
                self.auto_detect_subnet()
                return
            
            with open(settings_file, "r") as f:
                for line in f:
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        
                        if key == "hostname":
                            self.hostname_combo.setCurrentText(value)
                        elif key == "username":
                            self.username_input.setText(value)
                        elif key == "remote_dir":
                            self.remote_dir_input.setText(value)
                        elif key == "local_dir":
                            self.local_dir_input.setText(value)
                        elif key == "subnet":
                            self.subnet_input.setText(value)
                        elif key == "auto_date_folder":
                            self.auto_date_folder.setChecked(value == "1")
                        elif key == "delete_after_copy":
                            self.delete_after_copy.setChecked(value == "1")
            
            self.log_message("Settings loaded successfully")
        except Exception as e:
            self.log_message(f"Error loading settings: {str(e)}")
            # Auto-detect subnet on error
            self.auto_detect_subnet()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
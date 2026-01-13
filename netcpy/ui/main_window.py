"""MainWindow - Main application window"""

import os
import datetime
from typing import Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QProgressBar,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QMenu,
    QToolBar,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from netcpy.core.settings_manager import SettingsManager
from netcpy.core.profile_manager import ProfileManager
from netcpy.core.transfer_history import TransferHistory
from netcpy.workers.network_scanner import NetworkScanner
from netcpy.workers.file_preview_worker import FilePreviewWorker
from netcpy.workers.sftp_worker import SftpWorker
from netcpy.ui.dialogs.preview_dialog import PreviewDialog
from netcpy.ui.dialogs.profile_dialog import ProfileDialog
from netcpy.ui.dialogs.settings_dialog import SettingsDialog
from netcpy.utils.formatters import format_file_size


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        """Initialize MainWindow"""
        super().__init__()
        self.setWindowTitle("Network Copy - Raspberry Pi File Transfer")
        self.setGeometry(100, 100, 900, 700)

        # Initialize managers
        self.settings_manager = SettingsManager()
        self.profile_manager = ProfileManager()
        self.transfer_history = TransferHistory()

        # Initialize workers
        self.scanner = None
        self.preview_worker = None
        self.transfer_worker = None

        # Create UI
        self.setup_ui()
        self.setup_menu_bar()
        self.setup_toolbar()

        # Load settings
        self.load_window_state()

    def setup_ui(self):
        """Set up the main UI"""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Connection section
        conn_layout = QVBoxLayout()
        conn_layout.addWidget(QLabel("Device Profile:"))

        profile_select_layout = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self.on_profile_changed)
        profile_select_layout.addWidget(self.profile_combo)

        manage_profiles_btn = QPushButton("Manage")
        manage_profiles_btn.clicked.connect(self.open_profile_dialog)
        profile_select_layout.addWidget(manage_profiles_btn)
        conn_layout.addLayout(profile_select_layout)

        layout.addLayout(conn_layout)

        # Directory section
        dir_layout = QVBoxLayout()
        dir_layout.addWidget(QLabel("Remote Directory:"))
        self.remote_dir_input = QLineEdit()
        self.remote_dir_input.setPlaceholderText("/home/pi/data")
        dir_layout.addWidget(self.remote_dir_input)

        dir_layout.addWidget(QLabel("Local Directory:"))
        local_dir_h = QHBoxLayout()
        self.local_dir_input = QLineEdit()
        local_dir_h.addWidget(self.local_dir_input)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_local_dir)
        local_dir_h.addWidget(browse_btn)
        dir_layout.addLayout(local_dir_h)

        layout.addLayout(dir_layout)

        # Options
        options_layout = QHBoxLayout()
        self.delete_after_check = QCheckBox("Delete files from Raspberry Pi after copying")
        options_layout.addWidget(self.delete_after_check)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Preview button
        preview_layout = QHBoxLayout()
        preview_layout.addStretch()
        self.preview_btn = QPushButton("Preview Files")
        self.preview_btn.clicked.connect(self.start_preview)
        preview_layout.addWidget(self.preview_btn)
        layout.addLayout(preview_layout)

        # Progress section
        progress_layout = QVBoxLayout()
        self.progress_label = QLabel("Ready")
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        layout.addLayout(progress_layout)

        # Log section
        layout.addWidget(QLabel("Log:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)

        # Buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Transfer")
        self.start_btn.clicked.connect(self.start_transfer)
        button_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_current_operation)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.stop_btn)

        button_layout.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings_dialog)
        button_layout.addWidget(settings_btn)

        layout.addLayout(button_layout)

        # Load profiles
        self.refresh_profiles()

    def setup_menu_bar(self):
        """Set up menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        new_profile_action = QAction("New Profile", self)
        new_profile_action.triggered.connect(self.open_profile_dialog)
        file_menu.addAction(new_profile_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Profiles menu
        profiles_menu = menubar.addMenu("Profiles")

        manage_action = QAction("Manage Profiles", self)
        manage_action.triggered.connect(self.open_profile_dialog)
        profiles_menu.addAction(manage_action)

        # Tools menu
        tools_menu = menubar.addMenu("Tools")

        scan_action = QAction("Scan Network", self)
        scan_action.triggered.connect(self.start_network_scan)
        tools_menu.addAction(scan_action)

        tools_menu.addSeparator()

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        tools_menu.addAction(settings_action)

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_toolbar(self):
        """Set up toolbar"""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        scan_action = QAction("Scan Network", self)
        scan_action.triggered.connect(self.start_network_scan)
        toolbar.addAction(scan_action)

        toolbar.addSeparator()

        transfer_action = QAction("Start Transfer", self)
        transfer_action.triggered.connect(self.start_transfer)
        toolbar.addAction(transfer_action)

    def refresh_profiles(self):
        """Refresh profile list"""
        self.profile_combo.clear()

        profiles = self.profile_manager.load_profiles()
        for profile in profiles:
            self.profile_combo.addItem(profile.name or profile.hostname, profile.id)

        if not profiles:
            self.profile_combo.addItem("(No profiles configured)")

    def on_profile_changed(self):
        """Handle profile selection change"""
        if self.profile_combo.count() == 0:
            return

        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return

        profile = self.profile_manager.get_profile(profile_id)
        if profile:
            self.remote_dir_input.setText(profile.remote_dir)
            self.settings_manager.set_last_profile_id(profile_id)

    def browse_local_dir(self):
        """Browse for local directory"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if dir_path:
            self.local_dir_input.setText(dir_path)

    def log_message(self, message: str):
        """Log a message"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def start_network_scan(self):
        """Start network scan"""
        network_range = self.settings_manager.get_network_range()

        if self.scanner and self.scanner.isRunning():
            self.log_message("Scan already in progress")
            return

        self.scanner = NetworkScanner(network_range)
        self.scanner.device_found.connect(self.on_device_found)
        self.scanner.scan_progress.connect(self.on_scan_progress)
        self.scanner.scan_complete.connect(self.on_scan_complete)
        self.scanner.start()

        self.progress_label.setText("Scanning network...")
        self.log_message(f"Starting network scan on {network_range}...")

    def on_device_found(self, ip: str, display_name: str):
        """Handle device found during scan"""
        self.log_message(f"Found device with SSH: {display_name}")

    def on_scan_progress(self, value: int):
        """Handle scan progress"""
        self.progress_bar.setValue(value)
        self.progress_label.setText(f"Scan progress: {value}%")

    def on_scan_complete(self):
        """Handle scan complete"""
        self.progress_label.setText("Scan complete")
        self.log_message("Network scan complete")

    def start_preview(self):
        """Start file preview"""
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            QMessageBox.warning(self, "No Profile", "Please select a device profile")
            return

        profile = self.profile_manager.get_profile(profile_id)
        if not profile:
            QMessageBox.warning(self, "No Profile", "Profile not found")
            return

        remote_dir = self.remote_dir_input.text()
        if not remote_dir:
            QMessageBox.warning(self, "No Directory", "Please enter remote directory")
            return

        local_dir = self.local_dir_input.text()
        if not local_dir:
            QMessageBox.warning(self, "No Directory", "Please select local directory")
            return

        # Start preview worker
        self.preview_worker = FilePreviewWorker(profile.hostname, profile.username, profile.password, remote_dir, local_dir)
        self.preview_worker.status_update.connect(self.log_message)
        self.preview_worker.progress_update.connect(self.progress_bar.setValue)
        self.preview_worker.finished_signal.connect(self.on_preview_complete)

        self.preview_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.progress_label.setText("Analyzing files...")
        self.log_message("Starting file preview...")

        self.preview_worker.start()

    def on_preview_complete(self, success: bool, files: list, message: str):
        """Handle preview complete"""
        self.preview_btn.setEnabled(True)

        if success and files:
            # Show preview dialog
            dialog = PreviewDialog(self, files)
            if dialog.exec() == dialog.Accepted:
                selected_files = dialog.get_selected_files()
                self.log_message(f"Selected {len(selected_files)} files for transfer")

                # Store for transfer
                self._preview_files = selected_files
                self.start_transfer()
        else:
            QMessageBox.warning(self, "Preview Failed", message)
            self.progress_label.setText("Ready")
            self.start_btn.setEnabled(True)

    def start_transfer(self):
        """Start file transfer"""
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            QMessageBox.warning(self, "No Profile", "Please select a device profile")
            return

        profile = self.profile_manager.get_profile(profile_id)
        if not profile:
            QMessageBox.warning(self, "No Profile", "Profile not found")
            return

        remote_dir = self.remote_dir_input.text()
        local_dir = self.local_dir_input.text()

        if not remote_dir or not local_dir:
            QMessageBox.warning(self, "Missing Fields", "Please fill in all required fields")
            return

        # Create date subfolder if option enabled
        if self.settings_manager.get("auto_date_folder", True):
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            local_dir = os.path.join(local_dir, today)

        # Confirm if deleting
        if self.delete_after_check.isChecked():
            reply = QMessageBox.question(
                self,
                "Confirm Deletion",
                "Files will be deleted from Raspberry Pi after copying. Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # Get preview files if available
        files_to_transfer = getattr(self, "_preview_files", None)
        self._preview_files = None

        # Start transfer
        self.transfer_worker = SftpWorker(
            profile.hostname,
            profile.username,
            profile.password,
            remote_dir,
            local_dir,
            files_to_transfer=files_to_transfer,
            delete_after=self.delete_after_check.isChecked(),
        )
        self.transfer_worker.progress_update.connect(self.progress_bar.setValue)
        self.transfer_worker.status_update.connect(self.log_message)
        self.transfer_worker.finished_signal.connect(self.on_transfer_complete)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        self.log_message(f"Starting transfer from {profile.hostname}:{remote_dir} to {local_dir}")
        self.transfer_worker.start()

    def on_transfer_complete(self, success: bool, message: str):
        """Handle transfer complete"""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if success:
            self.log_message(f"Transfer completed: {message}")
            QMessageBox.information(self, "Transfer Complete", message)
        else:
            self.log_message(f"Transfer failed: {message}")
            QMessageBox.critical(self, "Transfer Failed", message)

        self.progress_label.setText("Ready")
        self.progress_bar.setValue(0)

    def stop_current_operation(self):
        """Stop current operation"""
        if self.transfer_worker and self.transfer_worker.isRunning():
            self.transfer_worker.stop()
            self.log_message("Stopping transfer...")
        elif self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.stop()
            self.log_message("Stopping preview...")
        elif self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.log_message("Stopping scan...")

    def open_profile_dialog(self):
        """Open profile management dialog"""
        dialog = ProfileDialog(self, self.profile_manager)
        dialog.exec()
        self.refresh_profiles()

    def open_settings_dialog(self):
        """Open settings dialog"""
        dialog = SettingsDialog(self, self.settings_manager)
        dialog.exec()

    def show_about(self):
        """Show about dialog"""
        QMessageBox.information(
            self, "About Network Copy", "Network Copy v2.0\n\nRaspberry Pi File Transfer Utility\n\n© 2026 Forensic System"
        )

    def load_window_state(self):
        """Load window state from settings"""
        width, height, maximized = self.settings_manager.get_window_geometry()
        self.resize(width, height)
        if maximized:
            self.showMaximized()

    def closeEvent(self, event):
        """Handle window close"""
        # Save window state
        self.settings_manager.set_window_geometry(self.width(), self.height(), self.isMaximized())

        # Stop any running operations
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
        if self.transfer_worker and self.transfer_worker.isRunning():
            self.transfer_worker.stop()
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.stop()

        event.accept()

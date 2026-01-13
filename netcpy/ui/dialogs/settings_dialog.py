"""SettingsDialog - Application settings management"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from netcpy.core.settings_manager import SettingsManager
from netcpy.utils.validators import validate_network_range


class SettingsDialog(QDialog):
    """Dialog for application settings"""

    def __init__(self, parent, settings_manager: SettingsManager):
        """Initialize SettingsDialog

        Args:
            parent: Parent widget
            settings_manager: SettingsManager instance
        """
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)
        self.settings_manager = settings_manager

        self.setup_ui()
        self.load_settings()

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()

        # Create tabbed interface
        tabs = QTabWidget()

        # General tab
        general_tab = self.create_general_tab()
        tabs.addTab(general_tab, "General")

        # Network tab
        network_tab = self.create_network_tab()
        tabs.addTab(network_tab, "Network")

        # Transfer tab
        transfer_tab = self.create_transfer_tab()
        tabs.addTab(transfer_tab, "Transfer")

        layout.addWidget(tabs)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def create_general_tab(self) -> QWidget:
        """Create the general settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("General Settings"))

        self.auto_date_folder_check = QCheckBox("Create date-based subfolder for transferred files")
        layout.addWidget(self.auto_date_folder_check)

        self.auto_scan_startup_check = QCheckBox("Auto-scan network on startup")
        layout.addWidget(self.auto_scan_startup_check)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_network_tab(self) -> QWidget:
        """Create the network settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Network Settings"))

        layout.addWidget(QLabel("Default Network Range:"))
        self.network_range_input = QLineEdit()
        self.network_range_input.setPlaceholderText("e.g., 192.168.1.0/24")
        layout.addWidget(self.network_range_input)

        layout.addWidget(QLabel("Scan Timeout (seconds):"))
        self.scan_timeout_spin = QSpinBox()
        self.scan_timeout_spin.setMinimum(1)
        self.scan_timeout_spin.setMaximum(30)
        self.scan_timeout_spin.setValue(10)
        layout.addWidget(self.scan_timeout_spin)

        layout.addWidget(QLabel("Thread Count:"))
        self.thread_count_spin = QSpinBox()
        self.thread_count_spin.setMinimum(10)
        self.thread_count_spin.setMaximum(200)
        self.thread_count_spin.setValue(50)
        layout.addWidget(self.thread_count_spin)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_transfer_tab(self) -> QWidget:
        """Create the transfer settings tab"""
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Transfer Settings"))

        layout.addWidget(QLabel("Buffer Size (KB):"))
        self.buffer_size_spin = QSpinBox()
        self.buffer_size_spin.setMinimum(1)
        self.buffer_size_spin.setMaximum(10000)
        self.buffer_size_spin.setValue(256)
        layout.addWidget(self.buffer_size_spin)

        layout.addWidget(QLabel("Transfer History Retention (days):"))
        self.history_retention_spin = QSpinBox()
        self.history_retention_spin.setMinimum(1)
        self.history_retention_spin.setMaximum(365)
        self.history_retention_spin.setValue(90)
        layout.addWidget(self.history_retention_spin)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def load_settings(self):
        """Load settings from manager"""
        settings = self.settings_manager.load_settings()

        self.auto_date_folder_check.setChecked(settings.get("auto_date_folder", True))
        self.auto_scan_startup_check.setChecked(settings.get("auto_scan_on_startup", False))
        self.network_range_input.setText(settings.get("network_range", "192.168.1.0/24"))

    def save_settings(self):
        """Save settings to manager"""
        from PySide6.QtWidgets import QMessageBox

        # Validate network range
        valid, msg = validate_network_range(self.network_range_input.text())
        if not valid:
            QMessageBox.warning(self, "Invalid Network Range", msg)
            return

        settings = {
            "auto_date_folder": self.auto_date_folder_check.isChecked(),
            "auto_scan_on_startup": self.auto_scan_startup_check.isChecked(),
            "network_range": self.network_range_input.text(),
        }

        self.settings_manager.save_settings(settings)
        QMessageBox.information(self, "Saved", "Settings saved successfully")
        self.accept()

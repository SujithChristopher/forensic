"""ProfileDialog - Device profile management (create, edit, delete, test connection)"""

from typing import Optional
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QInputDialog,
    QWidget,
)
from PySide6.QtCore import Qt
import paramiko

from netcpy.models.device_profile import DeviceProfile
from netcpy.core.profile_manager import ProfileManager
from netcpy.utils.validators import validate_connection_settings, validate_profile_name


class ProfileDialog(QDialog):
    """Dialog for managing device profiles"""

    def __init__(self, parent, profile_manager: ProfileManager):
        """Initialize ProfileDialog

        Args:
            parent: Parent widget
            profile_manager: ProfileManager instance
        """
        super().__init__(parent)
        self.setWindowTitle("Manage Device Profiles")
        self.setMinimumSize(700, 500)
        self.profile_manager = profile_manager
        self.current_profile: Optional[DeviceProfile] = None

        self.setup_ui()
        self.load_profiles()

    def setup_ui(self):
        """Set up the dialog UI"""
        main_layout = QVBoxLayout()

        # Left side: Profile list
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Profiles:"))

        self.profile_list = QListWidget()
        self.profile_list.itemSelectionChanged.connect(self.on_profile_selected)
        left_layout.addWidget(self.profile_list)

        left_buttons = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.create_profile)
        left_buttons.addWidget(new_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self.delete_profile)
        left_buttons.addWidget(delete_btn)

        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self.duplicate_profile)
        left_buttons.addWidget(duplicate_btn)

        left_layout.addLayout(left_buttons)

        # Right side: Profile details form
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Profile Details:"))

        right_layout.addWidget(QLabel("Name:"))
        self.name_input = QLineEdit()
        self.name_input.textChanged.connect(self.on_field_changed)
        right_layout.addWidget(self.name_input)

        right_layout.addWidget(QLabel("Hostname/IP:"))
        self.hostname_input = QLineEdit()
        self.hostname_input.textChanged.connect(self.on_field_changed)
        right_layout.addWidget(self.hostname_input)

        right_layout.addWidget(QLabel("Username:"))
        self.username_input = QLineEdit()
        self.username_input.textChanged.connect(self.on_field_changed)
        right_layout.addWidget(self.username_input)

        right_layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.textChanged.connect(self.on_field_changed)
        right_layout.addWidget(self.password_input)

        right_layout.addWidget(QLabel("Remote Directory:"))
        self.remote_dir_input = QLineEdit()
        self.remote_dir_input.textChanged.connect(self.on_field_changed)
        right_layout.addWidget(self.remote_dir_input)

        # Statistics display
        right_layout.addSpacing(10)
        right_layout.addWidget(QLabel("Statistics:"))

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        right_layout.addWidget(self.stats_label)

        # Test connection button
        right_layout.addSpacing(10)
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_connection)
        right_layout.addWidget(test_btn)

        right_layout.addStretch()

        # Combine left and right in horizontal layout
        content_layout = QHBoxLayout()
        content_layout.addLayout(left_layout, 1)
        content_layout.addLayout(right_layout, 2)

        main_layout.addLayout(content_layout)

        # Bottom buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_profile)
        button_layout.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def load_profiles(self):
        """Load and display all profiles"""
        self.profile_list.clear()

        profiles = self.profile_manager.load_profiles()
        for profile in profiles:
            item = QListWidgetItem(profile.name or profile.hostname)
            item.setData(Qt.UserRole, profile.id)
            self.profile_list.addItem(item)

        if profiles:
            self.profile_list.setCurrentRow(0)
            self.on_profile_selected()

    def on_profile_selected(self):
        """Handle profile selection"""
        current_item = self.profile_list.currentItem()
        if not current_item:
            return

        profile_id = current_item.data(Qt.UserRole)
        self.current_profile = self.profile_manager.get_profile(profile_id)

        if self.current_profile:
            self.name_input.setText(self.current_profile.name or "")
            self.hostname_input.setText(self.current_profile.hostname)
            self.username_input.setText(self.current_profile.username)
            self.password_input.setText(self.current_profile.password)
            self.remote_dir_input.setText(self.current_profile.remote_dir)

            # Update statistics
            self.update_statistics()

    def on_field_changed(self):
        """Handle field changes"""
        if self.current_profile:
            self.current_profile.name = self.name_input.text()
            self.current_profile.hostname = self.hostname_input.text()
            self.current_profile.username = self.username_input.text()
            self.current_profile.password = self.password_input.text()
            self.current_profile.remote_dir = self.remote_dir_input.text()

    def update_statistics(self):
        """Update statistics display for current profile"""
        if not self.current_profile:
            self.stats_label.setText("")
            return

        stats = (
            f"Transfers: {self.current_profile.total_transfers}\n"
            f"Files: {self.current_profile.total_files_transferred}\n"
            f"Data: {self.current_profile.total_bytes_transferred} bytes"
        )
        self.stats_label.setText(stats)

    def create_profile(self):
        """Create a new profile"""
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok or not name:
            return

        # Validate name
        valid, msg = validate_profile_name(name)
        if not valid:
            QMessageBox.warning(self, "Invalid Name", msg)
            return

        profile = DeviceProfile(
            hostname="",
            username="pi",
            password="",
            name=name,
        )

        self.profile_manager.create_profile(profile)
        self.load_profiles()

        # Select the new profile
        for i in range(self.profile_list.count()):
            if self.profile_list.item(i).data(Qt.UserRole) == profile.id:
                self.profile_list.setCurrentRow(i)
                break

    def delete_profile(self):
        """Delete the current profile"""
        if not self.current_profile:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete profile '{self.current_profile.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.profile_manager.delete_profile(self.current_profile.id)
            self.load_profiles()

    def duplicate_profile(self):
        """Duplicate the current profile"""
        if not self.current_profile:
            return

        name, ok = QInputDialog.getText(self, "Duplicate Profile", "New profile name:")
        if not ok or not name:
            return

        # Validate name
        valid, msg = validate_profile_name(name)
        if not valid:
            QMessageBox.warning(self, "Invalid Name", msg)
            return

        new_profile = self.profile_manager.duplicate_profile(self.current_profile.id, name)
        if new_profile:
            self.load_profiles()

            # Select the new profile
            for i in range(self.profile_list.count()):
                if self.profile_list.item(i).data(Qt.UserRole) == new_profile.id:
                    self.profile_list.setCurrentRow(i)
                    break

    def test_connection(self):
        """Test connection to the current profile"""
        if not self.current_profile:
            QMessageBox.warning(self, "No Profile", "Please select a profile first")
            return

        # Validate settings
        valid, msg = validate_connection_settings(
            self.current_profile.hostname, self.current_profile.username, self.current_profile.password
        )
        if not valid:
            QMessageBox.warning(self, "Invalid Settings", msg)
            return

        # Try to connect
        try:
            transport = paramiko.Transport((self.current_profile.hostname, 22))
            transport.connect(username=self.current_profile.username, password=self.current_profile.password)
            transport.close()

            QMessageBox.information(
                self, "Connection Successful", f"Successfully connected to {self.current_profile.hostname}"
            )
        except paramiko.AuthenticationException:
            QMessageBox.critical(self, "Connection Failed", "Authentication failed. Check username and password.")
        except paramiko.SSHException as e:
            QMessageBox.critical(self, "Connection Failed", f"SSH error: {str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", f"Error: {str(e)}")

    def save_profile(self):
        """Save the current profile"""
        if not self.current_profile:
            return

        # Validate settings
        valid, msg = validate_connection_settings(
            self.current_profile.hostname, self.current_profile.username, self.current_profile.password
        )
        if not valid:
            QMessageBox.warning(self, "Invalid Settings", msg)
            return

        self.profile_manager.save_profile(self.current_profile)
        QMessageBox.information(self, "Saved", "Profile saved successfully")

        # Refresh the list
        self.load_profiles()

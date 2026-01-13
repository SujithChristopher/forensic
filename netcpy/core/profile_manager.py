"""ProfileManager - Handles device profile CRUD operations and password encryption"""

import json
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from cryptography.fernet import Fernet

from netcpy.models.device_profile import DeviceProfile


class ProfileManager:
    """Manages device profiles with CRUD operations and password encryption"""

    def __init__(self, profiles_dir: Optional[Path] = None):
        """Initialize ProfileManager

        Args:
            profiles_dir: Directory to store profiles. Defaults to ~/.rpi_transfer
        """
        self.profiles_dir = profiles_dir or Path.home() / ".rpi_transfer"
        self.profiles_file = self.profiles_dir / "profiles.json"
        self.key_file = self.profiles_dir / ".key"

        # Ensure directory exists
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Initialize or load encryption key
        self._cipher = self._get_or_create_cipher()

        # Load profiles
        self._profiles: dict[str, DeviceProfile] = self._load_profiles()

    def _get_or_create_cipher(self) -> Fernet:
        """Get or create encryption cipher for password encryption

        Returns:
            Fernet cipher instance
        """
        if self.key_file.exists():
            try:
                with open(self.key_file, "rb") as f:
                    key = f.read()
                return Fernet(key)
            except Exception as e:
                print(f"Error loading encryption key: {e}")

        # Create new key
        key = Fernet.generate_key()
        try:
            # Save with restricted permissions
            with open(self.key_file, "wb") as f:
                f.write(key)
            # Set restrictive permissions (owner read/write only)
            os.chmod(self.key_file, 0o600)
        except Exception as e:
            print(f"Error saving encryption key: {e}")

        return Fernet(key)

    def _encrypt_password(self, password: str) -> str:
        """Encrypt a password

        Args:
            password: Plain text password

        Returns:
            Encrypted password (base64 encoded)
        """
        if not password:
            return ""
        encrypted = self._cipher.encrypt(password.encode())
        return encrypted.decode()

    def _decrypt_password(self, encrypted_password: str) -> str:
        """Decrypt a password

        Args:
            encrypted_password: Encrypted password (base64 encoded)

        Returns:
            Plain text password
        """
        if not encrypted_password:
            return ""
        try:
            decrypted = self._cipher.decrypt(encrypted_password.encode())
            return decrypted.decode()
        except Exception as e:
            print(f"Error decrypting password: {e}")
            return ""

    def _load_profiles(self) -> dict[str, DeviceProfile]:
        """Load all profiles from JSON file

        Returns:
            Dictionary of profile_id -> DeviceProfile
        """
        if not self.profiles_file.exists():
            return {}

        try:
            with open(self.profiles_file, "r") as f:
                data = json.load(f)

            profiles = {}
            for profile_data in data.get("profiles", []):
                # Decrypt password
                if "password" in profile_data and profile_data["password"]:
                    profile_data["password"] = self._decrypt_password(profile_data["password"])

                profile = DeviceProfile.from_dict(profile_data)
                profiles[profile.id] = profile

            return profiles

        except Exception as e:
            print(f"Error loading profiles: {e}")
            return {}

    def _save_profiles(self):
        """Save all profiles to JSON file"""
        try:
            profiles_data = []
            for profile in self._profiles.values():
                data = profile.to_dict()
                # Encrypt password before saving
                if data["password"]:
                    data["password"] = self._encrypt_password(data["password"])
                profiles_data.append(data)

            with open(self.profiles_file, "w") as f:
                json.dump({"version": "1.0", "profiles": profiles_data}, f, indent=2)

        except Exception as e:
            print(f"Error saving profiles: {e}")

    def load_profiles(self) -> List[DeviceProfile]:
        """Load all profiles sorted by last used

        Returns:
            List of DeviceProfile objects, sorted by last_used (newest first)
        """
        profiles = list(self._profiles.values())
        profiles.sort(key=lambda p: p.last_used or datetime.min, reverse=True)
        return profiles

    def get_profile(self, profile_id: str) -> Optional[DeviceProfile]:
        """Get a specific profile by ID

        Args:
            profile_id: Profile ID

        Returns:
            DeviceProfile or None if not found
        """
        return self._profiles.get(profile_id)

    def create_profile(self, profile: DeviceProfile) -> DeviceProfile:
        """Create a new profile

        Args:
            profile: DeviceProfile to create

        Returns:
            Created profile with ID set
        """
        self._profiles[profile.id] = profile
        self._save_profiles()
        return profile

    def save_profile(self, profile: DeviceProfile):
        """Save/update a profile

        Args:
            profile: DeviceProfile to save
        """
        self._profiles[profile.id] = profile
        self._save_profiles()

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a profile

        Args:
            profile_id: ID of profile to delete

        Returns:
            True if deleted, False if not found
        """
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            self._save_profiles()
            return True
        return False

    def duplicate_profile(self, profile_id: str, new_name: str) -> Optional[DeviceProfile]:
        """Duplicate a profile with a new name

        Args:
            profile_id: ID of profile to duplicate
            new_name: Name for the new profile

        Returns:
            New profile or None if source not found
        """
        source = self.get_profile(profile_id)
        if not source:
            return None

        # Create new profile with same settings
        new_profile = DeviceProfile(
            hostname=source.hostname,
            username=source.username,
            password=source.password,
            name=new_name,
            remote_dir=source.remote_dir,
        )

        return self.create_profile(new_profile)

    def update_statistics(self, profile_id: str, files_count: int, bytes_count: int, success: bool = True):
        """Update profile statistics after a transfer

        Args:
            profile_id: Profile ID
            files_count: Number of files transferred
            bytes_count: Total bytes transferred
            success: Whether transfer was successful
        """
        profile = self.get_profile(profile_id)
        if profile:
            profile.update_statistics(files_count, bytes_count, success)
            self.save_profile(profile)

    def get_default_profile(self) -> Optional[DeviceProfile]:
        """Get a default profile (first one if available)

        Returns:
            First profile or None
        """
        profiles = self.load_profiles()
        return profiles[0] if profiles else None

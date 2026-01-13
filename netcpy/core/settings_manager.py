"""SettingsManager - Handles application settings persistence and migration"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime


class SettingsManager:
    """Manages application settings with JSON storage and migration from legacy format"""

    DEFAULT_SETTINGS = {
        "version": "2.0",
        "window": {
            "width": 900,
            "height": 700,
            "maximized": False,
        },
        "last_profile_id": None,
        "auto_date_folder": True,
        "network_range": "192.168.1.0/24",
        "auto_scan_on_startup": False,
    }

    def __init__(self, settings_dir: Optional[Path] = None):
        """Initialize SettingsManager

        Args:
            settings_dir: Directory to store settings. Defaults to ~/.rpi_transfer
        """
        self.settings_dir = settings_dir or Path.home() / ".rpi_transfer"
        self.settings_file = self.settings_dir / "settings.json"
        self.legacy_file = self.settings_dir / "settings.txt"

        # Ensure settings directory exists
        self.settings_dir.mkdir(parents=True, exist_ok=True)

        # Load settings, migrating if necessary
        self._settings = self._load_or_migrate_settings()

    def _load_or_migrate_settings(self) -> Dict[str, Any]:
        """Load settings from JSON, or migrate from legacy format if needed"""

        # Try loading from new JSON format
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
                    # Ensure all default keys exist
                    self._merge_defaults(settings)
                    return settings
            except Exception as e:
                print(f"Error loading settings: {e}")

        # Check if legacy settings.txt exists
        if self.legacy_file.exists():
            return self._migrate_from_legacy()

        # Use default settings
        settings = self.DEFAULT_SETTINGS.copy()
        self.save_settings(settings)
        return settings

    def _migrate_from_legacy(self) -> Dict[str, Any]:
        """Migrate from legacy settings.txt format to new JSON format

        Returns:
            Dict of settings, also saves to JSON file
        """
        settings = self.DEFAULT_SETTINGS.copy()

        try:
            with open(self.legacy_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    # Map old settings to new format
                    if key == "network_range" or key == "subnet":
                        settings["network_range"] = value
                    elif key == "auto_date_folder":
                        settings["auto_date_folder"] = value.lower() in ("1", "true", "yes")
                    elif key == "auto_scan_on_startup":
                        settings["auto_scan_on_startup"] = value.lower() in ("1", "true", "yes")

            # Backup legacy file
            backup_file = self.legacy_file.with_suffix(".txt.backup")
            self.legacy_file.rename(backup_file)
            print(f"Migrated settings from {self.legacy_file} to {self.settings_file}")
            print(f"Legacy file backed up to {backup_file}")

            # Save new format
            self.save_settings(settings)
            return settings

        except Exception as e:
            print(f"Error migrating settings: {e}")
            return self.DEFAULT_SETTINGS.copy()

    def _merge_defaults(self, settings: Dict[str, Any]):
        """Merge default settings with loaded settings to ensure all keys exist"""
        for key, value in self.DEFAULT_SETTINGS.items():
            if key not in settings:
                settings[key] = value
            elif isinstance(value, dict) and isinstance(settings[key], dict):
                # Recursively merge nested dictionaries
                for subkey, subvalue in value.items():
                    if subkey not in settings[key]:
                        settings[key][subkey] = subvalue

    def load_settings(self) -> Dict[str, Any]:
        """Load all settings

        Returns:
            Dictionary of all settings
        """
        return self._settings.copy()

    def save_settings(self, settings: Dict[str, Any]):
        """Save settings to JSON file

        Args:
            settings: Dictionary of settings to save
        """
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
            self._settings = settings.copy()
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value

        Args:
            key: Setting key (supports dot notation for nested keys, e.g., "window.width")
            default: Default value if key not found

        Returns:
            Setting value or default
        """
        keys = key.split(".")
        value = self._settings

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any):
        """Set a setting value

        Args:
            key: Setting key (supports dot notation for nested keys)
            value: Value to set
        """
        keys = key.split(".")

        # Navigate to parent
        current = self._settings
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        # Set value
        current[keys[-1]] = value

        # Save to file
        self.save_settings(self._settings)

    def get_last_profile_id(self) -> Optional[str]:
        """Get ID of the last used profile"""
        return self.get("last_profile_id")

    def set_last_profile_id(self, profile_id: str):
        """Set the last used profile ID"""
        self.set("last_profile_id", profile_id)

    def get_window_geometry(self) -> tuple:
        """Get saved window geometry

        Returns:
            Tuple of (width, height, maximized)
        """
        window = self.get("window", {})
        return (
            window.get("width", 900),
            window.get("height", 700),
            window.get("maximized", False),
        )

    def set_window_geometry(self, width: int, height: int, maximized: bool):
        """Save window geometry"""
        self.set("window", {"width": width, "height": height, "maximized": maximized})

    def get_network_range(self) -> str:
        """Get default network range for scanning"""
        return self.get("network_range", "192.168.1.0/24")

    def set_network_range(self, network_range: str):
        """Set default network range"""
        self.set("network_range", network_range)

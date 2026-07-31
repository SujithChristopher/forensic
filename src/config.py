"""Exposure configuration: loads exposure.toml and answers time-of-day questions.

Owns the time-based exposure schedule and the day/night boundary logic. Auto-exposure
tuning overrides found in the file are exposed via ``auto_exposure_overrides`` so the
ExposureController can apply only the keys the user actually set (defaults otherwise).
"""

import os
from datetime import datetime

import tomli  # For reading TOML files


def default_settings():
    """Fresh copy of the built-in defaults (never mutate a shared global)."""
    return {
        "time_exposures": [
            {"hour": 0, "minute": 0, "exposure": 500000},   # Midnight (12 AM) - high exposure
            {"hour": 6, "minute": 0, "exposure": 100000},   # 6 AM - medium exposure
            {"hour": 8, "minute": 0, "exposure": 20000},    # 8 AM - lower exposure
            {"hour": 17, "minute": 0, "exposure": 50000},   # 5 PM - medium exposure
            {"hour": 19, "minute": 0, "exposure": 300000},  # 7 PM - higher exposure
            {"hour": 22, "minute": 0, "exposure": 500000},  # 10 PM - high exposure
        ],
        "day": {
            "start_hour": 6,
            "end_hour": 18,
        },
        "auto_exposure": {
            "target_brightness": 120,
            "min_exposure": 5000,
            "max_exposure": 1000000,
            "tolerance": 10,
            "max_clip_pct": 2.0,
        },
    }


class ExposureConfig:
    """Reads exposure settings from a TOML file with sane fallbacks."""

    def __init__(self, config_file):
        self.config_file = config_file
        # auto_exposure_overrides is only populated when the file actually contains an
        # [exposure.auto_exposure] section — otherwise the controller keeps its defaults.
        self.settings, self.auto_exposure_overrides = self._load()

    def _load(self):
        defaults = default_settings()
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "rb") as f:
                    config = tomli.load(f)

                settings = {}
                overrides = None

                # Time-based exposure settings
                if "exposure" in config and "time_exposures" in config["exposure"]:
                    settings["time_exposures"] = config["exposure"]["time_exposures"]
                else:
                    settings["time_exposures"] = defaults["time_exposures"]
                    print("No time-based exposure settings found, using defaults")

                # Day/night definitions for LED control
                if "exposure" in config and "day" in config["exposure"]:
                    settings["day"] = config["exposure"]["day"]
                else:
                    settings["day"] = defaults["day"]

                # Auto-exposure settings (only override the controller if present in file)
                if "exposure" in config and "auto_exposure" in config["exposure"]:
                    settings["auto_exposure"] = config["exposure"]["auto_exposure"]
                    overrides = settings["auto_exposure"]
                else:
                    settings["auto_exposure"] = defaults["auto_exposure"]

                # Sort time exposures by time-of-day for efficient lookup
                settings["time_exposures"].sort(key=lambda x: x["hour"] * 60 + x["minute"])

                print(f"Loaded {len(settings['time_exposures'])} exposure time settings "
                      f"from {self.config_file}")
                return settings, overrides

            print(f"No valid config file found at {self.config_file}, using default exposure settings")
            return defaults, None

        except Exception as e:
            print(f"Error loading exposure settings: {e}")
            print("Using default exposure settings")
            return defaults, None

    @property
    def time_exposures(self):
        return self.settings["time_exposures"]

    @property
    def day(self):
        return self.settings["day"]

    def is_night_time(self):
        """Check if the current time is between the night hours defined in config."""
        current_hour = datetime.now().hour
        day_start = self.settings["day"]["start_hour"]
        day_end = self.settings["day"]["end_hour"]

        if day_start <= day_end:
            # Simple case: day is within same calendar day
            return current_hour < day_start or current_hour >= day_end
        else:
            # Complex case: day spans across midnight
            return current_hour >= day_end and current_hour < day_start

    def get_current_exposure_time(self):
        """Get the exposure time based on the current time of day from TOML settings."""
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute

        time_exposures = self.settings["time_exposures"]

        # Default to the last exposure value if no match is found
        exposure_value = time_exposures[-1]["exposure"]

        # Find the appropriate exposure setting based on current time
        # (relies on the settings being sorted by time)
        for i, setting in enumerate(time_exposures):
            setting_minutes = setting["hour"] * 60 + setting["minute"]

            if i == len(time_exposures) - 1 or current_minutes < (
                time_exposures[i + 1]["hour"] * 60 + time_exposures[i + 1]["minute"]
            ):
                if current_minutes >= setting_minutes:
                    exposure_value = setting["exposure"]
                    break
                elif i > 0:
                    exposure_value = time_exposures[i - 1]["exposure"]
                    break

        return exposure_value

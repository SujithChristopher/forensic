import os
import tomli

DEFAULT_SETTINGS = {
    "time_exposures": [
        {"hour": 0, "minute": 0, "exposure": 500000},
        {"hour": 6, "minute": 0, "exposure": 100000},
        {"hour": 8, "minute": 0, "exposure": 20000},
        {"hour": 17, "minute": 0, "exposure": 50000},
        {"hour": 19, "minute": 0, "exposure": 300000},
        {"hour": 22, "minute": 0, "exposure": 500000},
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
    },
}


def load_exposure_settings(config_file):
    """Load exposure settings from TOML file. Returns settings dict."""
    try:
        if os.path.exists(config_file):
            with open(config_file, "rb") as f:
                config = tomli.load(f)

            settings = {}

            if "exposure" in config and "time_exposures" in config["exposure"]:
                settings["time_exposures"] = config["exposure"]["time_exposures"]
            else:
                settings["time_exposures"] = DEFAULT_SETTINGS["time_exposures"]
                print("No time-based exposure settings found, using defaults")

            if "exposure" in config and "day" in config["exposure"]:
                settings["day"] = config["exposure"]["day"]
            else:
                settings["day"] = DEFAULT_SETTINGS["day"]

            if "exposure" in config and "auto_exposure" in config["exposure"]:
                settings["auto_exposure"] = config["exposure"]["auto_exposure"]
            else:
                settings["auto_exposure"] = DEFAULT_SETTINGS["auto_exposure"]

            settings["time_exposures"].sort(key=lambda x: x["hour"] * 60 + x["minute"])
            print(f"Loaded {len(settings['time_exposures'])} exposure time settings from {config_file}")
            return settings

        print(f"No valid config file found at {config_file}, using default exposure settings")
        return DEFAULT_SETTINGS

    except Exception as e:
        print(f"Error loading exposure settings: {e}")
        print("Using default exposure settings")
        return DEFAULT_SETTINGS

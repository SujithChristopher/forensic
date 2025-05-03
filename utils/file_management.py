import tomli
import os
from datetime import datetime

class file_manager():
    def __init__(self, file_path):
        self.file_path = file_path
        
    def load_exposure_settings(self):
        """Load exposure settings from TOML file"""
        # Default exposure settings if no file is found
        default_settings = {
            "time_exposures": [
                {"hour": 0, "minute": 0, "exposure": 500000},  # Midnight (12 AM) - high exposure
                {"hour": 6, "minute": 0, "exposure": 100000},  # 6 AM - medium exposure
                {"hour": 8, "minute": 0, "exposure": 20000},   # 8 AM - lower exposure
                {"hour": 17, "minute": 0, "exposure": 50000},  # 5 PM - medium exposure
                {"hour": 19, "minute": 0, "exposure": 300000}, # 7 PM - higher exposure
                {"hour": 22, "minute": 0, "exposure": 500000}  # 10 PM - high exposure
            ],
            "day": {
                "start_hour": 6,
                "end_hour": 18
            },
            "auto_exposure": {
                "target_brightness": 120,
                "min_exposure": 5000,
                "max_exposure": 1000000,
                "tolerance": 10
            }
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "rb") as f:
                    config = tomli.load(f)
                
                # Extract time-based exposure settings
                settings = {}
                
                # Get time-based exposure settings
                if "exposure" in config and "time_exposures" in config["exposure"]:
                    settings["time_exposures"] = config["exposure"]["time_exposures"]
                else:
                    settings["time_exposures"] = default_settings["time_exposures"]
                    print("No time-based exposure settings found, using defaults")
                
                # Get day/night definitions for LED control
                if "exposure" in config and "day" in config["exposure"]:
                    settings["day"] = config["exposure"]["day"]
                else:
                    settings["day"] = default_settings["day"]
                
                # Get auto-exposure settings if they exist
                if "exposure" in config and "auto_exposure" in config["exposure"]:
                    settings["auto_exposure"] = config["exposure"]["auto_exposure"]
                    # Update instance variables from config
                    if "target_brightness" in settings["auto_exposure"]:
                        self.target_brightness = settings["auto_exposure"]["target_brightness"]
                    if "min_exposure" in settings["auto_exposure"]:
                        self.min_exposure = settings["auto_exposure"]["min_exposure"]
                    if "max_exposure" in settings["auto_exposure"]:
                        self.max_exposure = settings["auto_exposure"]["max_exposure"]
                    if "tolerance" in settings["auto_exposure"]:
                        self.brightness_tolerance = settings["auto_exposure"]["tolerance"]
                else:
                    settings["auto_exposure"] = default_settings["auto_exposure"]
                    
                # Sort time exposures by hour and minute for efficient lookup
                settings["time_exposures"].sort(key=lambda x: x["hour"] * 60 + x["minute"])
                
                print(f"Loaded {len(settings['time_exposures'])} exposure time settings from {self.config_file}")
                return settings
            
            print(f"No valid config file found at {self.config_file}, using default exposure settings")
            return default_settings
            
        except Exception as e:
            print(f"Error loading exposure settings: {e}")
            print("Using default exposure settings")
            return default_settings
        
    def get_current_exposure_time(self):
        """Get the exposure time based on current time of day from TOML settings"""
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        
        # Get time-based exposures
        time_exposures = self.exposure_settings["time_exposures"]
        
        # Default to the last exposure value if no match is found
        exposure_value = time_exposures[-1]["exposure"]
        
        # Find the appropriate exposure setting based on current time
        # This uses the fact that settings are sorted by time
        for i, setting in enumerate(time_exposures):
            setting_minutes = setting["hour"] * 60 + setting["minute"]
            
            # If this is the last entry or current time is before the next entry
            if i == len(time_exposures) - 1 or current_minutes < (time_exposures[i+1]["hour"] * 60 + time_exposures[i+1]["minute"]):
                if current_minutes >= setting_minutes:
                    exposure_value = setting["exposure"]
                    break
                elif i > 0:
                    # Use previous setting if current time is before the first matching setting
                    exposure_value = time_exposures[i-1]["exposure"]
                    break
            
        return exposure_value
    
    def _update_day_paths(self):
        """Update paths for the current day"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        self.day_str = f"day{(datetime.now() - datetime(2025, 4, 7)).days + 1}"
        
        # Create day directory for images
        self.day_dir = os.path.join(self.data_dir, self.day_str)
        if not os.path.exists(self.day_dir):
            os.makedirs(self.day_dir)
            
        # Set up CSV file for temperature data
        self.csv_filename = os.path.join(self.day_dir, f"temp_data_{current_date}.csv")
        
        # Set up CSV file for exposure data
        self.exposure_csv = os.path.join(self.day_dir, f"exposure_data_{current_date}.csv")
        
        # Set up CSV file for image quality metrics
        self.quality_csv = os.path.join(self.day_dir, f"image_quality_{current_date}.csv")
        
        # Create temperature CSV with headers if it doesn't exist
        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, 'w', newline='') as f:
                writer = csv.writer(f)
                # Create header with timestamp and sensor1 through sensor4
                header = ['timestamp'] + [f'sensor{i+1}' for i in range(self.num_sensors)]
                writer.writerow(header)
        
        # Create exposure CSV with headers if it doesn't exist
        if not os.path.exists(self.exposure_csv):
            with open(self.exposure_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ['timestamp', 'initial_exposure', 'final_exposure', 'avg_brightness', 'contrast', 'led_used']
                writer.writerow(header)
                
        # Create image quality CSV with headers if it doesn't exist
        if not os.path.exists(self.quality_csv):
            with open(self.quality_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ['timestamp', 'filename', 'avg_brightness', 'contrast', 'histogram_std', 'exposure_time']
                writer.writerow(header)
import os
import glob
import time
import cv2
import platform
import csv
import tomli  # For reading TOML files
class DataRecorder():
    def __init__(self):
        if platform.system() == "Linux":
            self.frame_size = (1280, 720)
            self._init_rpi_camera()
        else:
            self._init_camera()



    def _init_rpi_camera(self):
        from picamera2 import Picamera2
        # Flag to control LED usage based on time of day (night only)
        self.night_led_only = night_led_only
        
        # Flag to enable auto-exposure feature
        self.auto_exposure = auto_exposure
        
        # Target brightness level for auto-exposure (0-255)
        self.target_brightness = 120  # Medium brightness
        
        # Brightness tolerance (how close we need to get to target)
        self.brightness_tolerance = 15
        
        # Max number of attempts for auto-exposure
        self.max_exposure_attempts = 5
        
        # Exposure adjustment factors
        self.min_exposure = 5000    # Minimum exposure time (microseconds)
        self.max_exposure = 1000000  # Maximum exposure time (microseconds)
        
        # Load camera settings from TOML file
        self.config_file = config_file
        self.exposure_settings = self.load_exposure_settings()
        print(device_folders)
        return [folder + '/w1_slave' for folder in device_folders]

    def read_temp_raw(self, device_file):
        with open(device_file, 'r') as f:
            return f.readlines()

    def read_temp(self, device_file):
        lines = self.read_temp_raw(device_file)

        while lines[0].strip()[-3:] != 'YES':
            time.sleep(1)
            lines = self.read_temp_raw(device_file)
        
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
        # Number of temperature sensors to use
        self.num_sensors = 4
            
        # Initialize day-specific paths
        self._update_day_paths()
        
        # Last image capture timestamp
        self.last_image_time = 0
        
        # Store last used exposure time for logging
        self.last_exposure_time = self.get_current_exposure_time()
    
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
                "tolerance": 15
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
    
    def _init_led(self):
        """Initialize LED control"""
        try:
            import gpiod
            self.LED_PIN = 27
            self.chip = gpiod.Chip('gpiochip4')
            self.led_line = self.chip.get_line(self.LED_PIN)
            self.led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
            print("LED initialized successfully")
        except Exception as e:
            print(f"Error initializing LED: {e}")
            self.use_led = False
    
    def is_night_time(self):
        """Check if current time is between night hours defined in config"""
        current_hour = datetime.now().hour
        day_start = self.exposure_settings["day"]["start_hour"]
        day_end = self.exposure_settings["day"]["end_hour"]
        
        # If it's not daytime, it's nighttime
        if day_start <= day_end:
            # Simple case: day is within same calendar day
            return current_hour < day_start or current_hour >= day_end
        else:
            # Complex case: day spans across midnight
            return current_hour >= day_end and current_hour < day_start
    
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
    
    def should_use_led(self):
        """Determine if LED should be used based on time of day settings"""
        if not self.use_led:
            return False
        
        if self.night_led_only:
            return self.is_night_time()
        
        return True
    
    def led_on(self):
        """Turn LED on if conditions are met"""
        if platform.system() == "Linux" and self.should_use_led() and hasattr(self, 'led_line'):
            try:
                self.led_line.set_value(1)
                print("LED turned ON")
            except Exception as e:
                print(f"Error turning LED on: {e}")
    
    def led_off(self):
        """Turn LED off"""
        if platform.system() == "Linux" and self.use_led and hasattr(self, 'led_line'):
            try:
                self.led_line.set_value(0)
                print("LED turned OFF")
            except Exception as e:
                print(f"Error turning LED off: {e}")
   
    def _init_rpi_camera(self):
        try:
            from picamera2 import Picamera2
            import libcamera
            self.picam2 = Picamera2()
            
            # Get initial exposure time based on time of day
            exposure_time = self.get_current_exposure_time()
            
            self.config = self.picam2.create_still_configuration(
                {"size": self.frame_size},
                controls={"ExposureTime": exposure_time},
                transform=libcamera.Transform(vflip=1),
            )
            self.picam2.configure(self.config)
            self.picam2.start()
            print(f"PiCamera initialized with exposure time: {exposure_time}")
        except Exception as e:
            print(f"Error initializing Raspberry Pi camera: {e}")
            print("Falling back to regular camera...")
            self._init_camera()
       
    def _init_camera(self):
        try:
            self.camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
        except Exception as e:
            print(f"Warning: Could not initialize camera: {e}")
            self.camera = None
        
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
                header = ['timestamp', 'initial_exposure', 'final_exposure', 'avg_brightness', 'led_used']
                writer.writerow(header)
    
    def initialize_sensors(self):
        if platform.system() == "Linux":
            try:
                os.system('sudo modprobe w1-gpio')
                os.system('sudo modprobe w1-therm')
                base_dir = '/sys/bus/w1/devices/'
                device_folders = glob.glob(base_dir + '28*')  # Get all DS18B20 device folders
                print(f"Found {len(device_folders)} temperature sensors")
                sensor_files = [folder + '/w1_slave' for folder in device_folders]
                
                # If we found fewer than 4 sensors, pad with None values
                sensor_files = sensor_files[:self.num_sensors]  # Limit to maximum 4 sensors
                while len(sensor_files) < self.num_sensors:
                    sensor_files.append(None)
                return sensor_files
            except Exception as e:
                print(f"Error initializing temperature sensors: {e}")
                return [None] * self.num_sensors
        else:
            print("Running on non-Linux platform. Using simulated temperature sensors.")
            # Return 4 dummy sensor values for testing
            return ["dummy_sensor_1", "dummy_sensor_2", "dummy_sensor_3", "dummy_sensor_4"]
            
    def read_temp_raw(self, device_file):
        try:
            if platform.system() == "Linux" and device_file is not None:
                with open(device_file, 'r') as f:
                    return f.readlines()
            else:
                # Simulate sensor reading on non-Linux platforms or when sensor is missing
                return ["YES", "t=23456"]
        except Exception as e:
            print(f"Error reading from sensor {device_file}: {e}")
            return None
            
    def read_temp(self, device_file):
        try:
            if platform.system() == "Linux" and device_file is not None:
                lines = self.read_temp_raw(device_file)
                
                # If read_temp_raw returned None due to an error
                if lines is None:
                    return None
                    
                # Check if we have sufficient data in lines
                if len(lines) < 2:
                    print(f"Warning: Insufficient data from sensor {device_file}")
                    return None
                
                # Check the CRC status but don't get stuck in a loop
                max_retries = 3
                retries = 0
                while lines[0].strip()[-3:] != 'YES' and retries < max_retries:
                    time.sleep(0.2)
                    lines = self.read_temp_raw(device_file)
                    if lines is None or len(lines) < 2:
                        return None
                    retries += 1
                
                # If we couldn't get a good reading, return None
                if lines[0].strip()[-3:] != 'YES':
                    print(f"Warning: CRC check failed for sensor {device_file}")
                    return None
                
                equals_pos = lines[1].find('t=')
                if equals_pos != -1:
                    temp_string = lines[1][equals_pos+2:]
                    temp_c = float(temp_string) / 1000.0
                    return temp_c
                return None
            else:
                # Generate simulated temperature readings
                import random
                # Each sensor gets a slightly different base temperature for more realistic simulation
                sensor_id = 0
                if isinstance(device_file, str) and device_file.startswith("dummy_sensor_"):
                    try:
                        sensor_id = int(device_file.split("_")[-1]) - 1
                    except:
                        pass
                temp_c = 20 + sensor_id + random.uniform(-1, 1)
                return temp_c
        except Exception as e:
            print(f"Error processing temperature for sensor {device_file}: {e}")
            return None
    
    def calculate_image_brightness(self, image):
        """Calculate average brightness of an image"""
        try:
            # Convert to grayscale if the image is in color
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            # Calculate average brightness
            return np.mean(gray)
        except Exception as e:
            print(f"Error calculating image brightness: {e}")
            return 0
    
    def capture_test_frame(self, exposure_time=None):
        """Capture a test frame to analyze brightness"""
        try:
            if platform.system() == "Linux" and hasattr(self, 'picam2'):
                # Set exposure if provided
                if exposure_time:
                    self.picam2.set_controls({'ExposureTime': exposure_time})
                
                # Capture a frame (lower resolution for speed)
                test_config = self.picam2.create_still_configuration({"size": (1920, 1080)})
                self.picam2.switch_mode(test_config)
                buffer = self.picam2.capture_array("main")
                
                # Switch back to full resolution
                self.picam2.switch_mode(self.config)
                
                return buffer
            elif hasattr(self, 'camera') and self.camera is not None:
                # With OpenCV, just return a regular frame
                ret, frame = self.camera.read()
                if ret:
                    return frame
                return None
            return None
        except Exception as e:
            print(f"Error capturing test frame: {e}")
            return None
    
    def adjust_exposure(self, led_required=False):
        """Auto-adjust exposure using test frames until target brightness is achieved"""
        if not self.auto_exposure:
            return self.get_current_exposure_time()
            
        # Turn on LED if needed for test frames
        led_used = False
        if led_required and self.should_use_led():
            self.led_on()
            led_used = True
            time.sleep(0.5)  # Let LED warm up
            
        try:
            # Start with time-based exposure as our baseline
            base_exposure = self.get_current_exposure_time()
            current_exposure = base_exposure
            
            print(f"Auto-exposure starting with base exposure: {base_exposure} μs")
            
            for attempt in range(self.max_exposure_attempts):
                # Capture test frame with current exposure
                test_frame = self.capture_test_frame(current_exposure)
                
                if test_frame is None:
                    print("Failed to capture test frame, using base exposure")
                    return base_exposure
                
                # Calculate brightness
                avg_brightness = self.calculate_image_brightness(test_frame)
                print(f"Test frame {attempt+1}: Exposure={current_exposure} μs, Brightness={avg_brightness:.1f}")
                
                # Check if we're within tolerance of target brightness
                if abs(avg_brightness - self.target_brightness) <= self.brightness_tolerance:
                    print(f"Target brightness achieved: {avg_brightness:.1f} (target: {self.target_brightness})")
                    break
                    
                # Calculate adjustment factor based on how far we are from target
                brightness_ratio = self.target_brightness / max(1, avg_brightness)
                
                # Apply adjustment, but limit change rate to avoid oscillation
                adjustment_factor = max(0.5, min(2.0, brightness_ratio))
                
                # Calculate new exposure time
                new_exposure = int(current_exposure * adjustment_factor)
                
                # Enforce min/max limits
                new_exposure = max(self.min_exposure, min(self.max_exposure, new_exposure))
                
                print(f"Adjusting exposure: {current_exposure} → {new_exposure} μs (factor: {adjustment_factor:.2f})")
                
                # Apply new exposure for next iteration
                current_exposure = new_exposure
                
            # Log exposure data
            self.log_exposure_data(base_exposure, current_exposure, avg_brightness, led_used)
                
            # Return the optimized exposure time
            return current_exposure
            
        except Exception as e:
            print(f"Error during auto-exposure: {e}")
            return self.get_current_exposure_time()
        finally:
            # Make sure to turn off LED if it was turned on
            if led_used:
                self.led_off()
    
    def log_exposure_data(self, initial_exposure, final_exposure, brightness, led_used):
        """Log exposure adjustment data to CSV"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with open(self.exposure_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, initial_exposure, final_exposure, f"{brightness:.1f}", led_used])
        except Exception as e:
            print(f"Error logging exposure data: {e}")
    
    def update_camera_exposure(self):
        """Update camera exposure settings based on time of day and auto-exposure"""
        if platform.system() == "Linux" and hasattr(self, 'picam2'):
            try:
                # Determine if LED will be used for final image
                led_required = self.should_use_led()
                
                # Get the optimal exposure time
                if self.auto_exposure:
                    exposure_time = self.adjust_exposure(led_required)
                else:
                    exposure_time = self.get_current_exposure_time()
                
                # Apply exposure setting
                self.picam2.set_controls({'ExposureTime': exposure_time})
                self.last_exposure_time = exposure_time
                
                print(f"Camera exposure updated: {exposure_time} μs ({'night' if self.is_night_time() else 'day'} mode, LED: {'ON' if led_required else 'OFF'})")
                return True
            except Exception as e:
                print(f"Error updating camera exposure: {e}")
        return False
    
    def capture_image(self):
        """Capture and save an image with timestamp"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = os.path.join(self.day_dir, f"image_{timestamp}.jpg")
            
            # Update camera exposure based on time of day and lighting conditions
            self.update_camera_exposure()
            
            # Turn on LED if enabled and if it's nighttime (when night_led_only is True)
            led_used = False
            if self.should_use_led():
                self.led_on()
                led_used = True
                # Small delay to let the LED fully illuminate
                time.sleep(0.5)
            else:
                is_night = self.is_night_time()
                print(f"LED not used for this capture (Nighttime: {is_night}, LED enabled: {self.use_led})")
            
            # Capture the image
            success = False
            if platform.system() == "Linux" and hasattr(self, 'picam2'):
                # Capture with Raspberry Pi camera
                self.picam2.capture_file(image_path)
                
                # Add exposure info to EXIF metadata (will be embedded in JPG)
                # For PiCamera2, this is already included in the image metadata
                
                success = True
            elif hasattr(self, 'camera') and self.camera is not None:
                # Capture with OpenCV
                ret, frame = self.camera.read()
                if ret:
                    cv2.imwrite(image_path, frame)
                    success = True
                else:
                    print("Warning: Could not capture image")
            else:
                print("Warning: No camera available to capture image")
            
            # Turn off LED after capturing if it was turned on
            if led_used:
                self.led_off()
            
            if success:
                print(f"Image saved: {image_path} (Exposure: {self.last_exposure_time} μs)")
                
        except Exception as e:
            print(f"Error capturing image: {e}")
            # Ensure LED is turned off in case of error
            if self.use_led:
                self.led_off()
    
    def log_temperature(self, temperatures):
        """Log temperature data to the CSV file"""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Convert None values to empty strings
            temp_values = [f"{temp:.2f}" if temp is not None else "" for temp in temperatures]
            
            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp] + temp_values)
        except Exception as e:
            print(f"Error logging temperature data: {e}")
    
    def main(self):
        sensor_files = self.initialize_sensors()
        
        print(f"Starting data recording. Images saved every minute, temperature recorded every second.")
        print(f"Data directory: {self.data_dir}")
        print(f"Using up to {self.num_sensors} temperature sensors")
        print(f"LED for image capture: {'ENABLED' if self.use_led else 'DISABLED'}")
        print(f"Auto-exposure: {'ENABLED' if self.auto_exposure else 'DISABLED'}")
        
        if self.auto_exposure:
            print(f"Target brightness: {self.target_brightness} ± {self.brightness_tolerance}")
            print(f"Exposure range: {self.min_exposure} - {self.max_exposure} μs")
        
        # Print exposure schedule
        print("\nBase exposure time schedule from TOML config:")
        for setting in self.exposure_settings["time_exposures"]:
            print(f"  {setting['hour']:02d}:{setting['minute']:02d} → {setting['exposure']} μs")
        
        if self.use_led and self.night_led_only:
            day_start = self.exposure_settings["day"]["start_hour"]
            day_end = self.exposure_settings["day"]["end_hour"]
            print(f"\nLED will only be used at night (between {day_end}:00 and {day_start}:00)")
        
        try:
            while True:
                try:
                    # Check if we need to update day directory
                    current_day = f"day{(datetime.now() - datetime(2025, 4, 7)).days + 1}"
                    if current_day != self.day_str:
                        self._update_day_paths()
                        print(f"New day detected. Saving to {self.day_dir}")
                    
                    # Record temperature for all sensors
                    temperatures = []
                    for i, sensor in enumerate(sensor_files):
                        try:
                            temp_c = self.read_temp(sensor)
                            temperatures.append(temp_c)
                            status = f"{temp_c:.2f}°C" if temp_c is not None else "N/A"
                            print(f"Sensor {i+1}: {status}")
                        except Exception as e:
                            print(f"Error reading sensor {i+1}: {e}")
                            temperatures.append(None)
                    
                    # Log all temperatures in one row
                    self.log_temperature(temperatures)
                    
                    # Capture image once per minute
                    current_time = time.time()
                    if current_time - self.last_image_time >= 60:  # 60 seconds = 1 minute
                        self.capture_image()
                        self.last_image_time = current_time
                    
                    print("---")
                    
                except Exception as e:
                    print(f"Error in main loop: {e}")
                    print("Continuing to next iteration...")
                
                time.sleep(1)  # 1 second interval
                
        except KeyboardInterrupt:
            print("Recording stopped by user")
            # Ensure LED is off when exiting
            if self.use_led:
                self.led_off()
            if platform.system() != "Linux" and hasattr(self, 'camera') and self.camera is not None:
                self.camera.release()

if __name__ == "__main__":
    # To enable LED and auto-exposure (default):
    DataRecorder(use_led=True, night_led_only=True, auto_exposure=True).main()
    
    # To disable auto-exposure and use only time-based exposure settings:
    # DataRecorder(use_led=True, night_led_only=True, auto_exposure=False).main()
    
    # To enable LED during image capture at all times:
    # DataRecorder(use_led=True, night_led_only=False, auto_exposure=True).main()
    
    # To disable LED during image capture:
    # DataRecorder(use_led=False, auto_exposure=True).main()
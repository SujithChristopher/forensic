import os
import glob
import time
import cv2
import platform
import csv
from datetime import datetime

class DataRecorder():
    def __init__(self, use_led=True, night_led_only=True):
        self.frame_size = (1280, 720)
        
        # Flag to control LED usage during image capture
        self.use_led = use_led
        
        # Flag to control LED usage based on time of day (night only)
        self.night_led_only = night_led_only
        
        # Create base data directory
        self.data_dir = "data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # Initialize LED if on Linux and LED is enabled
        if platform.system() == "Linux" and self.use_led:
            self._init_led()
        
        # Initialize camera based on platform
        if platform.system() == "Linux":
            self._init_rpi_camera()
        else:
            self._init_camera()
            
        # Number of temperature sensors to use
        self.num_sensors = 4
            
        # Initialize day-specific paths
        self._update_day_paths()
        
        # Last image capture timestamp
        self.last_image_time = 0
    
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
        """Check if current time is between 6:00 PM and 6:00 AM"""
        current_hour = datetime.now().hour
        return current_hour >= 18 or current_hour < 6
    
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
            config = self.picam2.create_video_configuration(
                {"format": "YUV420", "size": self.frame_size},
                controls={"FrameRate": 1, "ExposureTime": 50000},
                transform=libcamera.Transform(vflip=1),
            )
            self.picam2.configure(config)
            self.picam2.start()
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
        
        # Create CSV with headers if it doesn't exist
        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, 'w', newline='') as f:
                writer = csv.writer(f)
                # Create header with timestamp and sensor1 through sensor4
                header = ['timestamp'] + [f'sensor{i+1}' for i in range(self.num_sensors)]
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
    
    def capture_image(self):
        """Capture and save an image with timestamp"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = os.path.join(self.day_dir, f"image_{timestamp}.jpg")
            
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
                img = self.picam2.capture_array()
                cv2.imwrite(image_path, cv2.cvtColor(img, cv2.COLOR_YUV420p2BGR))
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
                print(f"Image saved: {image_path}")
                
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
        if self.use_led and self.night_led_only:
            print(f"LED will only be used at night (6:00 PM to 6:00 AM)")
        
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
    # To enable LED during image capture at night only (6PM-6AM):
    DataRecorder(use_led=True, night_led_only=True).main()
    
    # To enable LED during image capture at all times:
    # DataRecorder(use_led=True, night_led_only=False).main()
    
    # To disable LED during image capture:
    # DataRecorder(use_led=False).main()
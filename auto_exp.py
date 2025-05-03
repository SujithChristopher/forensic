import os
import glob
import time
import cv2
import platform
import csv
import tomli  # For reading TOML files
import numpy as np
from datetime import datetime

from utils.temperature_sensor import temp_support

class DataRecorder():
    def __init__(self, use_led=True, night_led_only=True, config_file="exposure.toml", auto_exposure=True):
        self.frame_size = (4608, 2592)
        
        # Flag to control LED usage during image capture
        self.use_led = use_led
        
        # Flag to control LED usage based on time of day (night only)
        self.night_led_only = night_led_only
        
        # Flag to enable auto-exposure feature
        self.auto_exposure = auto_exposure
        
        # Target brightness level for auto-exposure (0-255)
        self.target_brightness = 120  # Medium brightness
        
        # Brightness tolerance (how close we need to get to target)
        self.brightness_tolerance = 10  # Tighter tolerance for more uniform results
        
        # Max number of attempts for auto-exposure
        self.max_exposure_attempts = 8  # Increased for more precise adjustment
        
        # Exposure adjustment factors
        self.min_exposure = 50000    # Minimum exposure time (microseconds)
        self.max_exposure = 10000000  # Maximum exposure time (microseconds)
        
        # Histogram-based contrast analysis
        self.enable_histogram_analysis = True
        self.target_contrast_range = (40, 200)  # Target range for most pixels
        
        # Multiple sampling for each brightness assessment
        self.num_test_samples = 3
        
        # Load camera settings from TOML file
        self.config_file = config_file
        self.exposure_settings = self.load_exposure_settings()
        
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
        
        # Store last used exposure time for logging
        self.last_exposure_time = self.get_current_exposure_time()
        
        # Store recent successful exposure times to improve stability
        self.recent_exposures = []
        self.max_exposure_history = 5
    

    
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
                return True
            except Exception as e:
                print(f"Error turning LED on: {e}")
                return False
        return False
    
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
        

    

    
    def calculate_image_quality(self, image):
        """Calculate image quality metrics including brightness, contrast, and histogram distribution"""
        try:
            # Convert to grayscale if the image is in color
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            # Calculate average brightness
            avg_brightness = np.mean(gray)
            
            # Calculate standard deviation (simple contrast measure)
            std_dev = np.std(gray)
            
            # Calculate histogram
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist = hist.flatten() / hist.sum()  # Normalize histogram
            
            # Calculate histogram standard deviation (measure of spread)
            hist_indices = np.arange(256)
            hist_mean = np.sum(hist_indices * hist)
            hist_std = np.sqrt(np.sum(((hist_indices - hist_mean) ** 2) * hist))
            
            # Calculate contrast ratio (simplified)
            p_low = np.percentile(gray, 5)  # 5th percentile
            p_high = np.percentile(gray, 95)  # 95th percentile
            if p_low > 0:  # Avoid division by zero
                contrast_ratio = p_high / p_low
            else:
                contrast_ratio = p_high
            
            return {
                'avg_brightness': avg_brightness,
                'std_dev': std_dev,
                'hist_std': hist_std,
                'contrast_ratio': contrast_ratio
            }
        except Exception as e:
            print(f"Error calculating image quality: {e}")
            return {
                'avg_brightness': 0,
                'std_dev': 0,
                'hist_std': 0,
                'contrast_ratio': 0
            }
    
    def capture_test_frame(self, exposure_time=None, exposure_tolerance=50):
        """Capture a test frame to analyze brightness"""
        try:
            if platform.system() == "Linux" and hasattr(self, 'picam2'):
                # Set exposure if provided
                if exposure_time:
                    self.picam2.set_controls({'ExposureTime': exposure_time})
                
                # Capture a frame (lower resolution for speed)
                test_config = self.picam2.create_still_configuration({"size": (1920, 1080)})
                self.picam2.switch_mode(test_config)
                for i in range(3):
                    buffer = self.picam2.capture_array("main")
                    realtime_exposure = self.picam2.capture_metadata['Exposure']
                    if exposure_time and abs(realtime_exposure - exposure_time) <= exposure_tolerance:
                        break
                
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
            
    def get_starting_exposure(self):
        """Get a good starting exposure value based on time of day and recent history"""
        # Start with time-based exposure as baseline
        base_exposure = self.get_current_exposure_time()
        
        # If we have recent successful exposures, use their average as a better starting point
        if len(self.recent_exposures) > 0:
            recent_avg = sum(self.recent_exposures) / len(self.recent_exposures)
            # Blend between time-based and recent history (70% recent, 30% time-based)
            starting_exposure = int(0.7 * recent_avg + 0.3 * base_exposure)
            print(f"Using blended exposure: {starting_exposure} μs (time-based: {base_exposure} μs, recent avg: {recent_avg:.0f} μs)")
            return starting_exposure
        
        return base_exposure
    
    def analyze_image_histogram(self, image):
        """Analyze image histogram to check for proper exposure distribution"""
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
                
            # Calculate histogram
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist = hist.flatten()
            
            # Check for overexposure (too many bright pixels)
            bright_pixels = np.sum(hist[220:]) / np.sum(hist)
            
            # Check for underexposure (too many dark pixels)
            dark_pixels = np.sum(hist[:30]) / np.sum(hist)
            
            # Calculate the percentage of pixels in the ideal middle range
            midrange_pixels = np.sum(hist[self.target_contrast_range[0]:self.target_contrast_range[1]]) / np.sum(hist)
            
            return {
                'overexposed': bright_pixels > 0.15,  # More than 15% very bright pixels
                'underexposed': dark_pixels > 0.15,   # More than 15% very dark pixels
                'midrange_percent': midrange_pixels * 100,
                'dark_percent': dark_pixels * 100,
                'bright_percent': bright_pixels * 100
            }
        except Exception as e:
            print(f"Error analyzing image histogram: {e}")
            return {'overexposed': False, 'underexposed': False, 'midrange_percent': 0}
    
    def binary_search_exposure(self, min_exp, max_exp, led_used=False):
        """Use binary search to find the optimal exposure value faster"""
        # Start with the midpoint of min and max
        iterations = 0
        max_iterations = 5  # Limit iterations to avoid endless loops
        
        while min_exp < max_exp and iterations < max_iterations:
            mid_exp = (min_exp + max_exp) // 2
            print(f"Binary search iteration {iterations+1}: Testing exposure {mid_exp} μs")
            
            # Capture test frame with current exposure
            test_frame = self.capture_test_frame(mid_exp)
            
            if test_frame is None:
                print("Failed to capture test frame during binary search")
                return mid_exp
                
            # Calculate brightness
            metrics = self.calculate_image_quality(test_frame)
            brightness = metrics['avg_brightness']
            
            print(f"  Test brightness: {brightness:.1f} (target: {self.target_brightness})")
            
            # Check if we're within tolerance
            if abs(brightness - self.target_brightness) <= self.brightness_tolerance:
                print(f"  Found acceptable exposure: {mid_exp} μs gives brightness {brightness:.1f}")
                return mid_exp
            
            # Adjust search space
            if brightness < self.target_brightness:
                # Image too dark, increase exposure (search upper half)
                min_exp = mid_exp
            else:
                # Image too bright, decrease exposure (search lower half)
                max_exp = mid_exp
                
            iterations += 1
            
        # Return the middle value if we couldn't converge
        return (min_exp + max_exp) // 2
    
    def adjust_exposure(self, led_required=False):
        """Enhanced auto-adjust exposure using test frames until target brightness is achieved"""
        if not self.auto_exposure:
            return self.get_current_exposure_time()
            
        # Turn on LED if needed for test frames
        led_used = False
        if led_required and self.should_use_led():
            led_used = self.led_on()
            time.sleep(0.5)  # Let LED warm up
            
        try:
            # Get starting exposure based on time and history
            base_exposure = self.get_starting_exposure()
            
            # Start a little lower than the base exposure to avoid overexposure
            current_exposure = int(base_exposure * 0.9)
            
            # Ensure within min/max bounds
            current_exposure = max(self.min_exposure, min(self.max_exposure, current_exposure))
            
            print(f"Auto-exposure starting with base exposure: {current_exposure} μs")
            
            # Quick binary search to get close to target brightness
            if self.max_exposure / self.min_exposure >= 4:  # Only worth it for large exposure ranges
                current_exposure = self.binary_search_exposure(
                    min_exp=max(self.min_exposure, int(current_exposure * 0.5)),
                    max_exp=min(self.max_exposure, int(current_exposure * 2.0)),
                    led_used=led_used
                )
            
            # Fine-tune with iterative steps
            avg_brightness = 0
            contrast = 0
            hist_analysis = {}
            
            for attempt in range(self.max_exposure_attempts):
                # Capture multiple test frames and average the results for stability
                brightness_samples = []
                test_frame = None
                
                for _ in range(self.num_test_samples):
                    frame = self.capture_test_frame(current_exposure)
                    if frame is not None:
                        test_frame = frame  # Keep the last valid frame
                        metrics = self.calculate_image_quality(frame)
                        brightness_samples.append(metrics['avg_brightness'])
                
                if not brightness_samples:
                    print("Failed to capture any test frames, using base exposure")
                    return base_exposure
                
                # Use median brightness to reduce impact of outliers
                avg_brightness = np.median(brightness_samples)
                
                # Get more detailed image metrics
                metrics = self.calculate_image_quality(test_frame)
                contrast = metrics['contrast_ratio']
                
                # Analyze histogram distribution
                if self.enable_histogram_analysis:
                    hist_analysis = self.analyze_image_histogram(test_frame)
                    print(f"Histogram analysis: {hist_analysis['midrange_percent']:.1f}% midrange, " +
                          f"{hist_analysis['dark_percent']:.1f}% dark, {hist_analysis['bright_percent']:.1f}% bright")
                
                print(f"Test frame {attempt+1}: Exposure={current_exposure} μs, " +
                      f"Brightness={avg_brightness:.1f}, Contrast={contrast:.1f}")
                
                # Check if we're within tolerance of target brightness and histogram looks good
                is_brightness_good = abs(avg_brightness - self.target_brightness) <= self.brightness_tolerance
                is_histogram_good = not self.enable_histogram_analysis or hist_analysis.get('midrange_percent', 0) >= 50
                
                if is_brightness_good and is_histogram_good:
                    print(f"Target brightness achieved: {avg_brightness:.1f} (target: {self.target_brightness})")
                    break
                    
                # Calculate adjustment factor based on how far we are from target
                brightness_ratio = self.target_brightness / max(1, avg_brightness)
                
                # Use smaller adjustment steps as we get closer to target
                proximity_factor = min(1.0, abs(avg_brightness - self.target_brightness) / 50.0)
                
                # Apply adjustment, limiting change rate more as we get closer to target
                adjustment_factor = 1.0 + (brightness_ratio - 1.0) * proximity_factor
                adjustment_factor = max(0.7, min(1.5, adjustment_factor))  # Limit extreme adjustments
                
                # Calculate new exposure time
                new_exposure = int(current_exposure * adjustment_factor)
                
                # Account for histogram analysis in adjustment
                if self.enable_histogram_analysis:
                    if hist_analysis.get('overexposed', False):
                        # Reduce exposure even more for overexposed images
                        new_exposure = int(new_exposure * 0.8)
                        print("Reducing exposure further due to overexposure")
                    elif hist_analysis.get('underexposed', False):
                        # Increase exposure for underexposed images
                        new_exposure = int(new_exposure * 1.2)
                        print("Increasing exposure further due to underexposure")
                
                # Enforce min/max limits
                new_exposure = max(self.min_exposure, min(self.max_exposure, new_exposure))
                
                print(f"Adjusting exposure: {current_exposure} → {new_exposure} μs (factor: {adjustment_factor:.2f})")
                
                # Apply new exposure for next iteration
                current_exposure = new_exposure
                
            # Log exposure data
            self.log_exposure_data(base_exposure, current_exposure, avg_brightness, contrast, led_used)
            
            # Remember this exposure time for future use if it was successful
            if abs(avg_brightness - self.target_brightness) <= self.brightness_tolerance * 1.5:
                self.recent_exposures.append(current_exposure)
                # Keep only the most recent N exposures
                if len(self.recent_exposures) > self.max_exposure_history:
                    self.recent_exposures.pop(0)
                
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
        sensor_files = temp_support.initialize_sensors(self)
        
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
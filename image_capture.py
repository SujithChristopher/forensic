import os
import glob
import time
import cv2
import platform
import csv
from datetime import datetime

class DataRecorder():
    def __init__(self):
        self.frame_size = (1280, 720)
        
        # Create base data directory
        self.data_dir = "data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        
        # Initialize camera based on platform
        if platform.system() == "Linux":
            self._init_rpi_camera()
        else:
            self._init_camera()
            
        # Initialize day-specific paths
        self._update_day_paths()
        
        # Last image capture timestamp
        self.last_image_time = 0
   
    def _init_rpi_camera(self):
        from picamera2 import Picamera2
        import libcamera
        self.picam2 = Picamera2()
        config = self.picam2.create_video_configuration(
            {"format": "YUV420", "size": self.frame_size},
            controls={"FrameRate": 100, "ExposureTime": 5000},
            transform=libcamera.Transform(vflip=1),
        )
        self.picam2.configure(config)
        self.picam2.start()
       
    def _init_camera(self):
        self.camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.camera.set(cv2.CAP_PROP_FPS, 30)
        
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
                writer.writerow(['timestamp', 'sensor_id', 'temp_c', 'temp_f'])
    
    def initialize_sensors(self):
        if platform.system() == "Linux":
            os.system('modprobe w1-gpio')
            os.system('modprobe w1-therm')
            base_dir = '/sys/bus/w1/devices/'
            device_folders = glob.glob(base_dir + '28*')  # Get all DS18B20 device folders
            print(f"Found {len(device_folders)} temperature sensors")
            return [folder + '/w1_slave' for folder in device_folders]
        else:
            print("Running on non-Linux platform. Using simulated temperature sensors.")
            # Return dummy sensor IDs for testing on non-Linux platforms
            return ["dummy_sensor_1", "dummy_sensor_2"]
            
    def read_temp_raw(self, device_file):
        if platform.system() == "Linux":
            with open(device_file, 'r') as f:
                return f.readlines()
        else:
            # Simulate sensor reading on non-Linux platforms
            return ["YES", "t=23456"]
            
    def read_temp(self, device_file):
        if platform.system() == "Linux":
            lines = self.read_temp_raw(device_file)
            while lines[0].strip()[-3:] != 'YES':
                time.sleep(0.2)
                lines = self.read_temp_raw(device_file)
            
            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                temp_string = lines[1][equals_pos+2:]
                temp_c = float(temp_string) / 1000.0
                temp_f = temp_c * 9.0 / 5.0 + 32.0
                return temp_c, temp_f
        else:
            # Generate simulated temperature readings
            import random
            temp_c = 20 + random.uniform(-2, 2)
            temp_f = temp_c * 9.0 / 5.0 + 32.0
            return temp_c, temp_f
    
    def capture_image(self):
        """Capture and save an image with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = os.path.join(self.day_dir, f"image_{timestamp}.jpg")
        
        if platform.system() == "Linux":
            # Capture with Raspberry Pi camera
            img = self.picam2.capture_array()
            cv2.imwrite(image_path, cv2.cvtColor(img, cv2.COLOR_YUV420p2BGR))
        else:
            # Capture with OpenCV
            ret, frame = self.camera.read()
            if ret:
                cv2.imwrite(image_path, frame)
                
        print(f"Image saved: {image_path}")
    
    def log_temperature(self, sensor_id, temp_c, temp_f):
        """Log temperature data to the CSV file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(self.csv_filename, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, sensor_id, f"{temp_c:.2f}", f"{temp_f:.2f}"])
    
    def main(self):
        sensor_files = self.initialize_sensors()
        if not sensor_files:
            print("No temperature sensors detected.")
            return
        
        print(f"Starting data recording. Images saved every minute, temperature recorded every second.")
        print(f"Data directory: {self.data_dir}")
        
        try:
            while True:
                # Check if we need to update day directory
                current_day = f"day{(datetime.now() - datetime(2025, 4, 7)).days + 1}"
                if current_day != self.day_str:
                    self._update_day_paths()
                    print(f"New day detected. Saving to {self.day_dir}")
                
                # Record temperature for all sensors
                for i, sensor in enumerate(sensor_files):
                    sensor_id = sensor.split('/')[-2] if platform.system() == "Linux" else f"sensor_{i+1}"
                    temp_c, temp_f = self.read_temp(sensor)
                    print(f"Sensor {sensor_id}: {temp_c:.2f}°C / {temp_f:.2f}°F")
                    self.log_temperature(sensor_id, temp_c, temp_f)
                
                # Capture image once per minute
                current_time = time.time()
                if current_time - self.last_image_time >= 3:  # 60 seconds = 1 minute
                    self.capture_image()
                    self.last_image_time = current_time
                
                print("---")
                time.sleep(1)  # 1 second interval
                
        except KeyboardInterrupt:
            print("Recording stopped by user")
            if platform.system() != "Linux":
                self.camera.release()

if __name__ == "__main__":
    DataRecorder().main()
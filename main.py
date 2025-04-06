import os
import glob
import time
import cv2
import platform


class DataRecorder():
    def __init__(self):
        if platform.system() == "Linux":
            self._init_rpi_camera()
        else:
            self._init_camera()
    

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

    def initialize_sensors(self):
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        base_dir = '/sys/bus/w1/devices/'
        device_folders = glob.glob(base_dir + '28*')  # Get all DS18B20 device folders
        print(device_folders)
        return [folder + '/w1_slave' for folder in device_folders]

    def read_temp_raw(device_file):
        with open(device_file, 'r') as f:
            return f.readlines()

    def read_temp(self, device_file):
        lines = read_temp_raw(device_file)

        while lines[0].strip()[-3:] != 'YES':
            time.sleep(1)
            lines = read_temp_raw(device_file)
        
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos+2:]
            temp_c = float(temp_string) / 1000.0
            temp_f = temp_c * 9.0 / 5.0 + 32.0
            return temp_c, temp_f

    def main(self):
        sensor_files = self.initialize_sensors()
        if not sensor_files:
            print("No DS18B20 sensors detected.")
            return
        
        while True:
            for i, sensor in enumerate(sensor_files):
                temp_c, temp_f = self.read_temp(sensor)
                print(f"Sensor {i + 1}: {temp_c:.2f}°C / {temp_f:.2f}°F")
            print("---")
            time.sleep(1)

if __name__ == "__main__":
    DataRecorder().main()

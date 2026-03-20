import os
import glob
import time
import random
import platform


class TemperatureSensors:
    def initialize(self, num_sensors=4):
        """Discover DS18B20 sensors. Returns list of paths (or dummy strings for non-Linux)."""
        if platform.system() == "Linux":
            try:
                os.system("sudo modprobe w1-gpio")
                os.system("sudo modprobe w1-therm")
                base_dir = "/sys/bus/w1/devices/"
                device_folders = glob.glob(base_dir + "28*")
                print(f"Found {len(device_folders)} temperature sensors")
                sensor_files = [folder + "/w1_slave" for folder in device_folders]
                sensor_files = sensor_files[:num_sensors]
                while len(sensor_files) < num_sensors:
                    sensor_files.append(None)
                return sensor_files
            except Exception as e:
                print(f"Error initializing temperature sensors: {e}")
                return [None] * num_sensors
        else:
            print("Running on non-Linux platform. Using simulated temperature sensors.")
            return [f"dummy_sensor_{i + 1}" for i in range(num_sensors)]

    def read_one(self, device_file):
        """Read temperature from a single sensor file. Returns float (°C) or None."""
        try:
            if platform.system() == "Linux" and device_file is not None:
                lines = self._read_raw(device_file)
                if lines is None or len(lines) < 2:
                    return None
                retries = 0
                while lines[0].strip()[-3:] != "YES" and retries < 3:
                    time.sleep(0.2)
                    lines = self._read_raw(device_file)
                    if lines is None or len(lines) < 2:
                        return None
                    retries += 1
                if lines[0].strip()[-3:] != "YES":
                    print(f"Warning: CRC check failed for sensor {device_file}")
                    return None
                equals_pos = lines[1].find("t=")
                if equals_pos != -1:
                    return float(lines[1][equals_pos + 2:]) / 1000.0
                return None
            else:
                sensor_id = 0
                if isinstance(device_file, str) and device_file.startswith("dummy_sensor_"):
                    try:
                        sensor_id = int(device_file.split("_")[-1]) - 1
                    except Exception:
                        pass
                return 20 + sensor_id + random.uniform(-1, 1)
        except Exception as e:
            print(f"Error processing temperature for sensor {device_file}: {e}")
            return None

    def read_all(self, sensor_files):
        """Read temperature from all sensors. Returns list of float|None."""
        return [self.read_one(f) for f in sensor_files]

    def _read_raw(self, device_file):
        try:
            with open(device_file, "r") as f:
                return f.readlines()
        except Exception as e:
            print(f"Error reading from sensor {device_file}: {e}")
            return None

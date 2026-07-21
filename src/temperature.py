"""DS18B20 1-Wire temperature sensor reading (with a simulated fallback off-Pi)."""

import glob
import os
import platform
import random
import time


class TemperatureSensors:
    def __init__(self, num_sensors=4):
        self.num_sensors = num_sensors
        self.sensor_files = self.initialize()

    def initialize(self):
        if platform.system() == "Linux":
            try:
                os.system('sudo modprobe w1-gpio')
                os.system('sudo modprobe w1-therm')
                base_dir = '/sys/bus/w1/devices/'
                device_folders = glob.glob(base_dir + '28*')  # DS18B20 device folders
                print(f"Found {len(device_folders)} temperature sensors")
                sensor_files = [folder + '/w1_slave' for folder in device_folders]

                # Limit to num_sensors, pad with None if fewer are present
                sensor_files = sensor_files[:self.num_sensors]
                while len(sensor_files) < self.num_sensors:
                    sensor_files.append(None)
                return sensor_files
            except Exception as e:
                print(f"Error initializing temperature sensors: {e}")
                return [None] * self.num_sensors
        else:
            print("Running on non-Linux platform. Using simulated temperature sensors.")
            return ["dummy_sensor_1", "dummy_sensor_2", "dummy_sensor_3", "dummy_sensor_4"]

    def read_raw(self, device_file):
        try:
            if platform.system() == "Linux" and device_file is not None:
                with open(device_file, 'r') as f:
                    return f.readlines()
            else:
                # Simulate a sensor reading on non-Linux platforms or when sensor missing
                return ["YES", "t=23456"]
        except Exception as e:
            print(f"Error reading from sensor {device_file}: {e}")
            return None

    def read(self, device_file):
        try:
            if platform.system() == "Linux" and device_file is not None:
                lines = self.read_raw(device_file)

                if lines is None:
                    return None

                if len(lines) < 2:
                    print(f"Warning: Insufficient data from sensor {device_file}")
                    return None

                # Check the CRC status but don't get stuck in a loop
                max_retries = 3
                retries = 0
                while lines[0].strip()[-3:] != 'YES' and retries < max_retries:
                    time.sleep(0.2)
                    lines = self.read_raw(device_file)
                    if lines is None or len(lines) < 2:
                        return None
                    retries += 1

                if lines[0].strip()[-3:] != 'YES':
                    print(f"Warning: CRC check failed for sensor {device_file}")
                    return None

                equals_pos = lines[1].find('t=')
                if equals_pos != -1:
                    temp_string = lines[1][equals_pos + 2:]
                    return float(temp_string) / 1000.0
                return None
            else:
                # Generate simulated temperature readings
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

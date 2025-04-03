import os
import glob
import time

def initialize_sensors():
    os.system('modprobe w1-gpio')
    os.system('modprobe w1-therm')
    base_dir = '/sys/bus/w1/devices/'
    device_folders = glob.glob(base_dir + '28*')  # Get all DS18B20 device folders
    print(device_folders)
    return [folder + '/w1_slave' for folder in device_folders]

def read_temp_raw(device_file):
    with open(device_file, 'r') as f:
        return f.readlines()

def read_temp(device_file):
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

def main():
    sensor_files = initialize_sensors()
    if not sensor_files:
        print("No DS18B20 sensors detected.")
        return
    
    while True:
        for i, sensor in enumerate(sensor_files):
            temp_c, temp_f = read_temp(sensor)
            print(f"Sensor {i + 1}: {temp_c:.2f}°C / {temp_f:.2f}°F")
        print("---")
        time.sleep(1)

if __name__ == "__main__":
    main()

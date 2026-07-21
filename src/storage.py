"""Per-day directory management and CSV logging.

Data is organised as data/YYYY-MM-DD/ with three CSVs per day (temperature, exposure,
image quality). Callers serialise day rollover against in-progress captures with an
external lock (the recorder owns it); the IO methods here are otherwise independent.
"""

import csv
import os
from datetime import datetime


class DataStorage:
    def __init__(self, data_dir, num_sensors):
        self.data_dir = data_dir
        self.num_sensors = num_sensors

        if not os.path.exists(self.data_dir):
            try:
                os.makedirs(self.data_dir)
            except PermissionError:
                print(f"CRITICAL ERROR: No permission to create {self.data_dir}")
                print("Try moving the script to a folder you own, or run with sudo.")
                raise

        # day_str / day_dir / csv paths are set here
        self.update_day_paths()

    @staticmethod
    def current_day():
        return datetime.now().strftime("%Y-%m-%d")

    def update_day_paths(self):
        """Point the CSV/image paths at today's directory, creating files + headers."""
        current_date = self.current_day()
        self.day_str = current_date

        self.day_dir = os.path.join(self.data_dir, self.day_str)
        if not os.path.exists(self.day_dir):
            os.makedirs(self.day_dir)

        self.csv_filename = os.path.join(self.day_dir, f"temp_data_{current_date}.csv")
        self.exposure_csv = os.path.join(self.day_dir, f"exposure_data_{current_date}.csv")
        self.quality_csv = os.path.join(self.day_dir, f"image_quality_{current_date}.csv")

        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ['timestamp'] + [f'sensor{i+1}' for i in range(self.num_sensors)]
                writer.writerow(header)

        if not os.path.exists(self.exposure_csv):
            with open(self.exposure_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'initial_exposure', 'final_exposure',
                                 'avg_brightness', 'contrast', 'led_used'])

        if not os.path.exists(self.quality_csv):
            with open(self.quality_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'filename', 'avg_brightness',
                                 'contrast', 'histogram_std', 'exposure_time'])

    def log_temperature(self, temperatures):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            temp_values = [f"{temp:.2f}" if temp is not None else "" for temp in temperatures]
            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp] + temp_values)
        except Exception as e:
            print(f"Error logging temperature data: {e}")

    def log_exposure(self, initial_exposure, final_exposure, brightness, contrast, led_used):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.exposure_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, initial_exposure, final_exposure,
                                 f"{brightness:.1f}", f"{contrast:.1f}", led_used])
        except Exception as e:
            print(f"Error logging exposure data: {e}")

    def log_image_quality(self, image_path, metrics, exposure_time):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            filename = os.path.basename(image_path)
            with open(self.quality_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    filename,
                    f"{metrics['avg_brightness']:.1f}",
                    f"{metrics['contrast_ratio']:.1f}",
                    f"{metrics['hist_std']:.1f}",
                    exposure_time,
                ])
        except Exception as e:
            print(f"Error logging image quality: {e}")

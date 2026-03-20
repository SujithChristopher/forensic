import os
import csv
from datetime import datetime


class DataLogger:
    def __init__(self, base_dir, num_sensors=4):
        self.base_dir = base_dir
        self.num_sensors = num_sensors
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        self.day_str = None
        self.day_dir = None
        self.csv_filename = None
        self.exposure_csv = None
        self.quality_csv = None

    def update_day(self, date_str=None):
        """Create/switch to a new day directory and initialise CSV files with headers."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        self.day_str = date_str
        self.day_dir = os.path.join(self.base_dir, date_str)
        if not os.path.exists(self.day_dir):
            os.makedirs(self.day_dir)

        self.csv_filename = os.path.join(self.day_dir, f"temp_data_{date_str}.csv")
        self.exposure_csv = os.path.join(self.day_dir, f"exposure_data_{date_str}.csv")
        self.quality_csv = os.path.join(self.day_dir, f"image_quality_{date_str}.csv")

        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp"] + [f"sensor{i + 1}" for i in range(self.num_sensors)]
                )

        if not os.path.exists(self.exposure_csv):
            with open(self.exposure_csv, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "initial_exposure", "final_exposure", "avg_brightness", "contrast", "led_used"]
                )

        if not os.path.exists(self.quality_csv):
            with open(self.quality_csv, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "filename", "avg_brightness", "contrast", "histogram_std", "exposure_time"]
                )

    def log_temperature(self, temperatures):
        """Append one row of temperature readings to the daily temp CSV."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            temp_values = [f"{t:.2f}" if t is not None else "" for t in temperatures]
            with open(self.csv_filename, "a", newline="") as f:
                csv.writer(f).writerow([timestamp] + temp_values)
        except Exception as e:
            print(f"Error logging temperature data: {e}")

    def log_exposure(self, initial, final, brightness, contrast, led_used):
        """Append one exposure adjustment record to the daily exposure CSV."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.exposure_csv, "a", newline="") as f:
                csv.writer(f).writerow(
                    [timestamp, initial, final, f"{brightness:.1f}", f"{contrast:.1f}", led_used]
                )
        except Exception as e:
            print(f"Error logging exposure data: {e}")

    def log_image_quality(self, image_path, metrics, exposure_time):
        """Append image quality metrics to the daily quality CSV."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            filename = os.path.basename(image_path)
            with open(self.quality_csv, "a", newline="") as f:
                csv.writer(f).writerow([
                    timestamp,
                    filename,
                    f"{metrics['avg_brightness']:.1f}",
                    f"{metrics['contrast_ratio']:.1f}",
                    f"{metrics['hist_std']:.1f}",
                    exposure_time,
                ])
        except Exception as e:
            print(f"Error logging image quality: {e}")

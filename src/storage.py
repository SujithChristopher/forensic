"""Per-day directory management and CSV logging.

Data is organised as data/YYYY-MM-DD/ with four CSVs per day (temperature, exposure,
image quality, auto-exposure trace). Callers serialise day rollover against in-progress
captures with an external lock (the recorder owns it); the IO methods here are otherwise
independent.

The schemas favour post-hoc diagnosis. Anything recomputable from a saved JPEG is a
convenience; the values that matter are the ones that vanish once the capture ends —
the LED/AEC decisions, analogue gain, sensor metadata, and every intermediate metering
frame. `capture_id` joins all three image-related CSVs to the image file itself.
"""

import csv
import os
from datetime import datetime

EXPOSURE_COLUMNS = [
    'timestamp', 'capture_id',
    # what each stage decided
    'schedule_exposure', 'aec_exposure', 'aec_gain', 'gain_capped', 'analogue_gain',
    'pre_smoothing_exposure', 'smoothing_reverted', 'final_exposure',
    # what the final metering frame actually looked like
    'meter_brightness', 'meter_clip_pct', 'meter_p99', 'meter_center_brightness',
    'meter_hotspot_ratio', 'contrast',
    # lighting decisions
    'ambient_brightness', 'led_used', 'led_just_turned_on', 'darkness_override',
    # the settings in force, so a row explains itself without the config file
    'target_brightness', 'max_clip_pct',
    # how it ended
    'passes_used', 'outcome', 'duration_s', 'error',
]

AE_TRACE_COLUMNS = [
    'timestamp', 'capture_id', 'stage', 'pass_num',
    'requested_exposure', 'actual_exposure', 'analogue_gain', 'digital_gain',
    'lux', 'sensor_temperature', 'frame_duration', 'colour_gain_r', 'colour_gain_b',
    'avg_brightness', 'clip_pct', 'p99', 'center_brightness', 'edge_brightness',
    'hotspot_ratio', 'contrast_ratio', 'led_on', 'frame_ok',
]

QUALITY_COLUMNS = [
    'timestamp', 'capture_id', 'filename',
    'avg_brightness', 'contrast', 'histogram_std',
    'clip_pct', 'p05', 'p50', 'p99',
    'center_brightness', 'edge_brightness', 'hotspot_ratio',
    'exposure_time', 'actual_exposure', 'analogue_gain', 'digital_gain',
    'lux', 'sensor_temperature', 'led_used',
    'hist16',
]


def _fmt(value, precision=2):
    """CSV cell: blank for missing, fixed precision for floats, str otherwise."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{precision}f}"
    return value


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
        self.ae_trace_csv = os.path.join(self.day_dir, f"ae_trace_{current_date}.csv")

        temp_header = ['timestamp'] + [f'sensor{i+1}' for i in range(self.num_sensors)]
        self._ensure_header(self.csv_filename, temp_header)
        self._ensure_header(self.exposure_csv, EXPOSURE_COLUMNS)
        self._ensure_header(self.quality_csv, QUALITY_COLUMNS)
        self._ensure_header(self.ae_trace_csv, AE_TRACE_COLUMNS)

    @staticmethod
    def _ensure_header(path, header):
        """Create the file with its header, or set aside one written to an older schema.

        Restarting mid-day after a schema change would otherwise append rows in the new
        column order under the old header, silently corrupting the whole day's file.
        """
        if not os.path.exists(path):
            with open(path, 'w', newline='') as f:
                csv.writer(f).writerow(header)
            return

        try:
            with open(path, newline='') as f:
                existing = next(csv.reader(f), [])
        except Exception as e:
            print(f"Could not read header of {path}: {e}")
            return

        if existing == header:
            return

        archived = f"{path}.{datetime.now().strftime('%H%M%S')}.old"
        os.rename(path, archived)
        print(f"{os.path.basename(path)} uses an older column set; kept as "
              f"{os.path.basename(archived)} and starting a new file")
        with open(path, 'w', newline='') as f:
            csv.writer(f).writerow(header)

    def log_temperature(self, temperatures):
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            temp_values = [f"{temp:.2f}" if temp is not None else "" for temp in temperatures]
            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp] + temp_values)
        except Exception as e:
            print(f"Error logging temperature data: {e}")

    def log_exposure(self, record):
        """Append one auto-exposure summary row (a dict keyed by EXPOSURE_COLUMNS)."""
        try:
            row = dict(record)
            row['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.exposure_csv, 'a', newline='') as f:
                csv.writer(f).writerow([_fmt(row.get(col)) for col in EXPOSURE_COLUMNS])
        except Exception as e:
            print(f"Error logging exposure data: {e}")

    def log_ae_trace(self, rows):
        """Append one row per metering frame of a hunt, so the decision path can be
        replayed offline instead of inferred from the single summary row."""
        if not rows:
            return
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.ae_trace_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                for row in rows:
                    row = dict(row, timestamp=timestamp)
                    writer.writerow([_fmt(row.get(col)) for col in AE_TRACE_COLUMNS])
        except Exception as e:
            print(f"Error logging auto-exposure trace: {e}")

    def log_image_quality(self, image_path, metrics, exposure_time,
                          capture_id="", meta=None, led_used=""):
        """Append metrics for a saved full-resolution image.

        `meta` is the libcamera metadata of that exact frame — the only record of the
        exposure and gain the sensor really used, as opposed to what was requested.
        """
        try:
            meta = meta or {}
            row = {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'capture_id': capture_id,
                'filename': os.path.basename(image_path),
                'histogram_std': metrics['hist_std'],
                'contrast': metrics['contrast_ratio'],
                'exposure_time': exposure_time,
                'led_used': led_used,
                'hist16': " ".join(str(v) for v in metrics.get('hist16', [])),
            }
            for key in ('avg_brightness', 'clip_pct', 'p05', 'p50', 'p99',
                        'center_brightness', 'edge_brightness', 'hotspot_ratio'):
                row[key] = metrics[key]
            row.update(meta)
            with open(self.quality_csv, 'a', newline='') as f:
                csv.writer(f).writerow([_fmt(row.get(col)) for col in QUALITY_COLUMNS])
        except Exception as e:
            print(f"Error logging image quality: {e}")

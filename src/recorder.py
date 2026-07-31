"""DataRecorder: wires the modules together and runs the recording loops.

Temperature logging runs on the main thread (1-second cadence); image capture runs on
its own thread so multi-second night exposures never stall temperature logging. The two
threads share only the storage paths, serialised at day-rollover by a lock.
"""

import os
import platform
import threading
import time
from datetime import datetime

from .camera import Camera, summarize_metadata
from .config import ExposureConfig
from .exposure import ExposureController
from .image_quality import calculate_image_quality
from .led import LEDController
from .storage import DataStorage
from .temperature import TemperatureSensors

# Repo root = parent of this src/ package, so data/ and exposure.toml keep their
# original locations regardless of where this file lives.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class DataRecorder:
    def __init__(self, use_led=True, night_led_only=True, config_file=None, auto_exposure=True):
        self.base_script_path = PROJECT_ROOT

        self.frame_size = (4608, 2592)
        self.meter_size = (1920, 1080)
        self.num_sensors = 4

        self.use_led = use_led
        self.night_led_only = night_led_only
        self.auto_exposure = auto_exposure

        # --- configuration ---
        if config_file is None:
            config_file = os.path.join(self.base_script_path, "exposure.toml")
        self.config = ExposureConfig(config_file)

        # --- storage ---
        self.data_dir = os.path.join(self.base_script_path, "data")
        self.storage = DataStorage(self.data_dir, self.num_sensors)

        # --- LED (Linux + enabled only) ---
        self.led = None
        if platform.system() == "Linux" and self.use_led:
            self.led = LEDController()
            if not self.led.available:
                # Mirror the original behaviour: a failed LED init disables LED usage.
                self.use_led = False

        # --- camera ---
        initial_exposure = self.config.get_current_exposure_time()
        self.camera = Camera(self.frame_size, self.meter_size, initial_exposure)

        # --- temperature sensors ---
        self.temperature = TemperatureSensors(self.num_sensors)

        # --- exposure / lighting controller ---
        self.exposure = ExposureController(
            self.camera, self.led, self.config, self.storage,
            use_led=self.use_led,
            night_led_only=self.night_led_only,
            auto_exposure=self.auto_exposure,
        )

        # --- concurrency ---
        self._stop_event = threading.Event()
        self._paths_lock = threading.Lock()
        self.last_image_time = 0

    # ---------------------------------------------------------------- capture
    def capture_image(self):
        """Capture and save a full-resolution image with quality logging."""
        try:
            # This timestamp is taken before the exposure hunt (which can run for tens of
            # seconds at night), names the image file, and is the capture_id that joins
            # the exposure, trace and quality CSVs to that file.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = os.path.join(self.storage.day_dir, f"image_{timestamp}.jpg")

            # Update camera exposure based on time of day and lighting conditions
            self.exposure.update_camera_exposure(capture_id=timestamp)

            # Turn on LED if enabled and conditions are met
            led_used = False
            if self.exposure.should_use_led():
                self.exposure.led_on()
                led_used = True
                time.sleep(0.5)  # let the LED fully illuminate
            else:
                is_night = self.config.is_night_time()
                print(f"LED not used for this capture "
                      f"(Nighttime: {is_night}, LED enabled: {self.use_led})")

            success, image_frame, meta = self.camera.capture_and_save(image_path)

            if led_used:
                self.exposure.led_off()

            if success and image_frame is not None:
                metrics = calculate_image_quality(image_frame)
                self.storage.log_image_quality(
                    image_path, metrics, self.exposure.last_exposure_time,
                    capture_id=timestamp, meta=summarize_metadata(meta), led_used=led_used)
                print(f"Image saved: {image_path} "
                      f"(Exposure: {self.exposure.last_exposure_time} μs, "
                      f"Brightness: {metrics['avg_brightness']:.1f}, "
                      f"Clipped: {metrics['clip_pct']:.2f}%, "
                      f"Hotspot: {metrics['hotspot_ratio']:.2f}x)")

        except Exception as e:
            print(f"Error capturing image: {e}")
            # Ensure LED is turned off in case of error
            if self.use_led:
                self.exposure.led_off()

    def capture_loop(self):
        """Dedicated image-capture thread. Runs independently of the temperature loop so
        multi-second night exposures never stall the 1-second temperature logging.

        The camera is only ever touched from this thread; the temperature loop never
        accesses it, so no camera lock is needed. The paths lock only serialises the
        rare day-rollover against an in-progress capture."""
        next_capture = time.time()  # capture once immediately, then every 60s
        while not self._stop_event.is_set():
            if time.time() >= next_capture:
                try:
                    with self._paths_lock:
                        self.capture_image()
                except Exception as e:
                    print(f"Error in capture loop: {e}")
                next_capture = time.time() + 60
            # Wait in short slices so a stop request is handled promptly.
            self._stop_event.wait(1.0)

    # ------------------------------------------------------------------- main
    def main(self):
        sensor_files = self.temperature.sensor_files

        print("Starting data recording. Images saved every minute, temperature recorded every second.")
        print(f"Data directory: {self.data_dir}")
        print(f"Using up to {self.num_sensors} temperature sensors")
        print(f"LED for image capture: {'ENABLED' if self.use_led else 'DISABLED'}")
        print(f"Auto-exposure: {'ENABLED' if self.auto_exposure else 'DISABLED'}")

        if self.auto_exposure:
            print(f"Target brightness: {self.exposure.target_brightness} "
                  f"± {self.exposure.brightness_tolerance}")
            print(f"Exposure range: {self.exposure.min_exposure} - {self.exposure.max_exposure} μs")

        print("\nBase exposure time schedule from TOML config:")
        for setting in self.config.time_exposures:
            print(f"  {setting['hour']:02d}:{setting['minute']:02d} -> {setting['exposure']} μs")

        if self.use_led and self.night_led_only:
            day_start = self.config.day["start_hour"]
            day_end = self.config.day["end_hour"]
            print(f"\nLED will only be used at night (between {day_end}:00 and {day_start}:00)")

        # Image capture runs on its own thread so long night exposures don't block the
        # 1-second temperature cadence below.
        capture_thread = threading.Thread(target=self.capture_loop, name="capture", daemon=True)
        capture_thread.start()

        try:
            while True:
                try:
                    # Roll over to a new day directory when the date changes
                    current_day = self.storage.current_day()
                    if current_day != self.storage.day_str:
                        # Serialise the rollover against an in-progress capture so the
                        # capture thread never reads half-updated day paths.
                        with self._paths_lock:
                            self.storage.update_day_paths()
                        print(f"New day detected. Saving to {self.storage.day_dir}")

                    # Record temperature for all sensors
                    temperatures = []
                    for i, sensor in enumerate(sensor_files):
                        try:
                            temp_c = self.temperature.read(sensor)
                            temperatures.append(temp_c)
                            status = f"{temp_c:.2f}°C" if temp_c is not None else "N/A"
                            print(f"Sensor {i+1}: {status}")
                        except Exception as e:
                            print(f"Error reading sensor {i+1}: {e}")
                            temperatures.append(None)

                    self.storage.log_temperature(temperatures)

                    print("---")

                except Exception as e:
                    print(f"Error in main loop: {e}")
                    print("Continuing to next iteration...")

                time.sleep(1)  # 1 second interval

        except KeyboardInterrupt:
            print("Recording stopped by user")
            # Signal the capture thread to stop and wait for it to finish its current frame.
            self._stop_event.set()
            capture_thread.join(timeout=15)
            if self.use_led:
                self.exposure.led_off()
            self.camera.close()

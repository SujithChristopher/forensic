import os
import time
import cv2
from datetime import datetime

from src.config import load_exposure_settings
from src.hardware.led import LED
from src.hardware.camera import Camera
from src.hardware.sensors import TemperatureSensors
from src.exposure import ExposureManager, calculate_image_quality
from src.data_logger import DataLogger


class DataRecorder:
    def __init__(
        self,
        use_led=True,
        night_led_only=True,
        config_file="/home/rpi2/Documents/forensic/exposure.toml",
        auto_exposure=True,
    ):
        self.use_led = use_led
        self.night_led_only = night_led_only
        self.auto_exposure = auto_exposure
        self.num_sensors = 4
        self.max_exposure_history = 5
        self.recent_exposures = []

        settings = load_exposure_settings(config_file)
        self.exposure_mgr = ExposureManager(settings)

        initial_exposure = self.exposure_mgr.get_time_based()

        # LED setup — disable flag if hardware init fails
        self.led = LED() if use_led else None
        if self.led is not None and not self.led.available:
            self.use_led = False

        self.camera = Camera(frame_size=(4608, 2592), exposure_time=initial_exposure)
        self.sensors = TemperatureSensors()

        data_dir = "/home/rpi2/Documents/forensic/data"
        self.logger = DataLogger(data_dir, num_sensors=self.num_sensors)
        self.logger.update_day()

        self.last_image_time = 0
        self.last_exposure_time = initial_exposure

    def _active_led(self):
        """Return the LED object if it should fire for this capture, else None."""
        if self.led is None or not self.use_led:
            return None
        is_night = self.exposure_mgr.is_night()
        return self.led if self.led.should_use(is_night, self.night_led_only) else None

    def _update_camera_exposure(self):
        """Determine and apply optimal exposure. Logs exposure data. Returns final exposure."""
        led = self._active_led()

        if self.auto_exposure:
            initial, final, brightness, contrast, led_used = self.exposure_mgr.auto_adjust(
                self.camera, led=led, recent_history=self.recent_exposures
            )
            self.logger.log_exposure(initial, final, brightness, contrast, led_used)

            if abs(brightness - self.exposure_mgr.target_brightness) <= self.exposure_mgr.tolerance * 1.5:
                self.recent_exposures.append(final)
                if len(self.recent_exposures) > self.max_exposure_history:
                    self.recent_exposures.pop(0)

            exposure = final
        else:
            exposure = self.exposure_mgr.get_time_based()

        self.camera.set_exposure(exposure)
        self.last_exposure_time = exposure

        mode = "night" if self.exposure_mgr.is_night() else "day"
        print(f"Camera exposure updated: {exposure} μs ({mode} mode)")
        return exposure

    def _capture_image(self):
        """Capture and save one image, log quality metrics."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = os.path.join(self.logger.day_dir, f"image_{timestamp}.jpg")

            self._update_camera_exposure()

            # Turn LED on for final capture if applicable
            led = self._active_led()
            led_used = False
            if led is not None:
                led_used = led.on()
                if led_used:
                    time.sleep(0.5)
            else:
                is_night = self.exposure_mgr.is_night()
                print(f"LED not used for this capture (Nighttime: {is_night}, LED enabled: {self.use_led})")

            image_frame = self.camera.capture_array()

            if led_used and led is not None:
                led.off()

            if image_frame is not None:
                cv2.imwrite(image_path, image_frame)
                metrics = calculate_image_quality(image_frame)
                self.logger.log_image_quality(image_path, metrics, self.last_exposure_time)
                print(
                    f"Image saved: {image_path} "
                    f"(Exposure: {self.last_exposure_time} μs, Brightness: {metrics['avg_brightness']:.1f})"
                )
            else:
                print("Warning: No frame captured")

        except Exception as e:
            print(f"Error capturing image: {e}")
            if self.led is not None and self.use_led:
                self.led.off()

    def main(self):
        sensor_files = self.sensors.initialize(self.num_sensors)

        print("Starting data recording. Images saved every minute, temperature recorded every second.")
        print(f"Data directory: {self.logger.base_dir}")
        print(f"Using up to {self.num_sensors} temperature sensors")
        print(f"LED for image capture: {'ENABLED' if self.use_led else 'DISABLED'}")
        print(f"Auto-exposure: {'ENABLED' if self.auto_exposure else 'DISABLED'}")

        if self.auto_exposure:
            print(f"Target brightness: {self.exposure_mgr.target_brightness} ± {self.exposure_mgr.tolerance}")
            print(f"Exposure range: {self.exposure_mgr.min_exp} - {self.exposure_mgr.max_exp} μs")

        print("\nBase exposure time schedule from TOML config:")
        for setting in self.exposure_mgr.settings["time_exposures"]:
            print(f"  {setting['hour']:02d}:{setting['minute']:02d} → {setting['exposure']} μs")

        if self.use_led and self.night_led_only:
            day_start = self.exposure_mgr.settings["day"]["start_hour"]
            day_end = self.exposure_mgr.settings["day"]["end_hour"]
            print(f"\nLED will only be used at night (between {day_end}:00 and {day_start}:00)")

        try:
            while True:
                try:
                    current_day = datetime.now().strftime("%Y-%m-%d")
                    if current_day != self.logger.day_str:
                        self.logger.update_day(current_day)
                        print(f"New day detected. Saving to {self.logger.day_dir}")

                    temperatures = []
                    for i, sensor in enumerate(sensor_files):
                        try:
                            temp_c = self.sensors.read_one(sensor)
                            temperatures.append(temp_c)
                            status = f"{temp_c:.2f}°C" if temp_c is not None else "N/A"
                            print(f"Sensor {i + 1}: {status}")
                        except Exception as e:
                            print(f"Error reading sensor {i + 1}: {e}")
                            temperatures.append(None)

                    self.logger.log_temperature(temperatures)

                    current_time = time.time()
                    if current_time - self.last_image_time >= 60:
                        self._capture_image()
                        self.last_image_time = current_time

                    print("---")

                except Exception as e:
                    print(f"Error in main loop: {e}")
                    print("Continuing to next iteration...")

                time.sleep(1)

        except KeyboardInterrupt:
            print("Recording stopped by user")
            if self.led is not None and self.use_led:
                self.led.off()
            self.camera.release()

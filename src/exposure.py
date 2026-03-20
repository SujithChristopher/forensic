import time
from datetime import datetime

import cv2
import numpy as np


def calculate_image_quality(image):
    """Calculate brightness, contrast, and histogram metrics for an image."""
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        avg_brightness = np.mean(gray)
        std_dev = np.std(gray)

        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()
        hist_indices = np.arange(256)
        hist_mean = np.sum(hist_indices * hist)
        hist_std = np.sqrt(np.sum(((hist_indices - hist_mean) ** 2) * hist))

        p_low = np.percentile(gray, 5)
        p_high = np.percentile(gray, 95)
        contrast_ratio = p_high / p_low if p_low > 0 else p_high

        return {
            "avg_brightness": avg_brightness,
            "std_dev": std_dev,
            "hist_std": hist_std,
            "contrast_ratio": contrast_ratio,
        }
    except Exception as e:
        print(f"Error calculating image quality: {e}")
        return {"avg_brightness": 0, "std_dev": 0, "hist_std": 0, "contrast_ratio": 0}


class ExposureManager:
    def __init__(
        self,
        settings,
        min_exp=5000,
        max_exp=10000000,
        target_brightness=180,
        tolerance=20,
        max_attempts=5,
    ):
        self.settings = settings
        self.min_exp = min_exp
        self.max_exp = max_exp
        self.target_brightness = target_brightness
        self.tolerance = tolerance
        self.max_attempts = max_attempts

        # Override defaults from auto_exposure section if present
        ae = settings.get("auto_exposure", {})
        if "target_brightness" in ae:
            self.target_brightness = ae["target_brightness"]
        if "min_exposure" in ae:
            self.min_exp = ae["min_exposure"]
        if "max_exposure" in ae:
            self.max_exp = ae["max_exposure"]
        if "tolerance" in ae:
            self.tolerance = ae["tolerance"]

    def is_night(self, now=None):
        """Return True if current time is outside daytime hours."""
        if now is None:
            now = datetime.now()
        hour = now.hour
        day_start = self.settings["day"]["start_hour"]
        day_end = self.settings["day"]["end_hour"]
        if day_start <= day_end:
            return hour < day_start or hour >= day_end
        return hour >= day_end and hour < day_start

    def get_time_based(self, now=None):
        """Return the scheduled exposure time (μs) for the given moment."""
        if now is None:
            now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        time_exposures = self.settings["time_exposures"]
        exposure_value = time_exposures[-1]["exposure"]
        for i, setting in enumerate(time_exposures):
            setting_minutes = setting["hour"] * 60 + setting["minute"]
            if i == len(time_exposures) - 1 or current_minutes < (
                time_exposures[i + 1]["hour"] * 60 + time_exposures[i + 1]["minute"]
            ):
                if current_minutes >= setting_minutes:
                    exposure_value = setting["exposure"]
                    break
                elif i > 0:
                    exposure_value = time_exposures[i - 1]["exposure"]
                    break
        return exposure_value

    def get_starting(self, now=None, recent_history=None):
        """Return blended starting exposure from time schedule + recent history (70/30)."""
        base = self.get_time_based(now)
        if recent_history:
            recent_avg = sum(recent_history) / len(recent_history)
            blended = int(0.7 * recent_avg + 0.3 * base)
            print(
                f"Using blended exposure: {blended} μs "
                f"(time-based: {base} μs, recent avg: {recent_avg:.0f} μs)"
            )
            return blended
        return base

    def auto_adjust(self, camera, led=None, recent_history=None):
        """
        Run iterative auto-exposure loop.

        Turns LED on/off around test captures if provided.
        Returns (initial_exposure, final_exposure, avg_brightness, contrast, led_used).
        """
        led_used = False
        if led is not None and led.available:
            led_used = led.on()
            if led_used:
                time.sleep(0.5)

        try:
            initial_exposure = max(
                self.min_exp,
                min(self.max_exp, self.get_starting(recent_history=recent_history)),
            )
            current_exposure = initial_exposure
            print(f"Auto-exposure starting with base exposure: {current_exposure} μs")

            avg_brightness = 0
            contrast = 0

            for attempt in range(self.max_attempts):
                test_frame = camera.capture_test_frame(current_exposure)
                if test_frame is None:
                    print("Failed to capture test frame, using base exposure")
                    return initial_exposure, self.get_time_based(), 0, 0, led_used

                metrics = calculate_image_quality(test_frame)
                avg_brightness = metrics["avg_brightness"]
                contrast = metrics["contrast_ratio"]

                print(
                    f"Test frame {attempt + 1}: Exposure={current_exposure} μs, "
                    f"Brightness={avg_brightness:.1f}, Contrast={contrast:.1f}"
                )

                if abs(avg_brightness - self.target_brightness) <= self.tolerance:
                    print(
                        f"Target brightness achieved: {avg_brightness:.1f} "
                        f"(target: {self.target_brightness})"
                    )
                    break

                brightness_ratio = self.target_brightness / max(1, avg_brightness)
                if brightness_ratio > 1:
                    adjustment_factor = min(brightness_ratio, 1.5)
                else:
                    adjustment_factor = max(brightness_ratio, 0.7)

                new_exposure = int(current_exposure * adjustment_factor)
                new_exposure = max(self.min_exp, min(self.max_exp, new_exposure))
                print(
                    f"Adjusting exposure: {current_exposure} → {new_exposure} μs "
                    f"(factor: {adjustment_factor:.2f})"
                )
                current_exposure = new_exposure

            return initial_exposure, current_exposure, avg_brightness, contrast, led_used

        except Exception as e:
            print(f"Error during auto-exposure: {e}")
            return self.get_time_based(), self.get_time_based(), 0, 0, led_used
        finally:
            if led_used and led is not None:
                led.off()

import time
from datetime import datetime

import cv2
import numpy as np


CLIP_LEVEL = 250  # pixel value at or above which detail is considered lost

FAILED_METRICS = {
    "avg_brightness": 0,
    "std_dev": 0,
    "hist_std": 0,
    "contrast_ratio": 0,
    "clip_pct": 0,
    "p99": 0,
}


def calculate_image_quality(image):
    """Calculate brightness, contrast, histogram and highlight-clipping metrics."""
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
            "clip_pct": float(np.mean(gray >= CLIP_LEVEL) * 100),
            "p99": float(np.percentile(gray, 99)),
        }
    except Exception as e:
        print(f"Error calculating image quality: {e}")
        return {
            "avg_brightness": 0,
            "std_dev": 0,
            "hist_std": 0,
            "contrast_ratio": 0,
            "clip_pct": 0,
            "p99": 0,
        }


class ExposureManager:
    def __init__(
        self,
        settings,
        min_exp=5000,
        max_exp=10000000,
        target_brightness=180,
        tolerance=20,
        max_attempts=5,
        max_clip_pct=1.0,
    ):
        self.settings = settings
        self.min_exp = min_exp
        self.max_exp = max_exp
        self.target_brightness = target_brightness
        self.tolerance = tolerance
        self.max_attempts = max_attempts
        # Highlight budget: share of pixels allowed to sit at/above CLIP_LEVEL.
        # Under LED the scene centre is ~3x brighter than the frame mean, so the
        # mean alone cannot see a blown-out centre — this caps it directly.
        self.max_clip_pct = max_clip_pct

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
        if "max_clip_pct" in ae:
            self.max_clip_pct = ae["max_clip_pct"]

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
        """Return the starting exposure: recent measured exposures if any, else the schedule.

        Recent history is measured ground truth from the last few minutes, so it wins
        outright. The schedule is only a cold start — under LED it overstates the needed
        exposure by ~20x, and blending it in costs attempts the loop cannot spare.
        """
        base = self.get_time_based(now)
        if recent_history:
            ordered = sorted(recent_history)
            median = ordered[len(ordered) // 2]
            print(f"Starting from recent measured exposure: {median} μs (time-based: {base} μs)")
            return median
        return base

    def is_acceptable(self, metrics):
        """True if a measured frame is usable: highlights in budget and not badly dark."""
        if metrics["clip_pct"] > self.max_clip_pct:
            return False
        if self._is_highlight_limited(metrics):
            return True
        return abs(metrics["avg_brightness"] - self.target_brightness) <= self.tolerance * 1.5

    def _is_highlight_limited(self, metrics):
        """True when the highlight budget, not the brightness target, is the binding limit."""
        return metrics["clip_pct"] >= self.max_clip_pct * 0.8

    def _score(self, metrics):
        """Rank measured frames; lower is better. Blown highlights lose to everything else."""
        excess_clip = max(0.0, metrics["clip_pct"] - self.max_clip_pct)
        return excess_clip * 1000 + abs(metrics["avg_brightness"] - self.target_brightness)

    def _adjust_factor(self, metrics):
        """Return the exposure multiplier for this frame, or None if it is good enough."""
        clip = metrics["clip_pct"]
        brightness = metrics["avg_brightness"]

        # Highlights veto brightness: over budget, back off regardless of the mean.
        # Clipping is unambiguous, so allow a harder cut here than the 0.7 damping
        # used for mean-driven moves — a cold start can sit 20x too high.
        if clip > self.max_clip_pct:
            print(f"Clipping {clip:.2f}% over budget {self.max_clip_pct:.2f}% — reducing exposure")
            return max((self.max_clip_pct / clip) ** 0.5, 0.4)

        if abs(brightness - self.target_brightness) <= self.tolerance:
            return None

        if brightness > self.target_brightness:
            return max(self.target_brightness / max(1, brightness), 0.7)

        # Too dark, but raising exposure would blow the highlights. Accept as-is.
        if self._is_highlight_limited(metrics):
            print(
                f"Highlight-limited: brightness {brightness:.1f} below target "
                f"{self.target_brightness} but clipping already {clip:.2f}%"
            )
            return None

        return min(self.target_brightness / max(1, brightness), 1.5)

    def auto_adjust(self, camera, led=None, recent_history=None):
        """
        Run iterative auto-exposure loop.

        Turns LED on/off around test captures if provided. Only exposures that were
        actually measured are eligible to be returned.
        Returns (initial_exposure, final_exposure, metrics, led_used).
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

            measured = []  # (exposure, metrics) — every entry was actually captured

            for attempt in range(self.max_attempts):
                test_frame = camera.capture_test_frame(current_exposure)
                if test_frame is None:
                    print("Failed to capture test frame")
                    break

                metrics = calculate_image_quality(test_frame)
                measured.append((current_exposure, metrics))

                print(
                    f"Test frame {attempt + 1}: Exposure={current_exposure} μs, "
                    f"Brightness={metrics['avg_brightness']:.1f}, "
                    f"Contrast={metrics['contrast_ratio']:.1f}, "
                    f"Clipped={metrics['clip_pct']:.2f}%"
                )

                adjustment_factor = self._adjust_factor(metrics)
                if adjustment_factor is None:
                    print(f"Exposure accepted at {current_exposure} μs")
                    break

                new_exposure = int(current_exposure * adjustment_factor)
                new_exposure = max(self.min_exp, min(self.max_exp, new_exposure))
                if new_exposure == current_exposure:
                    print("Exposure at limit, stopping")
                    break

                print(
                    f"Adjusting exposure: {current_exposure} → {new_exposure} μs "
                    f"(factor: {adjustment_factor:.2f})"
                )
                current_exposure = new_exposure

            if not measured:
                print("No test frame measured, falling back to time-based exposure")
                return initial_exposure, self.get_time_based(), FAILED_METRICS, led_used

            # Return the best exposure we actually measured — never an untested adjustment.
            best_exposure, best_metrics = min(measured, key=lambda item: self._score(item[1]))
            print(
                f"Selected exposure {best_exposure} μs "
                f"(brightness {best_metrics['avg_brightness']:.1f}, "
                f"clipped {best_metrics['clip_pct']:.2f}%)"
            )
            return initial_exposure, best_exposure, best_metrics, led_used

        except Exception as e:
            print(f"Error during auto-exposure: {e}")
            return self.get_time_based(), self.get_time_based(), FAILED_METRICS, led_used
        finally:
            if led_used and led is not None:
                led.off()

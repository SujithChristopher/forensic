"""Auto-exposure control and LED lighting policy.

Owns the tuning parameters and the cross-capture state (recent exposures, last ambient
brightness, last LED state) that keep brightness consistent around the clock:

- AEC hunt on the lores stream with an LED off->on overshoot guard
- analogue-gain capping to limit noise
- multi-pass proportional correction toward target_brightness
- temporal smoothing (median blend + rate limit) to kill minute-to-minute flicker
- darkness override with hysteresis so the LED doesn't flip-flop at dusk/dawn
"""

import platform
import time

import numpy as np

from .image_quality import calculate_image_quality


class ExposureController:
    def __init__(self, camera, led, config, storage,
                 use_led=True, night_led_only=True, auto_exposure=True):
        self.camera = camera
        self.led = led          # LEDController or None
        self.config = config
        self.storage = storage

        self.use_led = use_led
        self.night_led_only = night_led_only
        self.auto_exposure = auto_exposure

        # --- brightness targets ---
        self.target_brightness = 110       # Medium brightness (0-255)
        self.brightness_tolerance = 20     # How close we need to get to target

        # --- exposure bounds (microseconds) ---
        self.min_exposure = 5000
        self.max_exposure = 10000000

        # Kept for parity with the original tuning surface (not used in the AEC path)
        self.max_exposure_attempts = 5
        self.aec_settle_time = 2.0

        # Maximum analogue gain — caps noise in dark/evening conditions
        self.max_analogue_gain = 8.0

        # LED darkness override with hysteresis to avoid dusk/dawn oscillation:
        # turn the LED on when ambient (LED-off) brightness drops below led_on_threshold,
        # and only drop back to LED-off once ambient climbs back above led_off_threshold.
        self.led_on_threshold = 50
        self.led_off_threshold = 85

        # LED off->on: AEC's settled value is from a dark scene and would overshoot.
        # Seed from this conservative baseline instead and let AEC re-hunt.
        self.led_baseline_exposure = 600000  # μs

        # Max brightness correction passes per capture (each drain-confirmed)
        self.max_correction_passes = 3

        # Temporal exposure smoothing
        self.exposure_smoothing = 0.6   # weight of the freshly-measured exposure (0-1)
        self.max_exposure_step = 2.0    # max multiplicative change vs. the last exposure

        # --- cross-capture state ---
        self.last_led_state = False
        self.last_measured_brightness = None   # may be LED-lit
        self.last_ambient_brightness = None    # LED-off; drives the hysteresis
        self.recent_exposures = []
        self.max_exposure_history = 5
        self.last_exposure_time = self.config.get_current_exposure_time()

        # Apply auto-exposure overrides from the TOML file, if any were present
        overrides = self.config.auto_exposure_overrides
        if overrides:
            if "target_brightness" in overrides:
                self.target_brightness = overrides["target_brightness"]
            if "min_exposure" in overrides:
                self.min_exposure = overrides["min_exposure"]
            if "max_exposure" in overrides:
                self.max_exposure = overrides["max_exposure"]
            if "tolerance" in overrides:
                self.brightness_tolerance = overrides["tolerance"]

    # ------------------------------------------------------------- delegation
    def get_current_exposure_time(self):
        return self.config.get_current_exposure_time()

    # -------------------------------------------------------------- LED policy
    def should_use_led(self):
        """Determine if the LED should be used based on time of day and a hysteretic
        darkness override."""
        if not self.use_led:
            return False

        # Darkness override with hysteresis: base the decision on ambient (LED-off)
        # brightness. Once the LED is engaged it stays on until ambient rises well above
        # the turn-on point, preventing dusk/dawn flip-flopping around a single threshold.
        if self.last_ambient_brightness is not None:
            threshold = self.led_off_threshold if self.last_led_state else self.led_on_threshold
            if self.last_ambient_brightness < threshold:
                return True

        if self.night_led_only:
            return self.config.is_night_time()

        return True

    def led_on(self):
        """Turn the LED on if conditions are met. Returns True on success."""
        if self.led is not None and self.led.available and self.should_use_led():
            return self.led.on()
        return False

    def led_off(self):
        if self.led is not None and self.use_led:
            self.led.off()

    # ------------------------------------------------------------- core hunt
    def simple_adjust_exposure(self, led_required=False):
        """
        Hybrid AEC/AGC exposure control with improvements for 24x7 consistency:

        1. LED state-change guard: when LED transitions off->on, AEC's settled value
           reflects a pitch-dark scene and would massively overshoot. Instead, seed
           from led_baseline_exposure so AEC re-hunts from a sane starting point.

        2. Darkness override with hysteresis: after measuring with LED off, if ambient
           brightness is below the (hysteretic) darkness threshold the scene is too dark
           regardless of the time schedule. Turn the LED on, re-run AEC, and continue.

        3. Multi-pass correction (up to max_correction_passes): each pass applies a
           proportional nudge and drains frames until metadata confirms the new exposure
           before re-measuring. Stops as soon as brightness is within tolerance.

        4. Temporal smoothing: the final exposure is blended with recent history and
           rate-limited so brightness doesn't flicker between consecutive captures.

        All metering frames come from the low-resolution lores stream to keep the hunt
        cheap; only the final saved image is captured at full resolution.
        """
        if not self.auto_exposure:
            return self.get_current_exposure_time()

        # Measure ambient (LED-off) brightness up front — the LED is off at this point
        # (turned off in the previous cycle's finally block). This feeds the LED
        # hysteresis so should_use_led() reacts to the *actual* current scene light.
        if self.camera.is_pi:
            ambient = self.camera.meter_brightness()
            if ambient is not None:
                self.last_ambient_brightness = ambient

        led_used = False
        if led_required and self.should_use_led():
            led_used = self.led_on()
            time.sleep(0.5)  # LED warm-up

        base_exposure = self.get_current_exposure_time()

        try:
            if self.camera.is_pi:
                led_just_turned_on = led_used and not self.last_led_state

                # --- Step 1: AEC settle (with LED state-change guard) ---
                if led_just_turned_on:
                    # AEC's value from the dark period would cause massive overshoot.
                    # Jump straight to the known-good LED baseline and let AEC re-hunt.
                    exposure_time = self.led_baseline_exposure
                    gain = 1.0
                    print(f"LED off->on transition: seeding from baseline {exposure_time} μs "
                          f"(skipping dark AEC value)")
                    self.camera.set_controls({
                        'AeEnable': False,
                        'ExposureTime': exposure_time,
                        'AnalogueGain': gain,
                    })
                else:
                    exposure_time, gain = self.camera.run_aec_settle()
                    print(f"AEC settled: exposure={exposure_time} μs, gain={gain:.2f}")

                # --- Step 2: cap analogue gain to limit noise ---
                if gain > self.max_analogue_gain:
                    exposure_time = min(
                        int(exposure_time * (gain / self.max_analogue_gain)),
                        self.max_exposure,
                    )
                    gain = self.max_analogue_gain
                    print(f"Gain capped at {self.max_analogue_gain:.1f}x -> "
                          f"exposure adjusted to {exposure_time} μs")

                exposure_time = max(self.min_exposure, min(self.max_exposure, exposure_time))

                # --- Step 3: lock and verify initial brightness ---
                self.camera.set_controls({
                    'AeEnable': False,
                    'ExposureTime': exposure_time,
                    'AnalogueGain': gain,
                })
                frame, _ = self.camera.drain_to_exposure(exposure_time)
                if frame is None:
                    return exposure_time

                metrics = calculate_image_quality(frame)
                brightness = metrics['avg_brightness']
                contrast = metrics['contrast_ratio']
                self.last_measured_brightness = brightness
                if not led_used:
                    # Still an ambient (LED-off) reading — keep the hysteresis input fresh.
                    self.last_ambient_brightness = brightness
                print(f"Verification: brightness={brightness:.1f} "
                      f"(target={self.target_brightness}±{self.brightness_tolerance}), "
                      f"contrast={contrast:.1f}")

                # --- Darkness override (hysteretic): scene too dark with LED off ---
                dark_thr = self.led_off_threshold if self.last_led_state else self.led_on_threshold
                if not led_used and self.use_led and brightness < dark_thr:
                    print(f"Darkness override: brightness {brightness:.1f} < {dark_thr}, "
                          f"forcing LED on")
                    led_used = self.led_on()
                    if led_used:
                        time.sleep(0.5)
                        # Start AEC from the current (dark) exposure clamped to baseline
                        # so it doesn't have to climb from a high value
                        seed = min(exposure_time, self.led_baseline_exposure)
                        self.camera.set_controls({'AeEnable': False, 'ExposureTime': seed})
                        exposure_time, gain = self.camera.run_aec_settle()
                        if gain > self.max_analogue_gain:
                            exposure_time = min(
                                int(exposure_time * (gain / self.max_analogue_gain)),
                                self.max_exposure)
                            gain = self.max_analogue_gain
                        exposure_time = max(self.min_exposure, min(self.max_exposure, exposure_time))
                        self.camera.set_controls({'AeEnable': False,
                                                  'ExposureTime': exposure_time,
                                                  'AnalogueGain': gain})
                        frame, _ = self.camera.drain_to_exposure(exposure_time)
                        if frame is not None:
                            metrics = calculate_image_quality(frame)
                            brightness = metrics['avg_brightness']
                            contrast = metrics['contrast_ratio']
                            self.last_measured_brightness = brightness
                            print(f"Post-LED-override AEC: exposure={exposure_time} μs, "
                                  f"brightness={brightness:.1f}")

                # --- Step 4: multi-pass brightness correction (drain-confirmed each pass) ---
                for pass_num in range(self.max_correction_passes):
                    if abs(brightness - self.target_brightness) <= self.brightness_tolerance:
                        break
                    correction = self.target_brightness / max(1.0, brightness)
                    correction = max(0.5, min(2.0, correction))
                    new_exposure = max(self.min_exposure,
                                       min(self.max_exposure, int(exposure_time * correction)))
                    print(f"Correction pass {pass_num+1}: {exposure_time} -> {new_exposure} μs "
                          f"(factor={correction:.2f})")
                    self.camera.set_controls({'ExposureTime': new_exposure})
                    exposure_time = new_exposure
                    check_frame, _ = self.camera.drain_to_exposure(new_exposure)
                    if check_frame is None:
                        break
                    metrics = calculate_image_quality(check_frame)
                    brightness = metrics['avg_brightness']
                    contrast = metrics['contrast_ratio']
                    self.last_measured_brightness = brightness
                    print(f"Pass {pass_num+1} result: brightness={brightness:.1f}")

                if abs(brightness - self.target_brightness) > self.brightness_tolerance * 2:
                    print(f"Warning: brightness {brightness:.1f} outside target after "
                          f"{self.max_correction_passes} correction passes — scene limits reached")

                # --- Step 5: temporal smoothing to suppress minute-to-minute flicker ---
                smoothed = self._smooth_exposure(exposure_time)
                if smoothed != exposure_time:
                    print(f"Smoothing: {exposure_time} -> {smoothed} μs "
                          f"(history {self.recent_exposures})")
                    self.camera.set_controls({'ExposureTime': smoothed})
                    check_frame, _ = self.camera.drain_to_exposure(smoothed)
                    exposure_time = smoothed
                    if check_frame is not None:
                        metrics = calculate_image_quality(check_frame)
                        brightness = metrics['avg_brightness']
                        contrast = metrics['contrast_ratio']
                        self.last_measured_brightness = brightness

            else:
                exposure_time = base_exposure
                brightness = float(self.target_brightness)
                contrast = 1.0

            self.storage.log_exposure(base_exposure, exposure_time, brightness, contrast, led_used)
            self.recent_exposures.append(exposure_time)
            if len(self.recent_exposures) > self.max_exposure_history:
                self.recent_exposures.pop(0)
            self.last_led_state = led_used

            return exposure_time

        except Exception as e:
            print(f"Error during auto-exposure: {e}")
            return base_exposure
        finally:
            if led_used:
                self.led_off()

    def _smooth_exposure(self, new_exposure):
        """Blend a freshly-measured exposure with recent history and rate-limit the
        per-capture change. Removes the minute-to-minute brightness flicker caused by
        the auto-exposure hunt re-deciding from scratch each cycle, while still tracking
        genuine light-level trends over a few captures."""
        if not self.recent_exposures:
            return new_exposure
        last = self.recent_exposures[-1]
        # Rate-limit relative to the last applied exposure.
        lo = last / self.max_exposure_step
        hi = last * self.max_exposure_step
        stepped = max(lo, min(hi, new_exposure))
        # Exponential blend against the recent median (robust to a single outlier).
        ref = float(np.median(self.recent_exposures))
        smoothed = self.exposure_smoothing * stepped + (1.0 - self.exposure_smoothing) * ref
        return int(max(self.min_exposure, min(self.max_exposure, smoothed)))

    def update_camera_exposure(self):
        """Update camera exposure settings based on time of day and auto-exposure."""
        if self.camera.is_pi:
            try:
                led_required = self.should_use_led()

                if self.auto_exposure:
                    # simple_adjust_exposure locks the exposure and drains frames until
                    # the pipeline confirms it — no extra set_controls needed here.
                    exposure_time = self.simple_adjust_exposure(led_required)
                else:
                    exposure_time = self.get_current_exposure_time()
                    self.camera.set_controls({'AeEnable': False, 'ExposureTime': exposure_time})
                    self.camera.drain_to_exposure(exposure_time)

                self.last_exposure_time = exposure_time
                print(f"Camera exposure updated: {exposure_time} μs "
                      f"({'night' if self.config.is_night_time() else 'day'} mode, "
                      f"LED: {'ON' if led_required else 'OFF'})")
                return True
            except Exception as e:
                print(f"Error updating camera exposure: {e}")
        return False

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

from .camera import summarize_metadata
from .image_quality import EMPTY_METRICS, calculate_image_quality

# Metrics carried from every metering frame into the trace CSV.
TRACE_METRICS = (
    'avg_brightness', 'clip_pct', 'p99', 'center_brightness',
    'edge_brightness', 'hotspot_ratio', 'contrast_ratio',
)


class _MeteringFailed(Exception):
    """A metering frame could not be captured; unwind to the single logging path."""

    def __init__(self, exposure_time):
        super().__init__(f"no metering frame at {exposure_time} μs")
        self.exposure_time = exposure_time


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

        # Highlight budget: max share of pixels allowed at/above CLIP_LEVEL. The LED is
        # an on-axis point source, so at night the centre runs ~2.8x the frame mean and
        # a mean on target can still mean a destroyed centre. Measured on recorded data:
        # 0.8% daylight (fine), 1.8% night (acceptable), 4.1-4.7% night (centre gone).
        # This vetoes brightness: exposure stops rising once the budget is reached.
        self.max_clip_pct = 2.0

        # A specular core stays clipped at any exposure, so the budget can be physically
        # unreachable. Once a reduction pass buys less than this relative improvement in
        # clipping, stop and keep the brighter exposure rather than darkening the whole
        # frame forever chasing pixels that will never come back.
        self.min_clip_improvement = 0.10

        # --- exposure bounds (microseconds) ---
        # min: measured — the sensor delivered 3023 μs, and hours 10-11 were pinned at a
        # 5000 μs floor with the frame still 25 points over target and 6.8% clipped.
        # max: bounded by the 60s cadence, not by the sensor. Each metering frame costs a
        # whole exposure, so a 10s ceiling could eat the interval; 1s at the gain cap
        # below is ~5x more light than the brightest LED night frame needed.
        self.min_exposure = 3000
        self.max_exposure = 1000000

        # Kept for parity with the original tuning surface (not used in the AEC path)
        self.max_exposure_attempts = 5
        self.aec_settle_time = 2.0

        # Maximum analogue gain — caps noise in dark/evening conditions. Excess gain is
        # traded for exposure time by _cap_gain. At 8.0 the AGC bought the whole night
        # with gain (5.4x median) and left exposure parked at the frame-duration ceiling;
        # the subject is static, so time is the cheaper currency.
        self.max_analogue_gain = 2.0

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

        # Per-capture decision trace, flushed to CSV at the end of each hunt.
        self._trace = []
        self._capture_id = ""

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
            if "max_clip_pct" in overrides:
                self.max_clip_pct = overrides["max_clip_pct"]
            if "max_analogue_gain" in overrides:
                self.max_analogue_gain = overrides["max_analogue_gain"]

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

    # --------------------------------------------------------- highlight veto
    def _is_highlight_limited(self, clip_pct):
        """True when the highlight budget, not the brightness target, is the binding limit."""
        return clip_pct >= self.max_clip_pct * 0.8

    def _correction_factor(self, brightness, clip_pct):
        """Exposure multiplier for a measured frame, or None if it is good enough.

        Highlights veto brightness: exposure only rises while clipping stays inside
        max_clip_pct, and is cut when it does not, however dark the mean looks. Under
        LED the mean will therefore settle below target on purpose — that is correct,
        not a failure, and is reported as the 'highlight_limited' outcome.
        """
        if clip_pct > self.max_clip_pct:
            # Clipping is unambiguous, so allow a harder cut than the mean-driven damping.
            return max((self.max_clip_pct / clip_pct) ** 0.5, 0.4)
        if abs(brightness - self.target_brightness) <= self.brightness_tolerance:
            return None
        if brightness > self.target_brightness:
            return max(self.target_brightness / max(1.0, brightness), 0.5)
        if self._is_highlight_limited(clip_pct):
            return None
        return min(self.target_brightness / max(1.0, brightness), 2.0)

    # ------------------------------------------------------- AEC helpers
    def _cap_gain(self, exposure_time, gain):
        """Trade analogue gain above the cap for exposure time, then clamp to bounds.

        Returns (exposure_time, gain, capped). Gain is read noise; exposure is free on a
        static scene, so buy light with time wherever the frame rate allows it.
        """
        capped = gain > self.max_analogue_gain
        if capped:
            exposure_time = min(int(exposure_time * (gain / self.max_analogue_gain)),
                                self.max_exposure)
            gain = self.max_analogue_gain
            print(f"Gain capped at {self.max_analogue_gain:.1f}x -> "
                  f"exposure adjusted to {exposure_time} μs")
        exposure_time = max(self.min_exposure, min(self.max_exposure, exposure_time))
        return exposure_time, gain, capped

    def _aec_after_led_on(self):
        """Re-settle AEC from the LED baseline, just after the LED has come on.

        AEC's current value was settled on a pitch-dark scene and would overshoot
        massively now the LED is lit. Seed from a known-good baseline and let AEC hunt
        down from there instead of climbing from the dark value.

        Both LED turn-on paths (the schedule and the darkness override) come through
        here — the override used to skip the baseline and re-hunt straight from the dark
        AEC value, which is how a dusk capture reached 129774 μs at 10.4% clipping.
        """
        print(f"LED off->on transition: seeding AEC from baseline "
              f"{self.led_baseline_exposure} μs (skipping the dark AEC value)")
        self.camera.set_controls({'AeEnable': False,
                                  'ExposureTime': self.led_baseline_exposure,
                                  'AnalogueGain': 1.0})
        # Wait for the seed to reach the sensor before handing control back to AEC.
        # Re-enabling AEC in the very next call leaves it hunting from the dark value it
        # already had, which is the whole thing this guard exists to prevent.
        self.camera.drain_to_exposure(self.led_baseline_exposure, 1.0)
        return self.camera.run_aec_settle()

    def _observe(self, stage, requested, frame, meta, pass_num=0, led_on=False):
        """Score a metering frame and append it to this capture's decision trace."""
        metrics = calculate_image_quality(frame) if frame is not None else dict(EMPTY_METRICS)
        row = {
            'capture_id': self._capture_id,
            'stage': stage,
            'pass_num': pass_num,
            'requested_exposure': requested,
            'led_on': led_on,
            'frame_ok': frame is not None,
        }
        row.update(summarize_metadata(meta))
        row.update({key: metrics[key] for key in TRACE_METRICS})
        self._trace.append(row)
        return metrics

    # ------------------------------------------------------------- core hunt
    def simple_adjust_exposure(self, led_required=False, capture_id=""):
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

        self._trace = []
        self._capture_id = capture_id
        gain = 1.0
        metrics = dict(EMPTY_METRICS)

        # Diagnostic-only record of how this hunt reached its answer. Kept apart from the
        # control-flow locals so every branch below contributes to one CSV row.
        state = {
            'started': time.time(),
            'outcome': 'not_pi',
            'passes_used': 0,
            'aec_exposure': None,
            'aec_gain': None,
            'gain_capped': False,
            'led_just_turned_on': False,
            'darkness_override': False,
            'pre_smoothing_exposure': None,
            'smoothing_reverted': False,
            'ambient': None,
        }

        # Measure ambient (LED-off) brightness up front — the LED is off at this point
        # (turned off in the previous cycle's finally block). This feeds the LED
        # hysteresis so should_use_led() reacts to the *actual* current scene light.
        if self.camera.is_pi:
            ambient_frame, ambient_meta = self.camera.meter_frame()
            ambient_metrics = self._observe(
                'ambient', self.last_exposure_time, ambient_frame, ambient_meta)
            if ambient_frame is not None:
                state['ambient'] = ambient_metrics['avg_brightness']
                self.last_ambient_brightness = state['ambient']

        led_used = False
        if led_required and self.should_use_led():
            led_used = self.led_on()
            time.sleep(0.5)  # LED warm-up

        base_exposure = self.get_current_exposure_time()

        try:
            if self.camera.is_pi:
                led_just_turned_on = led_used and not self.last_led_state
                state['led_just_turned_on'] = led_just_turned_on

                # --- Step 1: AEC settle (with LED state-change guard) ---
                if led_just_turned_on:
                    exposure_time, gain = self._aec_after_led_on()
                else:
                    exposure_time, gain = self.camera.run_aec_settle()
                print(f"AEC settled: exposure={exposure_time} μs, gain={gain:.2f}")

                state['aec_exposure'], state['aec_gain'] = exposure_time, gain

                # --- Step 2: cap analogue gain to limit noise ---
                exposure_time, gain, state['gain_capped'] = self._cap_gain(exposure_time, gain)

                # --- Step 3: lock and verify initial brightness ---
                self.camera.set_controls({
                    'AeEnable': False,
                    'ExposureTime': exposure_time,
                    'AnalogueGain': gain,
                })
                frame, verify_meta = self.camera.drain_to_exposure(exposure_time, gain)
                metrics = self._observe('verify', exposure_time, frame, verify_meta,
                                        led_on=led_used)
                if frame is None:
                    # Log the failure rather than returning silently — an unexplained gap
                    # in the exposure CSV is the hardest kind of fault to diagnose later.
                    state['outcome'] = "meter_frame_none"
                    raise _MeteringFailed(exposure_time)

                brightness = metrics['avg_brightness']
                contrast = metrics['contrast_ratio']
                self.last_measured_brightness = brightness
                if not led_used:
                    # Still an ambient (LED-off) reading — keep the hysteresis input fresh.
                    self.last_ambient_brightness = brightness
                print(f"Verification: brightness={brightness:.1f} "
                      f"(target={self.target_brightness}±{self.brightness_tolerance}), "
                      f"contrast={contrast:.1f}, clipped={metrics['clip_pct']:.2f}%")

                # --- Darkness override (hysteretic): scene too dark with LED off ---
                dark_thr = self.led_off_threshold if self.last_led_state else self.led_on_threshold
                if not led_used and self.use_led and brightness < dark_thr:
                    print(f"Darkness override: brightness {brightness:.1f} < {dark_thr}, "
                          f"forcing LED on")
                    state['darkness_override'] = True
                    led_used = self.led_on()
                    if led_used:
                        time.sleep(0.5)
                        # The LED has just come on here too, so this path needs the same
                        # baseline seeding as the scheduled one — and the flag, which used
                        # to be computed before this branch could ever set it.
                        state['led_just_turned_on'] = True
                        exposure_time, gain = self._aec_after_led_on()
                        exposure_time, gain, capped = self._cap_gain(exposure_time, gain)
                        state['gain_capped'] = state['gain_capped'] or capped
                        self.camera.set_controls({'AeEnable': False,
                                                  'ExposureTime': exposure_time,
                                                  'AnalogueGain': gain})
                        frame, override_meta = self.camera.drain_to_exposure(exposure_time, gain)
                        override_metrics = self._observe(
                            'override_aec', exposure_time, frame, override_meta, led_on=True)
                        if frame is not None:
                            metrics = override_metrics
                            brightness = metrics['avg_brightness']
                            contrast = metrics['contrast_ratio']
                            self.last_measured_brightness = brightness
                            print(f"Post-LED-override AEC: exposure={exposure_time} μs, "
                                  f"brightness={brightness:.1f}, "
                                  f"clipped={metrics['clip_pct']:.2f}%")

                # --- Step 4: multi-pass correction, highlight-vetoed (drain-confirmed) ---
                state['outcome'] = "passes_exhausted"
                for pass_num in range(self.max_correction_passes):
                    over_budget = metrics['clip_pct'] > self.max_clip_pct
                    prev_exposure, prev_metrics = exposure_time, metrics
                    correction = self._correction_factor(brightness, metrics['clip_pct'])
                    if correction is None:
                        off_target = (abs(brightness - self.target_brightness)
                                      > self.brightness_tolerance)
                        state['outcome'] = (
                            "highlight_limited"
                            if off_target and self._is_highlight_limited(metrics['clip_pct'])
                            else "in_tolerance")
                        break
                    new_exposure = max(self.min_exposure,
                                       min(self.max_exposure, int(exposure_time * correction)))
                    if new_exposure == exposure_time:
                        state['outcome'] = "at_exposure_limit"
                        break
                    print(f"Correction pass {pass_num+1}: {exposure_time} -> {new_exposure} μs "
                          f"(factor={correction:.2f})")
                    self.camera.set_controls({'ExposureTime': new_exposure})
                    exposure_time = new_exposure
                    state['passes_used'] = pass_num + 1
                    check_frame, check_meta = self.camera.drain_to_exposure(new_exposure, gain)
                    check_metrics = self._observe('correction', new_exposure, check_frame,
                                                  check_meta, pass_num=pass_num + 1,
                                                  led_on=led_used)
                    if check_frame is None:
                        state['outcome'] = "correction_frame_none"
                        break
                    metrics = check_metrics

                    # Irreducible highlights: this pass darkened the frame without
                    # meaningfully reducing clipping, so the clipped pixels are a
                    # specular core that no exposure can recover. Keep the brighter
                    # frame — chasing them would black out everything else.
                    if (over_budget
                            and metrics['clip_pct'] > prev_metrics['clip_pct']
                            * (1 - self.min_clip_improvement)):
                        print(f"Highlight floor: clipping {prev_metrics['clip_pct']:.2f}% -> "
                              f"{metrics['clip_pct']:.2f}% for a "
                              f"{prev_metrics['avg_brightness']:.1f} -> "
                              f"{metrics['avg_brightness']:.1f} brightness loss — "
                              f"reverting to {prev_exposure} μs")
                        exposure_time = prev_exposure
                        metrics = prev_metrics
                        brightness = metrics['avg_brightness']
                        contrast = metrics['contrast_ratio']
                        self.camera.set_controls({'ExposureTime': exposure_time})
                        self.camera.drain_to_exposure(exposure_time, gain)
                        state['outcome'] = "highlight_floor"
                        break

                    brightness = metrics['avg_brightness']
                    contrast = metrics['contrast_ratio']
                    self.last_measured_brightness = brightness
                    print(f"Pass {pass_num+1} result: brightness={brightness:.1f}, "
                          f"clipped={metrics['clip_pct']:.2f}%")

                if metrics['clip_pct'] > self.max_clip_pct:
                    print(f"Warning: clipping {metrics['clip_pct']:.2f}% still over budget "
                          f"{self.max_clip_pct:.2f}% after {state['passes_used']} pass(es) — "
                          f"illumination is too uneven to fix with exposure alone")
                elif (state['outcome'] != "highlight_limited"
                      and abs(brightness - self.target_brightness) > self.brightness_tolerance * 2):
                    print(f"Warning: brightness {brightness:.1f} outside target after "
                          f"{self.max_correction_passes} correction passes — scene limits reached")

                # --- Step 5: temporal smoothing to suppress minute-to-minute flicker ---
                smoothed = self._smooth_exposure(exposure_time)
                if smoothed != exposure_time:
                    print(f"Smoothing: {exposure_time} -> {smoothed} μs "
                          f"(history {self.recent_exposures})")
                    state['pre_smoothing_exposure'] = exposure_time
                    pre_smoothing_exposure = exposure_time
                    pre_smoothing_metrics = metrics
                    self.camera.set_controls({'ExposureTime': smoothed})
                    check_frame, smooth_meta = self.camera.drain_to_exposure(smoothed, gain)
                    smooth_metrics = self._observe('smoothing', smoothed, check_frame,
                                                   smooth_meta, led_on=led_used)
                    exposure_time = smoothed
                    if check_frame is not None:
                        metrics = smooth_metrics
                        brightness = metrics['avg_brightness']
                        contrast = metrics['contrast_ratio']
                        self.last_measured_brightness = brightness

                        # Smoothing blends toward history, which can push exposure back up
                        # past the highlight budget the correction passes just enforced.
                        # Compare against what the hunt achieved, not just the budget:
                        # on a scene sitting at its highlight floor the pre-smoothing
                        # frame is over budget too, and "over budget" alone never fires.
                        if metrics['clip_pct'] > max(self.max_clip_pct,
                                                     pre_smoothing_metrics['clip_pct']):
                            print(f"Smoothing re-clipped ({metrics['clip_pct']:.2f}%) — "
                                  f"reverting to {pre_smoothing_exposure} μs")
                            state['smoothing_reverted'] = True
                            exposure_time = pre_smoothing_exposure
                            metrics = pre_smoothing_metrics
                            brightness = metrics['avg_brightness']
                            contrast = metrics['contrast_ratio']
                            self.camera.set_controls({'ExposureTime': exposure_time})
                            self.camera.drain_to_exposure(exposure_time, gain)

            else:
                exposure_time = base_exposure
                brightness = float(self.target_brightness)
                contrast = 1.0

            # Only feed the smoothing history exposures that respected the highlight
            # budget — one blown frame would otherwise drag the median up for 5 captures.
            if metrics['clip_pct'] <= self.max_clip_pct:
                self.recent_exposures.append(exposure_time)
                if len(self.recent_exposures) > self.max_exposure_history:
                    self.recent_exposures.pop(0)
            self.last_led_state = led_used

            self._log_hunt(state, base_exposure, exposure_time, metrics, gain, led_used)
            return exposure_time

        except _MeteringFailed as failure:
            self.last_led_state = led_used
            self._log_hunt(state, base_exposure, failure.exposure_time, metrics, gain, led_used)
            return failure.exposure_time
        except Exception as e:
            print(f"Error during auto-exposure: {e}")
            state['outcome'] = f"error:{type(e).__name__}"
            self._log_hunt(state, base_exposure, base_exposure, metrics, gain, led_used,
                           error=str(e))
            return base_exposure
        finally:
            if led_used:
                self.led_off()

    def _log_hunt(self, state, schedule_exposure, final_exposure, metrics, gain, led_used,
                  error=""):
        """Write the per-capture summary row plus the per-frame decision trace."""
        record = {
            'capture_id': self._capture_id,
            'schedule_exposure': schedule_exposure,
            'aec_exposure': state['aec_exposure'],
            'aec_gain': state['aec_gain'],
            'gain_capped': state['gain_capped'],
            'analogue_gain': gain,
            'pre_smoothing_exposure': state['pre_smoothing_exposure'],
            'smoothing_reverted': state['smoothing_reverted'],
            'final_exposure': final_exposure,
            'meter_brightness': metrics['avg_brightness'],
            'meter_clip_pct': metrics['clip_pct'],
            'meter_p99': metrics['p99'],
            'meter_center_brightness': metrics['center_brightness'],
            'meter_hotspot_ratio': metrics['hotspot_ratio'],
            'contrast': metrics['contrast_ratio'],
            'ambient_brightness': state['ambient'],
            'led_used': led_used,
            'led_just_turned_on': state['led_just_turned_on'],
            'darkness_override': state['darkness_override'],
            'target_brightness': self.target_brightness,
            'max_clip_pct': self.max_clip_pct,
            'passes_used': state['passes_used'],
            'outcome': state['outcome'],
            'duration_s': round(time.time() - state['started'], 2),
            'error': error,
        }
        try:
            self.storage.log_exposure(record)
            self.storage.log_ae_trace(self._trace)
        except Exception as e:
            print(f"Error logging exposure data: {e}")

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

    def update_camera_exposure(self, capture_id=""):
        """Update camera exposure settings based on time of day and auto-exposure."""
        if self.camera.is_pi:
            try:
                led_required = self.should_use_led()

                if self.auto_exposure:
                    # simple_adjust_exposure locks the exposure and drains frames until
                    # the pipeline confirms it — no extra set_controls needed here.
                    exposure_time = self.simple_adjust_exposure(led_required, capture_id)
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

"""Tests for highlight-aware auto-exposure and the diagnostic CSV schemas.

The fake camera models the real rig: a linear sensor that clips at 255, lit by an
on-axis LED whose hotspot makes the frame centre ~2.8x brighter than the corners
(measured from the recorded night images).
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.exposure import ExposureController  # noqa: E402
from src.image_quality import calculate_image_quality  # noqa: E402
from src.storage import AE_TRACE_COLUMNS, EXPOSURE_COLUMNS, QUALITY_COLUMNS  # noqa: E402

SCHEDULE_EXPOSURE = 300000

# Gain chosen so SCHEDULE_EXPOSURE renders the uniform scene at the brightness target.
GAIN = 110 / SCHEDULE_EXPOSURE


def hotspot_field(size=200):
    """Mean-normalised LED illumination field: a broad falloff plus a small specular core.

    Fitted to the two recorded night frames, so it reproduces both anchor points —
    at frame mean 71.8 it clips 1.6% (recorded: 1.8%, the acceptable f1 night), and at
    frame mean 134 it clips 3.9% (recorded: 4.1%, the f2 night with the centre destroyed).
    A single Gaussian cannot match both; the real hotspot has a hot core.
    """
    y, x = np.mgrid[0:size, 0:size]
    r = np.hypot(y - size / 2, x - size / 2) / (size / 2)
    field = 1 + 1.2 * np.exp(-((r / 0.4) ** 2)) + 9.0 * np.exp(-((r / 0.12) ** 2))
    return field / field.mean()


def uniform_field(size=200):
    return np.ones((size, size))


class FakeCamera:
    is_pi = True

    def __init__(self, field, gain=GAIN, aec_exposure=SCHEDULE_EXPOSURE, aec_gain=1.0,
                 fail_after=None):
        self.field = field
        self.gain = gain
        self.aec_exposure = aec_exposure
        self.aec_gain = aec_gain
        self.fail_after = fail_after  # metering frames to serve before returning None
        self.exposure = aec_exposure
        self.requested = []
        self.frames_served = 0

    def render(self, exposure):
        return np.clip(self.field * self.gain * exposure, 0, 255).astype(np.uint8)

    def _frame(self):
        self.frames_served += 1
        if self.fail_after is not None and self.frames_served > self.fail_after:
            return None
        return self.render(self.exposure)

    def _meta(self):
        return {'ExposureTime': self.exposure, 'AnalogueGain': self.aec_gain,
                'DigitalGain': 1.0, 'Lux': 12.5, 'SensorTemperature': 41.0,
                'FrameDuration': 33000, 'ColourGains': (1.8, 1.6)}

    def meter_frame(self):
        return self._frame(), self._meta()

    def meter_brightness(self):
        return float(np.mean(self.render(self.exposure)))

    def set_controls(self, controls):
        if 'ExposureTime' in controls:
            self.exposure = controls['ExposureTime']
            self.requested.append(controls['ExposureTime'])

    def capture_metadata(self):
        return self._meta()

    def drain_to_exposure(self, target_exposure, tolerance=None, max_frames=8):
        self.exposure = target_exposure
        return self._frame(), self._meta()

    def run_aec_settle(self):
        self.exposure = self.aec_exposure
        return self.aec_exposure, self.aec_gain


class FakeConfig:
    auto_exposure_overrides = {
        'target_brightness': 110,
        'tolerance': 20,
        'min_exposure': 5000,
        'max_exposure': 10000000,
        'max_clip_pct': 2.0,
    }

    def __init__(self, night=True):
        self.night = night

    def get_current_exposure_time(self):
        return SCHEDULE_EXPOSURE

    def is_night_time(self):
        return self.night


class FakeStorage:
    def __init__(self):
        self.exposure_rows = []
        self.trace_rows = []

    def log_exposure(self, record):
        self.exposure_rows.append(record)

    def log_ae_trace(self, rows):
        self.trace_rows.extend(rows)


class FakeLED:
    available = True

    def __init__(self):
        self.state = False

    def on(self):
        self.state = True
        return True

    def off(self):
        self.state = False


def build(field=None, camera=None, use_led=False, **kwargs):
    camera = camera or FakeCamera(field if field is not None else uniform_field(), **kwargs)
    storage = FakeStorage()
    controller = ExposureController(camera, FakeLED() if use_led else None,
                                    FakeConfig(), storage, use_led=use_led)
    return controller, camera, storage


def measure(camera, exposure):
    return calculate_image_quality(camera.render(exposure))


# ------------------------------------------------------------------ highlight veto
def test_hotspot_scene_reduces_clipping_versus_mean_metering():
    """The core cannot be fully recovered, so the contract is 'less clipped than the
    mean-only answer', not 'inside budget' — see test_highlight_floor_stops_the_hunt."""
    controller, camera, storage = build(hotspot_field())

    final = controller.simple_adjust_exposure()

    assert measure(camera, final)['clip_pct'] < measure(camera, SCHEDULE_EXPOSURE)['clip_pct']
    assert storage.exposure_rows[-1]['meter_clip_pct'] < 2.5


def test_highlight_floor_stops_the_hunt_before_the_frame_goes_dark():
    """Regression: chasing an irreducible specular core drove brightness 103 -> 52.7."""
    controller, _, storage = build(hotspot_field())

    controller.simple_adjust_exposure()

    row = storage.exposure_rows[-1]
    assert row['outcome'] == 'highlight_floor'
    assert row['meter_brightness'] > 80


def test_uniform_scene_never_reports_a_highlight_floor():
    controller, _, storage = build(uniform_field())

    controller.simple_adjust_exposure()

    assert storage.exposure_rows[-1]['outcome'] == 'in_tolerance'


def test_hotspot_scene_lands_below_mean_only_metering():
    """A mean of 110 on this scene blows the centre; the veto must stop short of it."""
    controller, camera, _ = build(hotspot_field())
    mean_only = SCHEDULE_EXPOSURE  # renders mean ~110 by construction

    assert measure(camera, mean_only)['clip_pct'] > controller.max_clip_pct
    assert controller.simple_adjust_exposure() < mean_only


def test_correction_factor_refuses_to_brighten_at_the_highlight_budget():
    """A dark frame already spending its highlight budget must not be pushed brighter."""
    controller, _, _ = build(uniform_field())
    dark_but_clipping = controller.max_clip_pct * 0.9

    assert controller._correction_factor(60, dark_but_clipping) is None
    assert controller._correction_factor(60, 0.0) > 1  # same darkness, headroom to spare


def test_correction_factor_cuts_exposure_when_over_budget():
    controller, _, _ = build(uniform_field())

    # Over budget wins even though the mean says "far too dark, brighten".
    assert controller._correction_factor(40, controller.max_clip_pct * 4) < 1


def test_uniform_scene_still_reaches_target():
    """The veto must not cost brightness on an evenly lit scene."""
    controller, _, storage = build(uniform_field())

    controller.simple_adjust_exposure()

    row = storage.exposure_rows[-1]
    assert abs(row['meter_brightness'] - controller.target_brightness) <= controller.brightness_tolerance
    assert row['outcome'] == 'in_tolerance'


def test_dark_scene_is_brightened():
    controller, camera, storage = build(uniform_field(), gain=GAIN / 8)

    final = controller.simple_adjust_exposure()

    assert final > SCHEDULE_EXPOSURE
    assert storage.exposure_rows[-1]['meter_brightness'] > measure(camera, SCHEDULE_EXPOSURE)['avg_brightness']


def test_blown_exposure_is_kept_out_of_smoothing_history():
    """One clipped frame in the history would drag the median up for five captures."""
    controller, camera, _ = build(hotspot_field())
    camera.fail_after = 0  # no metering frames at all -> nothing measured

    controller.simple_adjust_exposure()

    assert controller.recent_exposures == []


def test_smoothing_cannot_reintroduce_clipping():
    controller, camera, storage = build(hotspot_field())
    # Seed history with a far-too-high exposure so smoothing pulls the result upward.
    controller.recent_exposures = [SCHEDULE_EXPOSURE * 4] * 5

    final = controller.simple_adjust_exposure()

    assert storage.exposure_rows[-1]['smoothing_reverted'] is True
    assert final == storage.exposure_rows[-1]['pre_smoothing_exposure']
    assert measure(camera, final)['clip_pct'] < measure(camera, SCHEDULE_EXPOSURE * 4)['clip_pct']


# ------------------------------------------------------------------- diagnostics
def test_every_hunt_writes_exactly_one_summary_row():
    controller, _, storage = build(hotspot_field())

    controller.simple_adjust_exposure(capture_id="20260731_120000")
    controller.simple_adjust_exposure(capture_id="20260731_120100")

    assert [row['capture_id'] for row in storage.exposure_rows] == [
        "20260731_120000", "20260731_120100"]


def test_metering_failure_is_logged_not_silent():
    """Regression: a None metering frame used to return with no CSV row at all."""
    controller, _, storage = build(uniform_field(), fail_after=1)

    controller.simple_adjust_exposure(capture_id="20260731_030000")

    assert len(storage.exposure_rows) == 1
    assert storage.exposure_rows[0]['outcome'] == 'meter_frame_none'
    assert storage.exposure_rows[0]['capture_id'] == "20260731_030000"


def test_trace_records_each_metering_stage():
    controller, _, storage = build(hotspot_field())

    controller.simple_adjust_exposure(capture_id="20260731_020000")

    stages = [row['stage'] for row in storage.trace_rows]
    assert stages[0] == 'ambient'
    assert 'verify' in stages
    assert 'correction' in stages
    assert all(row['capture_id'] == "20260731_020000" for row in storage.trace_rows)


def test_trace_carries_sensor_metadata_not_recoverable_from_the_jpeg():
    controller, _, storage = build(uniform_field())

    controller.simple_adjust_exposure()

    row = storage.trace_rows[-1]
    assert row['analogue_gain'] is not None
    assert row['lux'] == 12.5
    assert row['sensor_temperature'] == 41.0
    assert row['actual_exposure'] is not None


def test_summary_row_records_the_gain_and_aec_decisions():
    controller, _, storage = build(uniform_field(), aec_gain=16.0)

    controller.simple_adjust_exposure()

    row = storage.exposure_rows[-1]
    assert row['aec_gain'] == 16.0
    assert row['gain_capped'] is True
    assert row['analogue_gain'] == controller.max_analogue_gain
    assert row['duration_s'] is not None


def test_summary_row_matches_the_csv_schema():
    controller, _, storage = build(uniform_field())

    controller.simple_adjust_exposure()

    logged = set(storage.exposure_rows[-1]) | {'timestamp'}
    assert logged == set(EXPOSURE_COLUMNS)


def test_trace_row_matches_the_csv_schema():
    controller, _, storage = build(uniform_field())

    controller.simple_adjust_exposure()

    logged = set(storage.trace_rows[-1]) | {'timestamp'}
    assert logged == set(AE_TRACE_COLUMNS)


# ---------------------------------------------------------------- image metrics
def test_hotspot_ratio_detects_uneven_illumination():
    lit = calculate_image_quality(np.clip(hotspot_field() * 90, 0, 255).astype(np.uint8))
    flat = calculate_image_quality(np.full((200, 200), 90, np.uint8))

    assert lit['hotspot_ratio'] > 2.0
    assert flat['hotspot_ratio'] == pytest.approx(1.0, abs=0.01)


def test_clip_metric_sees_what_the_mean_hides():
    frame = np.clip(hotspot_field() * 130, 0, 255).astype(np.uint8)
    metrics = calculate_image_quality(frame)

    assert metrics['avg_brightness'] < 200  # mean looks acceptable
    assert metrics['clip_pct'] > 1.0        # centre is not
    assert metrics['center_brightness'] > metrics['edge_brightness']


def test_coarse_histogram_sums_to_one_hundred_percent():
    metrics = calculate_image_quality(np.full((100, 100), 90, np.uint8))

    assert sum(metrics['hist16']) == pytest.approx(100.0, abs=0.1)
    assert len(metrics['hist16']) == 16


def test_quality_schema_covers_every_logged_metric():
    metrics = calculate_image_quality(np.full((100, 100, 3), 90, np.uint8))
    logged = {'timestamp', 'capture_id', 'filename', 'histogram_std', 'contrast',
              'exposure_time', 'led_used', 'hist16', 'actual_exposure', 'analogue_gain',
              'digital_gain', 'lux', 'sensor_temperature'}
    logged |= {'avg_brightness', 'clip_pct', 'p05', 'p50', 'p99',
               'center_brightness', 'edge_brightness', 'hotspot_ratio'}

    assert logged == set(QUALITY_COLUMNS)
    assert {'clip_pct', 'hotspot_ratio', 'p99'} <= set(metrics)

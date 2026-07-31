"""Tests for highlight-aware auto-exposure.

The fake camera models the real rig: an LED hotspot in the frame centre with a
linear sensor response that clips at 255. Calibrated against the recorded night
images, where the centre measured ~2.8x brighter than the corners.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.exposure import ExposureManager, calculate_image_quality  # noqa: E402


SETTINGS = {
    "time_exposures": [{"hour": 0, "minute": 0, "exposure": 300000}],
    "day": {"start_hour": 6, "end_hour": 19},
    "auto_exposure": {
        "target_brightness": 120,
        "tolerance": 10,
        "min_exposure": 5000,
        "max_exposure": 1000000,
        "max_clip_pct": 1.0,
    },
}


def hotspot_field(size=200, peak=2.8):
    """Radial illumination field, mean-normalised, peaking at the centre like the LED."""
    y, x = np.mgrid[0:size, 0:size]
    r = np.hypot(y - size / 2, x - size / 2) / (size / 2)
    field = 1 + (peak - 1) * np.exp(-((r / 0.35) ** 2))
    return field / field.mean()


def uniform_field(size=200):
    return np.ones((size, size))


class FakeCamera:
    """Linear sensor with clipping. Records every exposure it is asked to capture."""

    def __init__(self, field, gain=120 / 300000):
        self.field = field
        self.gain = gain
        self.requested = []

    def capture_test_frame(self, exposure_time, tolerance=50):
        self.requested.append(exposure_time)
        frame = self.field * self.gain * exposure_time
        return np.clip(frame, 0, 255).astype(np.uint8)


class DeadCamera:
    def __init__(self):
        self.requested = []

    def capture_test_frame(self, exposure_time, tolerance=50):
        self.requested.append(exposure_time)
        return None


def measure(camera, exposure):
    return calculate_image_quality(camera.capture_test_frame(exposure))


@pytest.fixture
def manager():
    return ExposureManager(SETTINGS)


def test_hotspot_scene_keeps_highlights_within_budget(manager):
    camera = FakeCamera(hotspot_field())

    _, final, metrics, _ = manager.auto_adjust(camera)

    assert metrics["clip_pct"] <= manager.max_clip_pct
    # Verify against a fresh capture, not just the reported metrics.
    assert measure(camera, final)["clip_pct"] <= manager.max_clip_pct


def test_hotspot_scene_beats_mean_only_metering(manager):
    """A mean of 120 on this scene blows the centre — the fix must land below it."""
    camera = FakeCamera(hotspot_field())
    mean_only_exposure = 300000  # gain chosen so this yields mean ~120

    assert measure(camera, mean_only_exposure)["clip_pct"] > manager.max_clip_pct

    _, final, _, _ = manager.auto_adjust(camera)
    assert final < mean_only_exposure


def test_returned_exposure_was_actually_measured(manager):
    """Regression: the old loop returned an adjustment it never captured."""
    camera = FakeCamera(hotspot_field())

    _, final, _, _ = manager.auto_adjust(camera)

    assert final in camera.requested


def test_returned_metrics_match_returned_exposure(manager):
    camera = FakeCamera(hotspot_field())

    _, final, metrics, _ = manager.auto_adjust(camera)

    fresh = measure(camera, final)
    assert metrics["avg_brightness"] == pytest.approx(fresh["avg_brightness"])
    assert metrics["clip_pct"] == pytest.approx(fresh["clip_pct"])


def test_uniform_scene_reaches_target_brightness(manager):
    camera = FakeCamera(uniform_field())

    _, _, metrics, _ = manager.auto_adjust(camera)

    assert abs(metrics["avg_brightness"] - manager.target_brightness) <= manager.tolerance


def test_dark_uniform_scene_brightens(manager):
    camera = FakeCamera(uniform_field(), gain=120 / 3000000)

    initial, final, metrics, _ = manager.auto_adjust(camera)

    assert final > initial
    assert metrics["avg_brightness"] > measure(camera, initial)["avg_brightness"]


def test_cold_start_from_schedule_converges_from_far_too_high(manager):
    """The night schedule sits ~20x above what the LED-lit scene needs."""
    settings = dict(SETTINGS, time_exposures=[{"hour": 0, "minute": 0, "exposure": 5000000}])
    manager = ExposureManager(settings)
    camera = FakeCamera(hotspot_field())

    initial, final, metrics, _ = manager.auto_adjust(camera)

    assert initial == 1000000  # clamped to max_exposure
    assert metrics["clip_pct"] <= manager.max_clip_pct


def test_recent_history_overrides_stale_schedule(manager):
    """Regression: blending 30% of a 5 s schedule value wrecked a good starting point."""
    settings = dict(SETTINGS, time_exposures=[{"hour": 0, "minute": 0, "exposure": 5000000}])
    manager = ExposureManager(settings)

    assert manager.get_starting(recent_history=[200000, 210000, 205000]) == 205000


def test_cold_start_without_history_uses_schedule(manager):
    assert manager.get_starting(recent_history=None) == manager.get_time_based()


def test_camera_failure_falls_back_to_time_based(manager):
    camera = DeadCamera()

    _, final, metrics, _ = manager.auto_adjust(camera)

    assert final == manager.get_time_based()
    assert metrics["avg_brightness"] == 0


def test_exposure_stays_within_configured_limits(manager):
    camera = FakeCamera(uniform_field(), gain=120 / 50000000)

    _, final, _, _ = manager.auto_adjust(camera)

    assert manager.min_exp <= final <= manager.max_exp


def test_is_acceptable_rejects_clipped_frame(manager):
    blown = {"avg_brightness": 120, "clip_pct": 4.5, "contrast_ratio": 5}
    assert not manager.is_acceptable(blown)


def test_is_acceptable_allows_dark_highlight_limited_frame(manager):
    """Under LED the mean stays below target on purpose — that is not a failure."""
    limited = {"avg_brightness": 70, "clip_pct": 0.95, "contrast_ratio": 5}
    assert manager.is_acceptable(limited)


def test_is_acceptable_rejects_dark_frame_with_headroom(manager):
    dark = {"avg_brightness": 40, "clip_pct": 0.0, "contrast_ratio": 5}
    assert not manager.is_acceptable(dark)


def test_clip_metric_matches_recorded_night_image():
    """Sanity-check the metric against the shape of the real f2 night frames."""
    frame = np.clip(hotspot_field() * (120 / 300000) * 400000, 0, 255).astype(np.uint8)
    metrics = calculate_image_quality(frame)

    assert metrics["clip_pct"] > 1.0
    assert metrics["p99"] >= 250
    assert metrics["avg_brightness"] < 200  # mean hides the blown centre

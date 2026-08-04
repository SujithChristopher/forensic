"""Camera abstraction: Raspberry Pi (picamera2) with an OpenCV fallback.

Exposes the low-level primitives the auto-exposure controller needs — low-resolution
metering frames, exposure locking with metadata-confirmed settling, and an AEC settle —
plus the full-resolution capture-and-save used for the actual logged image.

All metering goes through the lores stream so the exposure hunt never churns
full-resolution buffers; only capture_and_save() touches the main stream.
"""

import platform
import time

import cv2
import numpy as np


def summarize_metadata(meta):
    """Pull the diagnostic fields out of a libcamera metadata dict.

    These are not recoverable from the saved JPEG afterwards, so anything used to
    reason about a bad capture has to be logged at the time it was taken.
    """
    meta = meta or {}
    colour_gains = meta.get('ColourGains') or (None, None)
    return {
        'actual_exposure': meta.get('ExposureTime'),
        'analogue_gain': meta.get('AnalogueGain'),
        'digital_gain': meta.get('DigitalGain'),
        'lux': meta.get('Lux'),
        'sensor_temperature': meta.get('SensorTemperature'),
        'frame_duration': meta.get('FrameDuration'),
        'colour_gain_r': colour_gains[0] if len(colour_gains) > 0 else None,
        'colour_gain_b': colour_gains[1] if len(colour_gains) > 1 else None,
    }


class Camera:
    # AnalogueGain lands a frame or two after ExposureTime, and under LED it is the
    # dominant control (5x+), so a settle check that ignores it measures the wrong scene.
    GAIN_TOLERANCE = 0.05

    def __init__(self, frame_size, meter_size, initial_exposure):
        self.frame_size = frame_size
        self.meter_size = meter_size
        self.is_pi = False        # True when picamera2 is driving
        self.has_lores = False    # True when the lores metering stream is configured
        self.picam2 = None
        self.cap = None           # OpenCV VideoCapture fallback

        if platform.system() == "Linux":
            self._init_rpi_camera(initial_exposure)
        else:
            self._init_opencv()

    # ------------------------------------------------------------------ init
    def _init_rpi_camera(self, initial_exposure):
        try:
            from picamera2 import Picamera2
            import libcamera
            self.picam2 = Picamera2()

            self.config = self.picam2.create_still_configuration(
                {"size": self.frame_size},
                lores={"size": self.meter_size},
                controls={"ExposureTime": initial_exposure},
                transform=libcamera.Transform(vflip=1),
            )
            self.picam2.configure(self.config)
            self.picam2.start()
            self.picam2.set_controls({'AfMode': 0, 'LensPosition': 0.0})
            self.is_pi = True
            self.has_lores = True
            print(f"PiCamera initialized with exposure time: {initial_exposure}, "
                  f"lores metering stream: {self.meter_size}, lens position: 0 (infinity)")
        except Exception as e:
            print(f"Error initializing Raspberry Pi camera: {e}")
            print("Falling back to regular camera...")
            self._init_opencv()

    def _init_opencv(self):
        try:
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
        except Exception as e:
            print(f"Warning: Could not initialize camera: {e}")
            self.cap = None

    # -------------------------------------------------------------- controls
    def set_controls(self, controls):
        self.picam2.set_controls(controls)

    def capture_metadata(self):
        return self.picam2.capture_metadata()

    @staticmethod
    def relative_tolerance(target_exposure):
        """Frame-settle tolerance scaled to the exposure. A fixed 2000 μs tolerance is
        far too tight at multi-second night exposures (it never settles) and needlessly
        loose in daylight. 5% (floored at 2000 μs) works across the whole 24h range."""
        return max(2000, int(0.05 * abs(target_exposure)))

    # -------------------------------------------------------------- metering
    def _extract_luma(self, arr, stream):
        if stream == "main":
            return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        w, h = self.meter_size
        if arr.ndim == 3:
            # Some pipelines hand back an RGB lores buffer instead of YUV420.
            return cv2.cvtColor(arr[:h, :w], cv2.COLOR_RGB2GRAY)
        # YUV420: the first h rows are the luma (brightness) plane.
        return arr[:h, :w]

    def meter_gray(self):
        """Capture a low-resolution grayscale frame for brightness metering.

        Uses the dedicated lores stream (YUV420 — the luma plane is a ready-made
        grayscale image) so the auto-exposure hunt never touches full-resolution
        buffers. Falls back to the main stream if lores is unavailable.
        """
        if self.has_lores:
            try:
                return self._extract_luma(self.picam2.capture_array("lores"), "lores")
            except Exception as e:
                print(f"lores metering failed ({e}); falling back to main stream")
        return self._extract_luma(self.picam2.capture_array("main"), "main")

    def meter_frame(self):
        """Return (grayscale metering frame, metadata) for one and the same frame.

        capture_array() and capture_metadata() each block for a *fresh* frame, so
        calling them in sequence returns pixels and metadata from two different
        frames — the metadata describes the frame after the one that was measured.
        Every exposure/gain decision made from such a pair is one frame stale.
        capture_request() hands back both halves of a single frame.
        """
        stream = "lores" if self.has_lores else "main"
        try:
            request = self.picam2.capture_request()
            try:
                return (self._extract_luma(request.make_array(stream), stream),
                        request.get_metadata())
            finally:
                request.release()
        except Exception as e:
            print(f"metering capture_request failed ({e}); falling back to unpaired capture")
            return self.meter_gray(), self.picam2.capture_metadata()

    def meter_brightness(self):
        """Mean brightness of the current scene from a lores metering frame."""
        try:
            return float(np.mean(self.meter_gray()))
        except Exception as e:
            print(f"Error measuring brightness: {e}")
            return None

    def _gain_settled(self, meta, target_gain):
        if target_gain is None:
            return True
        actual = meta.get('AnalogueGain')
        if actual is None:
            return True
        return abs(actual - target_gain) <= self.GAIN_TOLERANCE * max(target_gain, 1e-6)

    def drain_to_exposure(self, target_exposure, target_gain=None, tolerance=None,
                          max_frames=8, max_wait_s=10.0):
        """
        Discard frames until the metadata confirms the pipeline is delivering the
        requested ExposureTime *and* AnalogueGain. Returns the last measured grayscale
        frame and the metadata of that same frame.

        picamera2 applies set_controls() to a future frame, so metadata is the only
        reliable signal that a setting has landed. Both controls must be checked:
        exposure often matches on the first frame (AEC may already be sitting on the
        requested value) while the gain is still ramping, and metering that frame reports
        a scene the camera is no longer capturing.

        max_wait_s bounds the drain in wall-clock time, since a multi-second exposure
        makes each frame cost that much and the whole hunt has to fit in the 60s cadence.
        """
        if tolerance is None:
            tolerance = self.relative_tolerance(target_exposure)
        deadline = time.monotonic() + max_wait_s
        frame = None
        meta = {}
        for i in range(max_frames):
            frame, meta = self.meter_frame()
            actual = meta.get('ExposureTime', 0)
            if (abs(actual - target_exposure) <= tolerance
                    and self._gain_settled(meta, target_gain)):
                print(f"Settled after {i+1} frame(s): exposure {actual} μs "
                      f"(requested {target_exposure}), gain {meta.get('AnalogueGain')} "
                      f"(requested {target_gain})")
                break
            if time.monotonic() >= deadline:
                print(f"Settle wait exceeded {max_wait_s:.0f}s after {i+1} frame(s)")
                break
        else:
            print(f"Did not settle within {max_frames} frames "
                  f"(exposure {meta.get('ExposureTime')} μs vs {target_exposure}, "
                  f"gain {meta.get('AnalogueGain')} vs {target_gain})")
        return frame, meta

    def run_aec_settle(self, max_frames=20):
        """Enable AEC/AGC and drain frames until exposure *and* gain stop moving.

        Waiting on exposure alone returns while the gain is still climbing, and the
        gain reported at that moment is not the one the next frames will be shot at.
        """
        self.picam2.set_controls({'AeEnable': True})
        prev_exposure, prev_gain = 0, 0.0
        exposure, gain = 0, 1.0
        for _ in range(max_frames):
            _, meta = self.meter_frame()
            exposure = meta.get('ExposureTime', 0)
            gain = meta.get('AnalogueGain', 1.0)
            if (abs(exposure - prev_exposure) < self.relative_tolerance(exposure)
                    and abs(gain - prev_gain) <= self.GAIN_TOLERANCE * max(gain, 1e-6)):
                break
            prev_exposure, prev_gain = exposure, gain
        return exposure, gain

    # --------------------------------------------------------------- capture
    def capture_and_save(self, image_path):
        """Capture a full-resolution image, save it to image_path, and return
        (success, bgr_frame, metadata). The returned frame is BGR (ready for cv2
        metrics); the metadata describes the frame that was actually saved."""
        if self.is_pi:
            image_frame, meta = self._capture_main_with_metadata()
            if image_frame is not None:
                # picamera2 returns RGB; convert to BGR for cv2.imwrite
                image_frame = cv2.cvtColor(image_frame, cv2.COLOR_RGB2BGR)
                cv2.imwrite(image_path, image_frame)
                return True, image_frame, meta
            return False, None, {}
        elif self.cap is not None:
            ret, image_frame = self.cap.read()
            if ret:
                cv2.imwrite(image_path, image_frame)
                return True, image_frame, {}
            print("Warning: Could not capture image")
            return False, None, {}
        else:
            print("Warning: No camera available to capture image")
            return False, None, {}

    def _capture_main_with_metadata(self):
        """Capture the main stream together with the metadata of that same frame.

        capture_request() pairs them atomically; reading metadata separately after a
        capture_array() can describe a later frame, which would silently mislabel the
        exposure/gain a saved image was taken with.
        """
        try:
            request = self.picam2.capture_request()
            try:
                return request.make_array("main"), request.get_metadata()
            finally:
                request.release()
        except Exception as e:
            print(f"capture_request failed ({e}); falling back to capture_array")
            return self.picam2.capture_array("main"), self.picam2.capture_metadata()

    def close(self):
        if self.cap is not None:
            self.cap.release()

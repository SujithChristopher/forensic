"""Camera abstraction: Raspberry Pi (picamera2) with an OpenCV fallback.

Exposes the low-level primitives the auto-exposure controller needs — low-resolution
metering frames, exposure locking with metadata-confirmed settling, and an AEC settle —
plus the full-resolution capture-and-save used for the actual logged image.

All metering goes through the lores stream so the exposure hunt never churns
full-resolution buffers; only capture_and_save() touches the main stream.
"""

import platform

import cv2
import numpy as np


class Camera:
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
    def meter_gray(self):
        """Capture a low-resolution grayscale frame for brightness metering.

        Uses the dedicated lores stream (YUV420 — the luma plane is a ready-made
        grayscale image) so the auto-exposure hunt never touches full-resolution
        buffers. Falls back to the main stream if lores is unavailable.
        """
        if self.has_lores:
            try:
                arr = self.picam2.capture_array("lores")
                w, h = self.meter_size
                if arr.ndim == 3:
                    # Some pipelines hand back an RGB lores buffer instead of YUV420.
                    return cv2.cvtColor(arr[:h, :w], cv2.COLOR_RGB2GRAY)
                # YUV420: the first h rows are the luma (brightness) plane.
                return arr[:h, :w]
            except Exception as e:
                print(f"lores metering failed ({e}); falling back to main stream")
        frame = self.picam2.capture_array("main")
        return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    def meter_brightness(self):
        """Mean brightness of the current scene from a lores metering frame."""
        try:
            return float(np.mean(self.meter_gray()))
        except Exception as e:
            print(f"Error measuring brightness: {e}")
            return None

    def drain_to_exposure(self, target_exposure, tolerance=None, max_frames=8):
        """
        Discard frames until capture_metadata confirms the pipeline is delivering
        the requested ExposureTime. Returns the last measured grayscale frame and its
        metadata. picamera2 applies set_controls() to a future frame, not the current
        one, so reading metadata is the only reliable way to know when the setting landed.
        Metering frames come from the lores stream to keep the hunt cheap.
        """
        if tolerance is None:
            tolerance = self.relative_tolerance(target_exposure)
        frame = None
        meta = {}
        for i in range(max_frames):
            frame = self.meter_gray()
            meta = self.picam2.capture_metadata()
            actual = meta.get('ExposureTime', 0)
            if abs(actual - target_exposure) <= tolerance:
                print(f"Exposure settled after {i+1} frame(s): "
                      f"requested={target_exposure} μs, actual={actual} μs")
                break
        else:
            print(f"Exposure did not settle within {max_frames} frames "
                  f"(last actual={meta.get('ExposureTime')} μs, target={target_exposure} μs)")
        return frame, meta

    def run_aec_settle(self):
        """Enable AEC and drain frames until ExposureTime stabilises across two reads."""
        self.picam2.set_controls({'AeEnable': True})
        prev_exposure = 0
        meta = {}
        for _ in range(20):
            self.meter_gray()
            meta = self.picam2.capture_metadata()
            curr = meta.get('ExposureTime', 0)
            if abs(curr - prev_exposure) < self.relative_tolerance(curr):
                break
            prev_exposure = curr
        return meta.get('ExposureTime', prev_exposure), meta.get('AnalogueGain', 1.0)

    # --------------------------------------------------------------- capture
    def capture_and_save(self, image_path):
        """Capture a full-resolution image, save it to image_path, and return
        (success, bgr_frame). The returned frame is BGR (ready for cv2 metrics)."""
        if self.is_pi:
            image_frame = self.picam2.capture_array("main")
            if image_frame is not None:
                # picamera2 returns RGB; convert to BGR for cv2.imwrite
                image_frame = cv2.cvtColor(image_frame, cv2.COLOR_RGB2BGR)
                cv2.imwrite(image_path, image_frame)
                return True, image_frame
            return False, None
        elif self.cap is not None:
            ret, image_frame = self.cap.read()
            if ret:
                cv2.imwrite(image_path, image_frame)
                return True, image_frame
            print("Warning: Could not capture image")
            return False, None
        else:
            print("Warning: No camera available to capture image")
            return False, None

    def close(self):
        if self.cap is not None:
            self.cap.release()

import platform
import cv2


class Camera:
    def __init__(self, frame_size=(4608, 2592), exposure_time=20000):
        self.frame_size = frame_size
        self._picam2 = None
        self._still_config = None
        self._cv_camera = None

        if platform.system() == "Linux":
            self._init_rpi(exposure_time)
        else:
            self._init_opencv()

    def _init_rpi(self, exposure_time):
        try:
            from picamera2 import Picamera2
            import libcamera
            self._picam2 = Picamera2()
            self._still_config = self._picam2.create_still_configuration(
                {"size": self.frame_size},
                controls={"ExposureTime": exposure_time},
                transform=libcamera.Transform(vflip=1),
            )
            self._picam2.configure(self._still_config)
            self._picam2.start()
            print(f"PiCamera initialized with exposure time: {exposure_time}")
        except Exception as e:
            print(f"Error initializing Raspberry Pi camera: {e}")
            print("Falling back to OpenCV camera...")
            self._init_opencv()

    def _init_opencv(self):
        try:
            self._cv_camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self._cv_camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self._cv_camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self._cv_camera.set(cv2.CAP_PROP_FPS, 30)
        except Exception as e:
            print(f"Warning: Could not initialize camera: {e}")
            self._cv_camera = None

    def capture_array(self):
        """Capture a full-resolution frame. Returns ndarray or None."""
        if self._picam2 is not None:
            return self._picam2.capture_array("main")
        if self._cv_camera is not None:
            ret, frame = self._cv_camera.read()
            return frame if ret else None
        return None

    def capture_test_frame(self, exposure_time, tolerance=50):
        """Capture a lower-resolution test frame for exposure analysis. Returns ndarray or None."""
        if self._picam2 is not None:
            try:
                test_config = self._picam2.create_still_configuration({"size": (1920, 1080)})
                self._picam2.switch_mode(test_config)
                self._picam2.set_controls({"ExposureTime": exposure_time})
                buffer = None
                for _ in range(5):
                    buffer = self._picam2.capture_array("main")
                    real_exp = self._picam2.capture_metadata()["ExposureTime"]
                    print(f"Real exposure: {real_exp} μs")
                    if abs(real_exp - exposure_time) <= tolerance:
                        break
                self._picam2.switch_mode(self._still_config)
                return buffer
            except Exception as e:
                print(f"Error capturing test frame: {e}")
                return None
        if self._cv_camera is not None:
            ret, frame = self._cv_camera.read()
            return frame if ret else None
        return None

    def set_exposure(self, exposure_time):
        """Apply an exposure time (μs) to the camera."""
        if self._picam2 is not None:
            self._picam2.set_controls({"ExposureTime": exposure_time})

    def release(self):
        """Release camera resources."""
        if self._cv_camera is not None:
            self._cv_camera.release()

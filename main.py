"""Entry point for the forensic data recording system.

The implementation now lives in the `src` package (see src/recorder.py). This file is
kept as the runnable entry point so the systemd service (which runs `main.py`) and
existing docs continue to work unchanged.
"""

import os

# Must be set before picamera2/libcamera is imported (done lazily at camera init).
os.environ['LIBCAMERA_LOG_LEVELS'] = '4'

from src.recorder import DataRecorder  # noqa: E402


if __name__ == "__main__":
    # To enable LED and auto-exposure (default):
    DataRecorder(use_led=True, night_led_only=True, auto_exposure=True).main()

    # To disable auto-exposure and use only time-based exposure settings:
    # DataRecorder(use_led=True, night_led_only=True, auto_exposure=False).main()

    # To enable LED during image capture at all times:
    # DataRecorder(use_led=True, night_led_only=False, auto_exposure=True).main()

    # To disable LED during image capture:
    # DataRecorder(use_led=False, auto_exposure=True).main()

import os
os.environ['LIBCAMERA_LOG_LEVELS'] = '4'

from src.recorder import DataRecorder

if __name__ == "__main__":
    DataRecorder(use_led=True, night_led_only=True, auto_exposure=True).main()

    # To disable auto-exposure and use only time-based exposure settings:
    # DataRecorder(use_led=True, night_led_only=True, auto_exposure=False).main()

    # To enable LED during image capture at all times:
    # DataRecorder(use_led=True, night_led_only=False, auto_exposure=True).main()

    # To disable LED during image capture:
    # DataRecorder(use_led=False, auto_exposure=True).main()

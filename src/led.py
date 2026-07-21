"""Low-level LED control via gpiod.

Only the raw GPIO on/off lives here — the *decision* of whether the LED should be on
(schedule + darkness hysteresis) belongs to the ExposureController. On non-Raspberry-Pi
platforms this class is simply never constructed.
"""

import platform


class LEDController:
    """Drives the illumination LED on a single GPIO line."""

    def __init__(self, pin=27, chip_name='gpiochip4'):
        self.pin = pin
        self.chip_name = chip_name
        self.available = False
        self.chip = None
        self.led_line = None
        self._init_gpio()

    def _init_gpio(self):
        try:
            import gpiod
            self.chip = gpiod.Chip(self.chip_name)
            self.led_line = self.chip.get_line(self.pin)
            self.led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
            self.available = True
            print("LED initialized successfully")
        except Exception as e:
            print(f"Error initializing LED: {e}")
            self.available = False

    def on(self):
        """Energise the LED. Returns True on success."""
        if not self.available:
            return False
        try:
            self.led_line.set_value(1)
            print("LED turned ON")
            return True
        except Exception as e:
            print(f"Error turning LED on: {e}")
            return False

    def off(self):
        """De-energise the LED."""
        if not self.available:
            return
        try:
            self.led_line.set_value(0)
            print("LED turned OFF")
        except Exception as e:
            print(f"Error turning LED off: {e}")

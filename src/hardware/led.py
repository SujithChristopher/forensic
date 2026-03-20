import platform


class LED:
    def __init__(self, pin=27, chip="gpiochip4"):
        self.pin = pin
        self.available = False
        self._line = None

        if platform.system() == "Linux":
            try:
                import gpiod
                self._chip = gpiod.Chip(chip)
                self._line = self._chip.get_line(pin)
                self._line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
                self.available = True
                print("LED initialized successfully")
            except Exception as e:
                print(f"Error initializing LED: {e}")

    def on(self):
        """Turn LED on. Returns True if successful."""
        if self.available and self._line is not None:
            try:
                self._line.set_value(1)
                print("LED turned ON")
                return True
            except Exception as e:
                print(f"Error turning LED on: {e}")
        return False

    def off(self):
        """Turn LED off."""
        if self.available and self._line is not None:
            try:
                self._line.set_value(0)
                print("LED turned OFF")
            except Exception as e:
                print(f"Error turning LED off: {e}")

    def should_use(self, is_night, night_led_only):
        """Return True if LED should be active given time-of-day logic."""
        if not self.available:
            return False
        if night_led_only:
            return is_night
        return True

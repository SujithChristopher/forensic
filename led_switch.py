import gpiod
import time
import threading

LED_PIN = 27
chip = gpiod.Chip('gpiochip4')
led_line = chip.get_line(LED_PIN)
led_line.request(consumer="LED", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])  # Ensure it's an output pin
def toggle_led():
    """ Continuously toggles the LED on and off. """
    while True:
        led_line.set_value(1)
        time.sleep(3)
        led_line.set_value(0)
        time.sleep(3)


def led_state():
    """ Continuously reads and prints the LED state. """
    while True:
        print(f"LED State: {led_line.get_value()}")
        time.sleep(0.5)  # Adjust polling rate   


# Create threads
toggle_thread = threading.Thread(target=toggle_led, daemon=True)
state_thread = threading.Thread(target=led_state, daemon=True)

# Start threads
toggle_thread.start()
state_thread.start()

# Keep the main thread running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Exiting...")

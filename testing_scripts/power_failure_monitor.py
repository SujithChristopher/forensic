#!/usr/bin/env python3
import gpiod
import time
import threading
import logging
from twilio.rest import Client
import toml
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/home/rpi2/Documents/power_monitor.log')
    ]
)

# GPIO pin configuration
POWER_MONITOR_PIN = 12  # Pin to monitor for power failure
CHIP_NAME = 'gpiochip4'

# Paths to configuration files
SECRETS_PATH = '/home/rpi2/Documents/secrets.toml'
NUMBERS_PATH = '/home/rpi2/Documents/forensic/numbers.toml'

# Time to wait before sending alert (in seconds)
ALERT_DELAY = 60  # 1 minute

class PowerFailureMonitor(threading.Thread):
    def __init__(self, secrets_path=SECRETS_PATH, numbers_path=NUMBERS_PATH, 
                 chip_name=CHIP_NAME, pin=POWER_MONITOR_PIN, alert_delay=ALERT_DELAY):
        """Initialize the power failure monitor as a thread
        
        Args:
            secrets_path (str): Path to the secrets TOML file
            numbers_path (str): Path to the phone numbers TOML file
            chip_name (str): Name of the GPIO chip
            pin (int): GPIO pin number to monitor
            alert_delay (int): Seconds to wait before sending alert
        """
        super(PowerFailureMonitor, self).__init__()
        self.daemon = True  # Thread will exit when main program exits
        
        # Configuration
        self.secrets_path = secrets_path
        self.numbers_path = numbers_path
        self.chip_name = chip_name
        self.pin = pin
        self.alert_delay = alert_delay
        
        # State variables
        self.power_failure_detected = False
        self.alert_timer = None
        self.running = False
        self.monitor_thread = None
        self.alerted = False  # Flag to track if we've already alerted for current power failure
        
        # Setup resources
        self.load_configs()
        self.setup_twilio()
        
        # GPIO will be set up when the thread starts
        self.chip = None
        self.power_line = None

    def load_configs(self):
        """Load configuration from TOML files"""
        try:
            self.secrets = toml.load(self.secrets_path)['secrets']
            self.numbers_to_alert = toml.load(self.numbers_path)['people']['phone_numbers']
            logging.info(f"Loaded {len(self.numbers_to_alert)} contact numbers")
        except Exception as e:
            logging.error(f"Failed to load configuration: {e}")
            raise

    def setup_gpio(self):
        """Setup GPIO for power monitoring"""
        try:
            self.chip = gpiod.Chip(self.chip_name)
            # Configure as input
            self.power_line = self.chip.get_line(self.pin)
            self.power_line.request(consumer="power_monitor", type=gpiod.LINE_REQ_DIR_IN)
            logging.info(f"GPIO pin {self.pin} configured as input")
        except Exception as e:
            logging.error(f"Failed to setup GPIO: {e}")
            raise

    def setup_twilio(self):
        """Initialize Twilio client"""
        try:
            self.account_sid = self.secrets['account_sid']
            self.auth_token = self.secrets['auth_token']
            self.twilio_phone = "+17752274344"  # Your Twilio phone number
            self.client = Client(self.account_sid, self.auth_token)
            logging.info("Twilio client initialized")
        except Exception as e:
            logging.error(f"Failed to setup Twilio: {e}")
            raise

    def send_sms_alerts(self):
        """Send SMS alerts to all configured numbers"""
        message = "ALERT: Power failure detected!"
        success_count = 0
        
        for number in self.numbers_to_alert:
            try:
                self.client.messages.create(
                    from_=self.twilio_phone,
                    body=message,
                    to=number
                )
                success_count += 1
                logging.info(f"SMS sent to {number}")
            except Exception as e:
                logging.error(f"Failed to send SMS to {number}: {e}")
        
        logging.info(f"Successfully sent {success_count} SMS alerts out of {len(self.numbers_to_alert)}")

    def make_phone_calls(self):
        """Make phone calls to all configured numbers"""
        for number in self.numbers_to_alert:
            try:
                call = self.client.calls.create(
                    from_=self.twilio_phone,
                    to=number,
                    url="http://demo.twilio.com/docs/voice.xml",
                )
                logging.info(f"Call initiated to {number} (SID: {call.sid})")
                time.sleep(2)  # Brief delay between calls
            except Exception as e:
                logging.error(f"Failed to call {number}: {e}")

    def handle_power_failure(self):
        """Handle the power failure event after waiting for delay"""
        # Only send alerts if we haven't already alerted for this power failure
        if not self.alerted:
            logging.warning("Power failure confirmed after wait period. Sending alerts...")
            
            try:
                # Send SMS alerts
                self.send_sms_alerts()
                
                # Make phone calls
                self.make_phone_calls()
                
                # Mark that we've sent alerts for this power failure
                self.alerted = True
                
                logging.info("All alerts sent successfully")
            except Exception as e:
                logging.error(f"Error during alert process: {e}")
        else:
            logging.info("Power failure still ongoing. Already alerted, not sending duplicate alerts.")
        
    def start_alert_timer(self):
        """Start the timer before sending alerts"""
        if self.alert_timer is None or not self.alert_timer.is_alive():
            logging.warning(f"Power failure detected! Waiting {self.alert_delay} seconds before sending alerts...")
            self.power_failure_detected = True
            self.alert_timer = threading.Timer(self.alert_delay, self.handle_power_failure)
            self.alert_timer.daemon = True
            self.alert_timer.start()

    def cancel_alert_timer(self):
        """Cancel the alert timer if power is restored"""
        if self.alert_timer and self.alert_timer.is_alive():
            self.alert_timer.cancel()
            logging.info("Power restored. Alert cancelled.")
        
        # Reset the power failure state
        self.power_failure_detected = False
        
        # Reset the alerted state so we can alert on the next power failure
        self.alerted = False
        logging.info("Alert state reset. System will alert on next power failure.")

    def monitor_power(self):
        """Continuously monitor power status"""
        self.setup_gpio()  # Setup GPIO when monitoring starts
        
        # Initially assume power is on and we haven't alerted
        self.power_failure_detected = False
        self.alerted = False
        
        logging.info("Starting power monitoring")
        
        try:
            while self.running:
                # Read the pin status (0 = power failure, 1 = power on)
                power_status = self.power_line.get_value()
                
                if power_status == 0 and not self.power_failure_detected:
                    # Power failure detected
                    self.start_alert_timer()
                elif power_status == 1 and self.power_failure_detected:
                    # Power restored
                    self.cancel_alert_timer()
                
                # Check every second
                time.sleep(1)
                
        except Exception as e:
            logging.error(f"Error in power monitoring: {e}")
        finally:
            self.cleanup()

    def run(self):
        """Main thread method - starts the monitoring process"""
        logging.info("Power failure monitoring thread started")
        self.running = True
        self.monitor_power()

    def stop(self):
        """Stop the monitoring thread safely"""
        logging.info("Stopping power failure monitor...")
        self.running = False
        
        # Cancel any pending alerts
        if self.alert_timer and self.alert_timer.is_alive():
            self.alert_timer.cancel()
        
        # Give the thread time to clean up
        time.sleep(1)
        logging.info("Power failure monitor stopped")

    def cleanup(self):
        """Release GPIO resources"""
        if hasattr(self, 'power_line') and self.power_line:
            self.power_line.release()
        if hasattr(self, 'chip') and self.chip:
            self.chip.close()
        logging.info("Power monitoring resources released")

    def __del__(self):
        """Destructor to ensure resources are cleaned up"""
        self.stop()


# Example usage as standalone program
if __name__ == "__main__":
    try:
        # Create and start the monitor
        monitor = PowerFailureMonitor()
        monitor.start()
        
        # Keep main thread running
        print("Power failure monitor running. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # If monitor was created, stop it properly
        if 'monitor' in locals():
            monitor.stop()
            
# Example of how to use in another program:
"""
from power_failure_monitor import PowerFailureMonitor

# Create and start the monitor with default settings
monitor = PowerFailureMonitor()
monitor.start()

# Do other things in your main program...

# When done, stop the monitor
monitor.stop()
"""
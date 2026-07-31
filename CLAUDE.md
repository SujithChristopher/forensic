# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Raspberry Pi-based forensic data recording system designed for long-running monitoring. The system captures images with a camera, records temperature data from DS18B20 sensors, and can send power failure alerts via Twilio.

**Hardware Platform**: Raspberry Pi (gpiochip4 architecture)
**Primary Purpose**: Continuous environmental monitoring with image capture and temperature logging

## Running the System

### Main Application

The primary entry point is [main.py](main.py) or [auto_working.py](auto_working.py), which contain the same `DataRecorder` class implementation.

**Run the data recorder:**
```bash
python3 main.py
```

**Run as a systemd service (recommended for production):**
```bash
sudo systemctl start data-recorder.service
sudo systemctl status data-recorder.service
```

See [START_STOP_SERVICE.md](START_STOP_SERVICE.md) for complete systemd service management instructions.

### DataRecorder Configuration Options

The `DataRecorder` class accepts several initialization parameters:

```python
# Default (LED + auto-exposure enabled, LED only at night)
DataRecorder(use_led=True, night_led_only=True, auto_exposure=True).main()

# Disable auto-exposure (use time-based settings from TOML only)
DataRecorder(use_led=True, night_led_only=True, auto_exposure=False).main()

# LED on at all times
DataRecorder(use_led=True, night_led_only=False, auto_exposure=True).main()

# Disable LED completely
DataRecorder(use_led=False, auto_exposure=True).main()
```

## Key Architecture Patterns

### 1. Platform-Aware Initialization

The system automatically detects whether it's running on Linux (Raspberry Pi) or another platform and initializes hardware accordingly:

- **Linux**: Uses `picamera2` for camera, `gpiod` for GPIO, `/sys/bus/w1/devices/` for DS18B20 sensors
- **Non-Linux**: Falls back to OpenCV camera, simulated sensors (for development/testing)

This pattern is used throughout: check `platform.system() == "Linux"` before hardware access.

### 2. Dual Exposure Control System

The system uses a **two-tier exposure control strategy**:

1. **Time-based baseline exposure**: Configured in [exposure.toml](exposure.toml) with scheduled exposure times throughout the day
2. **Auto-exposure refinement**: Dynamically adjusts exposure by capturing test frames and analyzing brightness

Both systems work together: time-based provides the cold-start point, auto-exposure fine-tunes to reach target brightness (default: 120 ± 10 on 0-255 scale).

**Highlights veto brightness.** The LED is an on-axis point source, so at night the frame centre measures ~2.8x brighter than the corners. Metering on the frame mean alone cannot see that: a mean of 134 was measured with the centre at 208 and 4% of pixels clipped. Auto-exposure therefore also enforces `max_clip_pct` — the share of pixels allowed at/above 250 — and will stop short of the brightness target rather than exceed it ("highlight-limited"). Raising `target_brightness` will *not* brighten a night frame that is already at its clip budget; loosen `max_clip_pct` or fix the illumination instead.

The auto-exposure algorithm:
- Captures lower-resolution test frames (1920x1080) to determine optimal exposure
- Uses proportional adjustment with dampening to avoid oscillation
- Maintains exposure history to improve stability
- Logs all exposure data to CSV for analysis

### 3. LED Control with Time-Based Logic

LED illumination is controlled by `should_use_led()`, which considers:
- Whether LED is enabled (`use_led` flag)
- Whether night-only mode is active (`night_led_only` flag)
- Current time vs. day/night boundaries from TOML config

**GPIO Configuration**: LED on GPIO pin 27 via gpiochip4

### 4. Configuration via TOML Files

**[exposure.toml](exposure.toml)**: Camera exposure schedules, day/night boundaries, auto-exposure parameters
**[numbers.toml](numbers.toml)**: Phone numbers for power failure alerts (format: `[people]` section with `phone_numbers` array)

Both use the `tomli` library (TOML v1.0 reader).

### 5. Multi-Sensor Temperature Monitoring

The system expects up to 4 DS18B20 sensors connected via 1-Wire interface:
- Sensors auto-discovered at `/sys/bus/w1/devices/28*`
- If fewer than 4 sensors found, remaining columns logged as empty
- Temperatures logged every 1 second to daily CSV files

### 6. Daily Data Organization

Data is organized in `data/YYYY-MM-DD/` directories with three CSV files per day:
- `temp_data_{date}.csv` - Temperature readings (1-second interval)
- `exposure_data_{date}.csv` - Auto-exposure adjustment logs
- `image_quality_{date}.csv` - Image quality metrics for each captured image

Images saved as `image_{timestamp}.jpg` (captured every 60 seconds).

### 7. Power Failure Monitoring

[power_failure_monitor.py](power_failure_monitor.py) implements a threaded monitor that:
- Watches GPIO pin 12 for power status (0 = failure, 1 = normal)
- Waits 60 seconds before alerting (avoids false alarms)
- Sends SMS and makes phone calls via Twilio when power loss confirmed
- Cancels alerts if power restored during wait period
- Requires `secrets.toml` with Twilio credentials (not in repo, see .gitignore)

**Note**: Power monitoring is commented out in main.py (lines 78-79) but can be enabled.

## Development Workflow

### Testing Without Hardware

The codebase includes platform detection that enables testing on non-Raspberry Pi systems:
- Camera falls back to OpenCV VideoCapture
- Temperature sensors return simulated values
- GPIO operations are safely skipped

Simply run `python3 main.py` on any platform for basic testing.

### Hardware Dependencies

**Required for Raspberry Pi deployment:**
- `picamera2` - Camera interface
- `libcamera` - Camera controls
- `gpiod` - GPIO access (replaces deprecated RPi.GPIO)
- `opencv-python` (cv2) - Image processing
- `numpy` - Image quality calculations
- `tomli` - TOML parsing
- `twilio` - Power failure alerts (optional)

### Camera Configuration Details

**Full resolution capture**: 4608 x 2592 (main.py, auto_working.py)
**Test frame resolution**: 1920 x 1080 (for auto-exposure analysis)
**Vertical flip applied**: `libcamera.Transform(vflip=1)` - adjust if camera is mounted differently

Exposure time units: microseconds (μs)

### Image Quality Metrics

The `calculate_image_quality()` method computes:
- Average brightness (mean pixel value 0-255)
- Contrast ratio (95th percentile / 5th percentile)
- Histogram standard deviation (measure of tonal spread)
- Clipped-pixel percentage (`clip_pct`, share of pixels at/above 250) and the 99th percentile

These metrics are logged to CSV and used by auto-exposure to determine if target brightness is achieved without blowing highlights.

## File Organization

**Main implementation files:**
- [main.py](main.py) / [auto_working.py](auto_working.py) - Primary DataRecorder implementation (identical)
- [power_failure_monitor.py](power_failure_monitor.py) - Power monitoring with Twilio alerts

**Legacy/experimental files** (not used in production):
- [image_capture.py](image_capture.py) - Simpler version without LED or auto-exposure
- [image_with_led.py](image_with_led.py) - LED support without auto-exposure
- `adaptive_exposure.py`, `auto_exposure.py`, `auto_exp.py` - Early exposure experiments
- `exposure_iter_test.py`, `timelapse.py` - Testing utilities

**Utils directory:**
- [utils/file_management.py](utils/file_management.py) - Partially duplicates TOML/path logic from main
- [utils/temperature_sensor.py](utils/temperature_sensor.py) - Not currently used
- `utils/image_quality.py` - Empty file

## Important Implementation Notes

1. **Auto-exposure test frames must match final exposure**: The system captures multiple test frames until the actual exposure time matches the requested exposure (within 50μs tolerance). This ensures accurate brightness measurement.

2. **Exposure history stabilizes adjustments**: The starting exposure is the median of recent accepted exposures when any exist; the time-based schedule is used only as a cold start. The schedule's night values overstate the LED-lit requirement by ~20x (5 s scheduled vs ~300 ms measured), so blending it into a known-good exposure wastes the limited adjustment attempts.

3. **Only measured exposures are used**: `auto_adjust` records every exposure it actually captures and returns the best-scoring one. It never returns an adjustment it did not test — doing so previously caused a systematic overshoot (test frames logged brightness 105-117 while the saved image measured 134-139).

4. **LED warm-up delay**: When LED is used, 0.5 second delay allows LED to reach full brightness before capture.

5. **Error handling**: The main loop continues on exceptions rather than crashing, ensuring continuous operation despite transient errors.

6. **Resource cleanup**: LED is always turned off on exit or exception to prevent GPIO being left in active state.

## Systemd Service

The system is designed to run as `data-recorder.service`. See [START_STOP_SERVICE.md](START_STOP_SERVICE.md) for:
- Starting/stopping the service
- Enabling auto-start on boot
- Viewing logs via journalctl
- Service configuration editing

## Configuration File Formats

**exposure.toml structure:**
```toml
[exposure]
time_exposures = [
    { hour = 0, minute = 0, exposure = 5000000 },
    # ... more time-based exposure entries
]

[exposure.day]
start_hour = 6
end_hour = 19

# Optional auto-exposure settings (has defaults if omitted)
[exposure.auto_exposure]
target_brightness = 120
min_exposure = 5000
max_exposure = 1000000
tolerance = 10
max_clip_pct = 1.0   # max % of pixels allowed at/above 250 (highlight budget)
```

**numbers.toml structure:**
```toml
[people]
phone_numbers = ['+1234567890', '+0987654321']
```

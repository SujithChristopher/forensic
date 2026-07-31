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

Both systems work together: time-based provides the starting point, auto-exposure fine-tunes to reach target brightness (default: 110 ± 20 on 0-255 scale).

The auto-exposure algorithm:
- Captures lower-resolution test frames (1920x1080) to determine optimal exposure
- Uses proportional adjustment with dampening to avoid oscillation
- Maintains exposure history to improve stability
- Logs all exposure data to CSV for analysis

**Highlights veto brightness.** The LED is an on-axis point source, so at night the frame centre runs ~2.8x the frame mean. Metering on the mean alone cannot see this: a recorded frame measured mean 134 with the centre at 208 and 4% of pixels clipped to white. Auto-exposure therefore also enforces `max_clip_pct` — the share of pixels allowed at/above 250 — and stops short of the brightness target rather than exceed it.

Two outcomes describe this, both normal and both logged:
- `highlight_limited` — the mean is under target because raising exposure would blow the highlights.
- `highlight_floor` — reducing exposure has stopped buying meaningful clipping reduction (a specular core stays clipped at any exposure), so the hunt keeps the brighter frame instead of darkening the whole image chasing pixels that cannot be recovered.

Raising `target_brightness` will **not** brighten a night frame in either state. Loosen `max_clip_pct`, or fix the illumination (diffuse the LED, move it off-axis, lower its current) — that is the only real cure for uneven lighting.

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

Data is organized in `data/YYYY-MM-DD/` directories with four CSV files per day:
- `temp_data_{date}.csv` - Temperature readings (1-second interval)
- `exposure_data_{date}.csv` - One row per capture: what each stage of the exposure hunt decided, and how it ended (`outcome`)
- `ae_trace_{date}.csv` - One row per *metering frame*, so a hunt can be replayed rather than inferred
- `image_quality_{date}.csv` - Metrics for each saved full-resolution image, plus the libcamera metadata of that exact frame

**`capture_id` joins all four image-related records to each other and to the image file.** It is the `YYYYMMDD_HHMMSS` stamp taken *before* the exposure hunt (which can run for tens of seconds at night), so it matches the image filename but not the CSV `timestamp` column.

The schemas are built for post-hoc diagnosis, so they favour what cannot be recovered later. Anything measurable from a saved JPEG (brightness, clipping, hotspot ratio) is logged for convenience; the values that would otherwise be lost forever are the ones that matter:
- **Analogue/digital gain and `Lux`** — distinguishes "dark because exposure was low" from "noisy because gain was high"
- **The LED decision path** — `ambient_brightness`, `led_just_turned_on`, `darkness_override`
- **Every intermediate metering frame** — `ae_trace` records requested vs. actual exposure per frame, so a hunt that failed to settle is visible
- **`outcome`, `passes_used`, `duration_s`, `error`** — why the hunt stopped, and whether it is eating into the 60-second capture interval
- **`actual_exposure` vs. `exposure_time`** — what the sensor really used vs. what was requested

Metering happens on the 1920x1080 lores luma stream while the saved image is 4608x2592 from the main stream. Both are logged (`meter_brightness` vs. the image's `avg_brightness`), so any systematic offset between them is measurable rather than assumed.

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

`calculate_image_quality()` ([src/image_quality.py](src/image_quality.py)) computes:
- Average brightness (mean pixel value 0-255), std dev, and percentiles p05/p50/p99
- Contrast ratio (95th percentile / 5th percentile)
- Histogram standard deviation (measure of tonal spread), plus a 16-bin coarse histogram so tone distribution is analysable without re-decoding thousands of JPEGs
- `clip_pct` — % of pixels at/above 250, i.e. highlight detail lost
- `center_brightness` / `edge_brightness` / `hotspot_ratio` — the spatial split that reveals uneven LED illumination the mean cannot show

These are logged to CSV and used by auto-exposure to decide whether the target brightness is achievable without destroying the highlights.

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

2. **Exposure history stabilizes adjustments**: Recent exposures are median-blended and rate-limited (`_smooth_exposure`) to remove minute-to-minute flicker. Only exposures that respected the highlight budget enter the history — one blown frame would otherwise drag the median up for five captures. Smoothing is also re-measured and reverted if it makes clipping worse than the hunt achieved.

3. **LED warm-up delay**: When LED is used, 0.5 second delay allows LED to reach full brightness before capture.

4. **Error handling**: The main loop continues on exceptions rather than crashing, ensuring continuous operation despite transient errors.

5. **Every hunt writes exactly one exposure row**: Failure paths (no metering frame, exceptions) log a row carrying the reason in `outcome`/`error` rather than returning silently. An unexplained gap in the CSV is the hardest kind of fault to diagnose after the fact.

6. **Resource cleanup**: LED is always turned off on exit or exception to prevent GPIO being left in active state.

## Deploying to the Recorders

The two Pis sit on the LAN with no internet, so there is no GitHub in the loop. [deploy.ps1](deploy.ps1) pushes this repository to them directly over SSH.

```powershell
.\deploy.ps1 -InstallKey      # once per machine: password typed once, key auth after
.\deploy.ps1 -Setup           # once per Pi: allow pushes into the checked-out branch
.\deploy.ps1 -Deploy -Restart # every update
.\deploy.ps1 -Status          # what each Pi is running right now
```

Defaults: `cmc1@192.168.0.100` and `cmc1@192.168.0.101`, path `Documents/forensic`, service `data-recorder.service`. Override with `-ComputerName`, `-User`, `-RemotePath`, `-Service`.

Key properties:
- **Only committed code moves.** A push transfers git objects, so `data/`, `secrets.toml`, `venv/` and everything else in .gitignore cannot travel — no risk of overwriting a Pi's recorded data.
- **Per-rig edits are protected.** The Pis run `receive.denyCurrentBranch=updateInstead`, which refuses to update a dirty working tree. The script checks first and refuses rather than clobbering; `-Stash` overrides, leaving the stash on the Pi. This matters most for `exposure.toml`, which is tuned per rig — after a deploy the script prints each Pi's active `[exposure.auto_exposure]` block.
- **The push is verified.** It compares the Pi's post-push HEAD to the local commit, because a push can succeed while the checkout stays behind if `-Setup` was never run.

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
target_brightness = 110
min_exposure = 5000
max_exposure = 10000000
tolerance = 20
max_clip_pct = 2.0   # highlight budget: max % of pixels allowed at/above 250
```

`max_clip_pct` must stay above what the scene can physically reach. Measured reference: 0.8% in daylight, 1.8% on an acceptable LED night frame, 4.1-4.7% on one with the centre destroyed. A budget below the reachable floor just darkens the whole frame; the controller detects that floor and stops (`highlight_floor`), but a sane budget avoids the situation.

**numbers.toml structure:**
```toml
[people]
phone_numbers = ['+1234567890', '+0987654321']
```

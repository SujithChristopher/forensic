"""Forensic data recording system.

The monolithic DataRecorder has been split into focused modules:

- config       : exposure.toml loading + time-of-day schedule / day-night logic
- image_quality: pure brightness/contrast/histogram metrics
- led          : low-level GPIO LED control
- camera       : Pi (picamera2) / OpenCV camera with lores metering + AEC helpers
- temperature  : DS18B20 1-Wire sensor reading
- storage      : per-day directory management and CSV logging
- exposure     : auto-exposure control (AEC hunt, correction, smoothing, LED policy)
- recorder     : DataRecorder orchestrator (threads + main loop)
"""

"""Image quality metrics used by both auto-exposure and per-image logging.

Beyond mean brightness these expose *highlight* and *spatial* metrics. Both matter
because the LED is an on-axis point source: at night the frame centre measures ~2.8x
brighter than the corners, so a perfectly on-target mean can hide a blown-out centre.
Mean alone cannot distinguish the two; clip_pct and hotspot_ratio can.
"""

import cv2
import numpy as np

# Pixel value at or above which highlight detail is considered unrecoverable.
CLIP_LEVEL = 250

# Coarse histogram resolution stored per image, so tone distribution can be
# reconstructed offline without re-decoding thousands of JPEGs.
HIST_BINS = 16

EMPTY_METRICS = {
    'avg_brightness': 0,
    'std_dev': 0,
    'hist_std': 0,
    'contrast_ratio': 0,
    'clip_pct': 0,
    'p05': 0,
    'p50': 0,
    'p99': 0,
    'center_brightness': 0,
    'edge_brightness': 0,
    'hotspot_ratio': 0,
    'hist16': [0] * HIST_BINS,
}


def to_gray(image):
    """Accept BGR or single-channel luma (the lores metering stream gives us luma)."""
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def calculate_image_quality(image):
    """Brightness, contrast, histogram, highlight-clipping and hotspot metrics."""
    try:
        gray = to_gray(image)

        avg_brightness = float(np.mean(gray))
        std_dev = float(np.std(gray))

        # Histogram spread
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()  # Normalize histogram
        hist_indices = np.arange(256)
        hist_mean = np.sum(hist_indices * hist)
        hist_std = float(np.sqrt(np.sum(((hist_indices - hist_mean) ** 2) * hist)))

        p05, p50, p99 = (float(v) for v in np.percentile(gray, [5, 50, 99]))
        p_high = float(np.percentile(gray, 95))
        contrast_ratio = p_high / p05 if p05 > 0 else p_high

        # Highlight budget input: how much of the frame has lost detail entirely.
        clip_pct = float(np.mean(gray >= CLIP_LEVEL) * 100)

        # Spatial split: the LED hotspot lives in the centre, ambient light does not.
        # A high ratio at night means the LED is dominating and the mean is misleading.
        h, w = gray.shape[:2]
        center = gray[int(h * 0.35):int(h * 0.65), int(w * 0.35):int(w * 0.65)]
        center_brightness = float(np.mean(center))
        total = float(np.sum(gray, dtype=np.float64))
        center_sum = float(np.sum(center, dtype=np.float64))
        edge_count = gray.size - center.size
        edge_brightness = (total - center_sum) / edge_count if edge_count else center_brightness
        hotspot_ratio = center_brightness / edge_brightness if edge_brightness > 0 else 0.0

        # Coarse histogram as percentages, for offline tone analysis.
        counts = np.bincount(
            (gray.astype(np.uint16) * HIST_BINS // 256).ravel(), minlength=HIST_BINS
        )
        hist16 = [round(float(c) * 100.0 / gray.size, 2) for c in counts[:HIST_BINS]]

        return {
            'avg_brightness': avg_brightness,
            'std_dev': std_dev,
            'hist_std': hist_std,
            'contrast_ratio': contrast_ratio,
            'clip_pct': clip_pct,
            'p05': p05,
            'p50': p50,
            'p99': p99,
            'center_brightness': center_brightness,
            'edge_brightness': edge_brightness,
            'hotspot_ratio': hotspot_ratio,
            'hist16': hist16,
        }
    except Exception as e:
        print(f"Error calculating image quality: {e}")
        return dict(EMPTY_METRICS)

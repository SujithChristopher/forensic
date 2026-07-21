"""Image quality metrics used by both auto-exposure and per-image logging."""

import cv2
import numpy as np


def calculate_image_quality(image):
    """Calculate brightness, contrast, and histogram distribution for an image.

    Accepts either a 3-channel (BGR) image or a single-channel grayscale/luma frame
    (the lores metering stream hands us the latter).
    """
    try:
        # Convert to grayscale if the image is in color
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Average brightness
        avg_brightness = np.mean(gray)

        # Standard deviation (simple contrast measure)
        std_dev = np.std(gray)

        # Histogram spread
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()  # Normalize histogram
        hist_indices = np.arange(256)
        hist_mean = np.sum(hist_indices * hist)
        hist_std = np.sqrt(np.sum(((hist_indices - hist_mean) ** 2) * hist))

        # Contrast ratio (simplified: 95th vs 5th percentile)
        p_low = np.percentile(gray, 5)
        p_high = np.percentile(gray, 95)
        if p_low > 0:  # Avoid division by zero
            contrast_ratio = p_high / p_low
        else:
            contrast_ratio = p_high

        return {
            'avg_brightness': avg_brightness,
            'std_dev': std_dev,
            'hist_std': hist_std,
            'contrast_ratio': contrast_ratio,
        }
    except Exception as e:
        print(f"Error calculating image quality: {e}")
        return {
            'avg_brightness': 0,
            'std_dev': 0,
            'hist_std': 0,
            'contrast_ratio': 0,
        }

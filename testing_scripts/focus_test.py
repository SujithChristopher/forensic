import cv2
from picamera2 import Picamera2
# from pameratools import controls # Optional helper depending on your Pi OS build

# Initialize the camera
picam2 = Picamera2()

# Configure camera for manual lens control
config = picam2.create_preview_configuration()
picam2.configure(config)

# Start camera preview loop
picam2.start()

# Lens position scale: 0.0 (Infinity) to roughly 12.0+ (Macro close-up)
# Note: Dioptre units vary by hardware module capabilities
lens_pos = 2

print("Controls: Press 'W' to focus closer (Macro), 'S' to focus farther (Infinity). Press 'Q' to quit.")

try:
    while True:
        # Capture a single frame array for OpenCV
        frame = picam2.capture_array()
        
        # Convert RGB (Pi default) to BGR (OpenCV default)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        # Overlay the current lens position onto the frame
        cv2.putText(frame_bgr, f"Lens Position: {lens_pos:.2f}", (20, 40), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # Display the live window
        cv2.imshow("Camera Module 3 Focus Test", frame_bgr)
        
        # Update lens parameters
        picam2.set_controls({"AfMode": 0, "LensPosition": lens_pos}) # AfMode 0 is Manual

        # Keyboard polling (waits 1ms)
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('w'): # Move focus closer
            lens_pos = min(15.0, lens_pos + 0.2)
        elif key == ord('s'): # Move focus further away
            lens_pos = max(0.0, lens_pos - 0.2)
        elif key == ord('q'): # Quit application
            break

finally:
    # Clean up resources properly to prevent camera locks
    cv2.destroyAllWindows()
    picam2.stop()

import os
import cv2
import glob
import argparse
import numpy as np
from datetime import datetime
import tomli  # For reading exposure settings from TOML file

def load_exposure_settings(config_file="exposure.toml"):
    """Load exposure settings from TOML file"""
    try:
        if os.path.exists(config_file):
            with open(config_file, "rb") as f:
                config = tomli.load(f)
            
            # Extract time-based exposure settings
            if "exposure" in config and "time_exposures" in config["exposure"]:
                time_exposures = config["exposure"]["time_exposures"]
                # Sort time exposures by hour and minute for efficient lookup
                time_exposures.sort(key=lambda x: x["hour"] * 60 + x["minute"])
                
                # Extract day/night boundaries
                day_settings = None
                if "exposure" in config and "day" in config["exposure"]:
                    day_settings = config["exposure"]["day"]
                
                return {"time_exposures": time_exposures, "day": day_settings}
            
    except Exception as e:
        print(f"Error loading exposure settings: {e}")
    
    return None

def get_exposure_for_time(hour, minute, exposure_settings):
    """Determine exposure value based on hour and minute"""
    if not exposure_settings or "time_exposures" not in exposure_settings:
        return "Unknown"
        
    current_minutes = hour * 60 + minute
    time_exposures = exposure_settings["time_exposures"]
    
    # Default to the last exposure value if no match is found
    exposure_value = time_exposures[-1]["exposure"]
    
    # Find the appropriate exposure setting
    for i, setting in enumerate(time_exposures):
        setting_minutes = setting["hour"] * 60 + setting["minute"]
        
        # If this is the last entry or current time is before the next entry
        if i == len(time_exposures) - 1 or current_minutes < (time_exposures[i+1]["hour"] * 60 + time_exposures[i+1]["minute"]):
            if current_minutes >= setting_minutes:
                exposure_value = setting["exposure"]
                break
            elif i > 0:
                # Use previous setting
                exposure_value = time_exposures[i-1]["exposure"]
                break
    
    # Format the exposure value in a readable way
    exposure_ms = exposure_value / 1000
    if exposure_ms >= 1000:
        return f"{exposure_ms/1000:.1f}s"
    else:
        return f"{exposure_ms:.0f}ms"

def is_night_time(hour, day_settings):
    """Check if given hour is night time based on day settings"""
    if not day_settings:
        return False
        
    day_start = day_settings["start_hour"]
    day_end = day_settings["end_hour"]
    
    # If it's not daytime, it's nighttime
    if day_start <= day_end:
        # Simple case: day is within same calendar day
        return hour < day_start or hour >= day_end
    else:
        # Complex case: day spans across midnight
        return hour >= day_end and hour < day_start

def determine_led_status(hour, night_led_only, day_settings):
    """Determine if LED would be on based on time and settings"""
    if not night_led_only:
        return "LED: ON"
    
    if is_night_time(hour, day_settings):
        return "LED: ON"
    
    return "LED: OFF"

def add_text_overlay(image, text, position, font_scale=1.0, thickness=2, padding=10):
    """Add text with a dark semi-transparent background for better readability"""
    # Make a copy of the image to avoid modifying the original
    overlay_image = image.copy()
    
    # Get text size
    font = cv2.FONT_HERSHEY_SIMPLEX
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    
    # Create a semi-transparent rectangle behind the text
    rect_x1 = position[0] - padding
    rect_y1 = position[1] - text_height - padding
    rect_x2 = position[0] + text_width + padding
    rect_y2 = position[1] + padding
    
    cv2.rectangle(overlay_image, (rect_x1, rect_y1), (rect_x2, rect_y2), (0, 0, 0), -1)
    
    # Add text
    cv2.putText(overlay_image, text, position, font, font_scale, (255, 255, 255), thickness)
    
    # Blend the overlay with the original image
    alpha = 0.7  # Opacity of the rectangle
    cv2.addWeighted(overlay_image, alpha, image, 1 - alpha, 0, image)
    
    return image

def create_timelapse(input_dir, output_file, output_size=(640, 480), fps=24, night_led_only=True, config_file="exposure.toml"):
    """Create a timelapse video from images with overlays for LED status, exposure and time"""
    # Load exposure settings
    exposure_settings = load_exposure_settings(config_file)
    
    # Get all image files sorted by timestamp
    image_pattern = os.path.join(input_dir, "image_*.jpg")
    image_files = sorted(glob.glob(image_pattern))
    
    if not image_files:
        print(f"No images found in {input_dir}")
        return False
    
    # Output dimensions
    width, height = output_size
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # Use mp4v codec
    video_writer = cv2.VideoWriter(output_file, fourcc, fps, (width, height))
    
    if not video_writer.isOpened():
        print(f"Failed to open video writer for {output_file}")
        return False
    
    print(f"Processing {len(image_files)} images...")
    for i, image_file in enumerate(image_files):
        # Read the image
        image = cv2.imread(image_file)
        if image is None:
            print(f"Failed to read image: {image_file}")
            continue
        
        # Resize image to the desired output size
        image = cv2.resize(image, (width, height))
        
        # Extract timestamp from filename (format: image_YYYYMMDD_HHMMSS.jpg)
        filename = os.path.basename(image_file)
        timestamp_str = filename.replace("image_", "").replace(".jpg", "")
        
        try:
            # Parse timestamp
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            
            # Determine LED status
            hour = timestamp.hour
            led_status = determine_led_status(hour, night_led_only, 
                                             exposure_settings["day"] if exposure_settings else None)
            
            # Get exposure value
            exposure_str = get_exposure_for_time(hour, timestamp.minute, exposure_settings)
            
            # Format time
            time_str = f"{timestamp.hour:02d}:00"
            
            # Add overlays with larger font size
            # Adjusted positions for 640x480 resolution
            image = add_text_overlay(image, time_str, (30, 40), font_scale=1.2, thickness=2)
            image = add_text_overlay(image, exposure_str, (30, 90), font_scale=1.2, thickness=2)
            image = add_text_overlay(image, led_status, (30, 140), font_scale=1.2, thickness=2)
            
            # Write frame to video
            video_writer.write(image)
            
            # Show progress
            if i % 100 == 0:
                print(f"Processed {i}/{len(image_files)} images...")
            
        except Exception as e:
            print(f"Error processing {image_file}: {e}")
            continue
    
    # Release the video writer
    video_writer.release()
    print(f"Timelapse video created successfully: {output_file}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Create timelapse video from images with information overlays")
    parser.add_argument("--input", "-i", default="data", help="Input directory containing day folders with images")
    parser.add_argument("--output", "-o", default="timelapse.mp4", help="Output video file")
    parser.add_argument("--fps", "-f", type=int, default=24, help="Frames per second for the output video")
    parser.add_argument("--day", "-d", help="Specific day folder to process (e.g., 'day1')")
    parser.add_argument("--night-led-only", "-n", action="store_true", default=True, 
                        help="Only show LED as ON during night hours (default: True)")
    parser.add_argument("--config", "-c", default="exposure.toml", 
                        help="Path to exposure configuration TOML file")
    parser.add_argument("--width", "-w", type=int, default=640, help="Output video width")
    parser.add_argument("--height", "-ht", type=int, default=480, help="Output video height")
    
    args = parser.parse_args()
    
    # Output video dimensions
    output_size = (args.width, args.height)
    
    # If specific day is provided, process just that day
    if args.day:
        day_dir = os.path.join(args.input, args.day)
        if not os.path.exists(day_dir):
            print(f"Day directory not found: {day_dir}")
            return
        
        output_file = f"{args.day}_{args.output}"
        create_timelapse(day_dir, output_file, output_size, args.fps, args.night_led_only, args.config)
    else:
        # Process all day folders
        day_dirs = sorted([d for d in os.listdir(args.input) if d.startswith("day")])
        
        if not day_dirs:
            print(f"No day directories found in {args.input}")
            return
        
        print(f"Found {len(day_dirs)} day directories: {', '.join(day_dirs)}")
        
        for day in day_dirs:
            day_dir = os.path.join(args.input, day)
            output_file = f"{day}_{args.output}"
            print(f"\nProcessing {day}...")
            create_timelapse(day_dir, output_file, output_size, args.fps, args.night_led_only, args.config)
        
        print("\nAll timelapses created successfully!")

if __name__ == "__main__":
    main()
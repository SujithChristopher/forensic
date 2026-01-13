"""Formatters - Utility functions for formatting file sizes, durations, and dates"""

from datetime import datetime, timedelta


def format_file_size(size_bytes: int) -> str:
    """Format bytes to human-readable file size

    Args:
        size_bytes: Size in bytes

    Returns:
        Formatted size string (e.g., "12.3 MB")
    """
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024

    return f"{size:.1f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds to human-readable duration

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted duration string (e.g., "2m 30s" or "45s")
    """
    if seconds < 0:
        return "0s"

    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def format_datetime(dt: datetime) -> str:
    """Format datetime to human-readable string

    Args:
        dt: Datetime object

    Returns:
        Formatted datetime string (e.g., "Jan 13, 2:45 PM")
    """
    if not dt:
        return "Never"

    now = datetime.now()
    diff = now - dt

    # If within the last hour
    if diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() // 60)
        if minutes == 0:
            return "Just now"
        return f"{minutes}m ago"

    # If within the last day
    if diff < timedelta(days=1):
        hours = int(diff.total_seconds() // 3600)
        return f"{hours}h ago"

    # If within the last week
    if diff < timedelta(days=7):
        days = diff.days
        return f"{days}d ago"

    # Otherwise, show formatted date and time
    return dt.strftime("%b %d, %I:%M %p")


def format_transfer_rate(bytes_transferred: int, duration_seconds: float) -> str:
    """Format transfer rate in MB/s

    Args:
        bytes_transferred: Total bytes transferred
        duration_seconds: Duration in seconds

    Returns:
        Formatted rate string (e.g., "12.5 MB/s")
    """
    if duration_seconds == 0:
        return "N/A"

    rate_mbps = (bytes_transferred / (1024 * 1024)) / duration_seconds
    return f"{rate_mbps:.1f} MB/s"


def format_percentage(current: int, total: int) -> str:
    """Format as percentage

    Args:
        current: Current value
        total: Total value

    Returns:
        Formatted percentage string (e.g., "75.5%")
    """
    if total == 0:
        return "0%"

    percentage = (current / total) * 100
    return f"{percentage:.1f}%"

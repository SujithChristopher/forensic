"""FileInfo data class for storing file information in preview"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass
class FileInfo:
    """File information for preview dialog"""
    relative_path: str          # Path relative to remote_dir (e.g., "2026-01-13/image.jpg")
    remote_path: str            # Full remote path (e.g., "/home/pi/data/2026-01-13/image.jpg")
    size_bytes: int             # File size in bytes
    is_new: bool = True         # Will be transferred (not in local or size differs)
    modified_time: Optional[datetime] = None  # Last modified time on remote

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        if self.modified_time:
            data['modified_time'] = self.modified_time.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'FileInfo':
        """Create from dictionary"""
        if 'modified_time' in data and data['modified_time']:
            data['modified_time'] = datetime.fromisoformat(data['modified_time'])
        return cls(**data)

"""DeviceProfile data class for storing Raspberry Pi connection configurations"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class DeviceProfile:
    """Device profile for storing Raspberry Pi connection configurations"""

    # Core connection info
    hostname: str               # IP address or hostname
    username: str               # SSH username
    password: str               # Password (encrypted when stored)

    # Profile metadata
    name: str = ""              # User-friendly name (e.g., "Lab Pi")
    remote_dir: str = "/home/pi/data"  # Default remote directory

    # Identifiers and timestamps
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    last_successful_transfer: Optional[datetime] = None

    # Statistics
    total_transfers: int = 0
    total_files_transferred: int = 0
    total_bytes_transferred: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['created_at'] = self.created_at.isoformat()
        if self.last_used:
            data['last_used'] = self.last_used.isoformat()
        if self.last_successful_transfer:
            data['last_successful_transfer'] = self.last_successful_transfer.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'DeviceProfile':
        """Create from dictionary"""
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'last_used' in data and data['last_used']:
            data['last_used'] = datetime.fromisoformat(data['last_used'])
        if 'last_successful_transfer' in data and data['last_successful_transfer']:
            data['last_successful_transfer'] = datetime.fromisoformat(data['last_successful_transfer'])

        return cls(**data)

    def update_statistics(self, files_count: int, bytes_count: int, success: bool = True):
        """Update profile statistics after a transfer"""
        if success:
            self.last_successful_transfer = datetime.now()
            self.total_transfers += 1
            self.total_files_transferred += files_count
            self.total_bytes_transferred += bytes_count
        self.last_used = datetime.now()

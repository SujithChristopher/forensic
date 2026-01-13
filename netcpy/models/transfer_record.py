"""TransferRecord data class for tracking transfer operations"""

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class TransferRecord:
    """Record of a single transfer operation"""

    # Transfer details
    profile_id: str             # Reference to device profile
    remote_dir: str             # Remote directory transferred from
    local_dir: str              # Local directory transferred to

    # Statistics
    files_transferred: int       # Number of files transferred
    files_total: int            # Total files discovered
    bytes_transferred: int       # Total bytes transferred
    duration_seconds: float      # Time taken in seconds

    # Options and metadata
    deleted_after: bool = False  # Whether files were deleted after transfer
    success: bool = True         # Whether transfer succeeded
    error_message: Optional[str] = None  # Error message if failed

    # Identifiers and timestamps
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'TransferRecord':
        """Create from dictionary"""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)

    @property
    def transfer_rate_mbps(self) -> float:
        """Calculate transfer rate in MB/s"""
        if self.duration_seconds == 0:
            return 0
        return (self.bytes_transferred / (1024 * 1024)) / self.duration_seconds

    @property
    def files_transferred_percentage(self) -> float:
        """Calculate percentage of files transferred"""
        if self.files_total == 0:
            return 0
        return (self.files_transferred / self.files_total) * 100

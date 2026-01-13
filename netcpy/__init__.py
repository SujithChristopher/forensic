"""Network Copy Application - Raspberry Pi File Transfer Utility

Network Copy v2.0 - A comprehensive file transfer application for Raspberry Pi

Usage:
    python -m netcpy.main
    or
    from netcpy.main import main; main()
"""

__version__ = "2.0.0"
__author__ = "Forensic System"

from netcpy.models.device_profile import DeviceProfile
from netcpy.models.transfer_record import TransferRecord
from netcpy.models.file_info import FileInfo

__all__ = ["DeviceProfile", "TransferRecord", "FileInfo"]

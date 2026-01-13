"""FileAnalyzer - Analyzes remote files for preview and comparison with local files"""

import os
from typing import List, Dict, Optional
import paramiko

from netcpy.models.file_info import FileInfo


class FileAnalyzer:
    """Analyzes files for preview and comparison"""

    def __init__(self, sftp: paramiko.SFTPClient, remote_dir: str, local_dir: str):
        """Initialize FileAnalyzer

        Args:
            sftp: paramiko.SFTPClient instance for remote access
            remote_dir: Remote directory to analyze
            local_dir: Local directory to compare with
        """
        self.sftp = sftp
        self.remote_dir = remote_dir.rstrip("/")
        self.local_dir = local_dir.rstrip("/") if local_dir else ""

    def analyze(self) -> List[FileInfo]:
        """Analyze remote files and compare with local files

        Returns:
            List of FileInfo objects for all remote files
        """
        files = []
        self._get_files_recursive(self.remote_dir, "", files)
        return files

    def _get_files_recursive(self, remote_path: str, relative_path: str, files: List[FileInfo]):
        """Recursively get files from remote directory

        Args:
            remote_path: Current remote path to scan
            relative_path: Path relative to remote_dir
            files: List to append FileInfo objects to
        """
        try:
            items = self.sftp.listdir(remote_path)

            for item in items:
                item_remote_path = f"{remote_path}/{item}"
                item_relative_path = f"{relative_path}/{item}" if relative_path else item

                try:
                    # Check if it's a directory
                    self.sftp.listdir(item_remote_path)
                    # It's a directory, recurse
                    self._get_files_recursive(item_remote_path, item_relative_path, files)
                except IOError:
                    # It's a file
                    try:
                        # Get file info
                        stat = self.sftp.stat(item_remote_path)
                        is_new = self._is_file_new(item_relative_path, stat.st_size)

                        file_info = FileInfo(
                            relative_path=item_relative_path,
                            remote_path=item_remote_path,
                            size_bytes=stat.st_size,
                            is_new=is_new,
                        )
                        files.append(file_info)
                    except Exception as e:
                        print(f"Error getting file info for {item_remote_path}: {e}")

        except Exception as e:
            print(f"Error accessing {remote_path}: {e}")

    def _is_file_new(self, relative_path: str, remote_size: int) -> bool:
        """Check if a file is new (not in local or size differs)

        Args:
            relative_path: Path relative to remote_dir
            remote_size: Size of remote file

        Returns:
            True if file is new or different from local version
        """
        if not self.local_dir:
            return True

        local_path = os.path.join(self.local_dir, relative_path)

        # File doesn't exist locally
        if not os.path.exists(local_path):
            return True

        # File exists, compare sizes
        try:
            local_size = os.path.getsize(local_path)
            return local_size != remote_size
        except Exception:
            return True

    def get_total_size(self) -> int:
        """Get total size of all remote files

        Returns:
            Total size in bytes
        """
        files = self.analyze()
        return sum(f.size_bytes for f in files)

    def get_new_files_count(self) -> int:
        """Get count of files that are new (will be transferred)

        Returns:
            Number of new files
        """
        files = self.analyze()
        return sum(1 for f in files if f.is_new)

    def group_by_directory(self) -> Dict[str, List[FileInfo]]:
        """Group files by their directory

        Returns:
            Dictionary of directory -> list of FileInfo objects
        """
        files = self.analyze()
        grouped = {}

        for file_info in files:
            # Get directory from relative path
            dir_name = os.path.dirname(file_info.relative_path)
            if not dir_name:
                dir_name = "root"

            if dir_name not in grouped:
                grouped[dir_name] = []
            grouped[dir_name].append(file_info)

        return grouped

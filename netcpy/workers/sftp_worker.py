"""SftpWorker - Background thread for SFTP file transfers"""

import os
import paramiko
from typing import Optional, List
from PySide6.QtCore import QThread, Signal

from netcpy.models.file_info import FileInfo


class SftpWorker(QThread):
    """Transfers files via SFTP with optional deletion after transfer"""

    progress_update = Signal(int)  # percentage
    status_update = Signal(str)  # status message
    file_progress = Signal(str, int, int)  # (filename, bytes_transferred, total_bytes)
    finished_signal = Signal(bool, str)  # (success, message)

    def __init__(
        self,
        hostname: str,
        username: str,
        password: str,
        remote_dir: str,
        local_dir: str,
        files_to_transfer: Optional[List[FileInfo]] = None,
        delete_after: bool = False,
    ):
        """Initialize SftpWorker

        Args:
            hostname: Remote hostname or IP
            username: SSH username
            password: SSH password
            remote_dir: Remote directory to transfer from
            local_dir: Local directory to transfer to
            files_to_transfer: Optional list of FileInfo objects (from preview). If None, all files transferred.
            delete_after: Whether to delete files after transfer
        """
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        self.files_to_transfer_list = files_to_transfer  # Pre-analyzed files from preview
        self.delete_after = delete_after
        self.stop_flag = False

        # Runtime state
        self.files_to_transfer = []  # Full paths for actual transfer
        self.total_files = 0
        self.files_copied = 0
        self.new_files = 0
        self.successful_transfers = []  # Track successfully transferred files for deletion

    def _get_remote_files_recursive(self, sftp: paramiko.SFTPClient, remote_path: str, relative_path: str = ""):
        """Recursively get all files from remote directory (for backwards compatibility)"""
        try:
            items = sftp.listdir(remote_path)

            for item in items:
                item_remote_path = f"{remote_path}/{item}"
                item_relative_path = f"{relative_path}/{item}" if relative_path else item

                try:
                    # Check if it's a directory
                    sftp.listdir(item_remote_path)
                    # It's a directory, recursively get files
                    self._get_remote_files_recursive(sftp, item_remote_path, item_relative_path)
                except Exception:
                    # It's a file, add to the list
                    self.files_to_transfer.append((item_remote_path, item_relative_path))
        except Exception as e:
            self.status_update.emit(f"Error accessing {remote_path}: {str(e)}")

    def run(self):
        """Run the transfer operation"""
        try:
            # Connect to the Raspberry Pi
            self.status_update.emit("Connecting to Raspberry Pi...")
            transport = paramiko.Transport((self.hostname, 22))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            # Get list of files to transfer
            if self.files_to_transfer_list:
                # Use pre-analyzed files from preview
                self.status_update.emit("Using preview file list...")
                files_to_transfer_info = self.files_to_transfer_list
            else:
                # Fallback: discover files ourselves (backwards compatibility)
                self.status_update.emit("Getting file list recursively...")
                self.files_to_transfer = []
                self._get_remote_files_recursive(sftp, self.remote_dir)
                files_to_transfer_info = None

            # If we got FileInfo objects, convert them
            if files_to_transfer_info:
                self.files_to_transfer = [
                    (file_info.remote_path, file_info.relative_path) for file_info in files_to_transfer_info
                ]

            if not self.files_to_transfer:
                self.status_update.emit("No files found in the remote directory.")
                self.finished_signal.emit(False, "No files found")
                transport.close()
                return

            # Create local directory if it doesn't exist
            os.makedirs(self.local_dir, exist_ok=True)

            # Copy files
            self.total_files = len(self.files_to_transfer)
            self.status_update.emit(f"Found {self.total_files} files. Starting transfer...")

            self.files_copied = 0
            self.new_files = 0
            self.successful_transfers = []

            for i, (remote_path, relative_path) in enumerate(self.files_to_transfer):
                if self.stop_flag:
                    self.status_update.emit("Transfer stopped by user.")
                    self.finished_signal.emit(False, "Transfer stopped")
                    break

                local_path = os.path.join(self.local_dir, relative_path)
                local_dir = os.path.dirname(local_path)

                # Create local directory structure if it doesn't exist
                os.makedirs(local_dir, exist_ok=True)

                # Check if file already exists locally
                copy_file = True
                if os.path.exists(local_path):
                    # Compare file sizes to see if they're different
                    remote_stat = sftp.stat(remote_path)
                    local_stat = os.stat(local_path)

                    if remote_stat.st_size == local_stat.st_size:
                        # File exists and is the same size, skip it
                        copy_file = False

                if copy_file:
                    # Copy the file
                    sftp.get(remote_path, local_path)
                    self.new_files += 1
                    # Add to successful transfers for deletion later
                    self.successful_transfers.append(remote_path)

                self.files_copied += 1

                # Update progress
                self.progress_update.emit(int((self.files_copied / self.total_files) * 100))
                if self.files_copied % 10 == 0 or self.files_copied == self.total_files:
                    self.status_update.emit(f"Copied {self.files_copied}/{self.total_files} files")

            # Delete files if requested
            if self.delete_after and self.successful_transfers and not self.stop_flag:
                self.status_update.emit(f"Deleting {len(self.successful_transfers)} files from Raspberry Pi...")

                # Open SSH client for deletion
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(self.hostname, username=self.username, password=self.password)

                # Delete files in smaller batches to avoid command-line length limits
                batch_size = 20
                deleted_count = 0

                for i in range(0, len(self.successful_transfers), batch_size):
                    if self.stop_flag:
                        break

                    batch = self.successful_transfers[i : i + batch_size]
                    for remote_path in batch:
                        try:
                            # Delete the file
                            sftp.remove(remote_path)
                            deleted_count += 1

                            # Update progress occasionally
                            if deleted_count % 10 == 0:
                                self.status_update.emit(
                                    f"Deleted {deleted_count}/{len(self.successful_transfers)} files"
                                )
                        except Exception as e:
                            self.status_update.emit(f"Error deleting {remote_path}: {str(e)}")

                # Delete empty directories (from bottom up)
                if deleted_count > 0 and not self.stop_flag:
                    self.status_update.emit("Cleaning up empty directories...")

                    # Get all unique directories from file paths
                    all_dirs = set()
                    for remote_path in self.successful_transfers:
                        # Get the directory part of the path
                        dir_path = os.path.dirname(remote_path)
                        all_dirs.add(dir_path)

                    # Sort directories by depth (deepest first)
                    sorted_dirs = sorted(all_dirs, key=lambda x: x.count("/"), reverse=True)

                    # Try to remove each directory (will only work if empty)
                    removed_dirs = 0
                    for dir_path in sorted_dirs:
                        if dir_path == self.remote_dir:
                            # Don't delete the root transfer directory
                            continue

                        try:
                            # Check if directory is empty
                            if not sftp.listdir(dir_path):
                                sftp.rmdir(dir_path)
                                removed_dirs += 1
                        except Exception:
                            # Ignore errors - directory might not be empty
                            pass

                    if removed_dirs > 0:
                        self.status_update.emit(f"Removed {removed_dirs} empty directories")

                ssh.close()

                self.status_update.emit(f"Deleted {deleted_count} files from Raspberry Pi")

            # Close SFTP connection
            sftp.close()
            transport.close()

            success_msg = f"Transferred {self.new_files} new files out of {self.total_files} total files."
            if self.delete_after:
                success_msg += f" Deleted {len(self.successful_transfers)} files from Raspberry Pi."

            self.status_update.emit(f"Transfer complete! {success_msg}")
            self.finished_signal.emit(True, success_msg)

        except Exception as e:
            self.status_update.emit(f"Error: {str(e)}")
            self.finished_signal.emit(False, str(e))

    def stop(self):
        """Stop the transfer operation"""
        self.stop_flag = True

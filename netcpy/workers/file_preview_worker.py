"""FilePreviewWorker - Background thread for gathering file information before transfer"""

import paramiko
from typing import List
from PySide6.QtCore import QThread, Signal

from netcpy.models.file_info import FileInfo
from netcpy.core.file_analyzer import FileAnalyzer


class FilePreviewWorker(QThread):
    """Worker thread to gather file information before transfer for preview"""

    progress_update = Signal(int)  # Percentage of files analyzed
    status_update = Signal(str)  # Status message
    file_discovered = Signal(FileInfo)  # Emit each file as found
    finished_signal = Signal(bool, list, str)  # (success, files_list, message)

    def __init__(self, hostname: str, username: str, password: str, remote_dir: str, local_dir: str):
        """Initialize FilePreviewWorker

        Args:
            hostname: Remote hostname or IP
            username: SSH username
            password: SSH password
            remote_dir: Remote directory to analyze
            local_dir: Local directory to compare with
        """
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.local_dir = local_dir
        self.stop_flag = False

    def run(self):
        """Run the file preview analysis"""
        try:
            self.status_update.emit("Connecting to Raspberry Pi...")

            # Connect to remote host
            transport = paramiko.Transport((self.hostname, 22))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            self.status_update.emit("Analyzing files...")

            # Use FileAnalyzer to get all files
            analyzer = FileAnalyzer(sftp, self.remote_dir, self.local_dir)
            files = analyzer.analyze()

            if self.stop_flag:
                self.status_update.emit("Preview canceled by user")
                self.finished_signal.emit(False, [], "Preview canceled")
                sftp.close()
                transport.close()
                return

            if not files:
                self.status_update.emit("No files found in remote directory")
                self.finished_signal.emit(False, [], "No files found")
                sftp.close()
                transport.close()
                return

            # Calculate statistics
            total_size = sum(f.size_bytes for f in files)
            new_files_count = sum(1 for f in files if f.is_new)
            new_files_size = sum(f.size_bytes for f in files if f.is_new)

            # Close connections
            sftp.close()
            transport.close()

            # Prepare message with statistics
            message = (
                f"Found {len(files)} files ({self._format_size(total_size)}). "
                f"{new_files_count} new files ({self._format_size(new_files_size)}) "
                f"will be transferred."
            )

            self.status_update.emit("Preview complete")
            self.finished_signal.emit(True, files, message)

        except paramiko.AuthenticationException as e:
            self.status_update.emit(f"Authentication error: {str(e)}")
            self.finished_signal.emit(False, [], f"Authentication failed: {str(e)}")
        except paramiko.SSHException as e:
            self.status_update.emit(f"SSH error: {str(e)}")
            self.finished_signal.emit(False, [], f"SSH error: {str(e)}")
        except Exception as e:
            self.status_update.emit(f"Error: {str(e)}")
            self.finished_signal.emit(False, [], str(e))

    def stop(self):
        """Stop the preview operation"""
        self.stop_flag = True

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes to human readable size

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string
        """
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

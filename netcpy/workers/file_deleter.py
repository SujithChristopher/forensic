"""FileDeleter - Background thread for deleting files from remote Raspberry Pi"""

import os
import paramiko
from PySide6.QtCore import QThread, Signal


class FileDeleter(QThread):
    """Deletes files from remote Raspberry Pi and cleans up empty directories"""

    progress_update = Signal(int)  # percentage
    status_update = Signal(str)  # status message
    finished_signal = Signal(bool, str)  # (success, message)

    def __init__(self, hostname: str, username: str, password: str, file_list: list):
        """Initialize FileDeleter

        Args:
            hostname: Remote hostname or IP
            username: SSH username
            password: SSH password
            file_list: List of remote file paths to delete
        """
        super().__init__()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.file_list = file_list
        self.stop_flag = False

    def run(self):
        """Run the deletion operation"""
        try:
            # Connect to Raspberry Pi
            self.status_update.emit("Connecting to Raspberry Pi...")
            transport = paramiko.Transport((self.hostname, 22))
            transport.connect(username=self.username, password=self.password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            total_files = len(self.file_list)
            deleted_count = 0

            self.status_update.emit(f"Deleting {total_files} files...")

            # Delete files
            for i, file_path in enumerate(self.file_list):
                if self.stop_flag:
                    self.status_update.emit("Deletion stopped by user.")
                    self.finished_signal.emit(False, "Deletion stopped")
                    break

                try:
                    # Delete the file
                    sftp.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    self.status_update.emit(f"Error deleting {file_path}: {str(e)}")

                # Update progress
                self.progress_update.emit(int((i + 1) / total_files * 100))
                if (i + 1) % 10 == 0 or (i + 1) == total_files:
                    self.status_update.emit(f"Deleted {i + 1}/{total_files} files")

            # Delete empty directories (bottom-up approach)
            if deleted_count > 0 and not self.stop_flag:
                self.status_update.emit("Cleaning up empty directories...")

                # Get all directories from file paths
                all_dirs = set()
                for file_path in self.file_list:
                    dir_path = os.path.dirname(file_path)
                    all_dirs.add(dir_path)

                # Sort directories by depth (deepest first)
                sorted_dirs = sorted(all_dirs, key=lambda x: x.count("/"), reverse=True)

                removed_dirs = 0
                for dir_path in sorted_dirs:
                    try:
                        # Check if directory is empty before removing
                        if not sftp.listdir(dir_path):
                            sftp.rmdir(dir_path)
                            removed_dirs += 1
                    except Exception:
                        # Directory might not be empty or might have been already removed
                        pass

                if removed_dirs > 0:
                    self.status_update.emit(f"Removed {removed_dirs} empty directories")

            # Close connection
            sftp.close()
            transport.close()

            self.status_update.emit(f"Deletion complete. {deleted_count} files deleted.")
            self.finished_signal.emit(True, f"Deleted {deleted_count} files")

        except Exception as e:
            self.status_update.emit(f"Error: {str(e)}")
            self.finished_signal.emit(False, str(e))

    def stop(self):
        """Stop the deletion operation"""
        self.stop_flag = True

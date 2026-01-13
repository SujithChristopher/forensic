"""TransferHistory - Manages transfer history using SQLite database"""

import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from netcpy.models.transfer_record import TransferRecord


class TransferHistory:
    """Tracks and persists transfer history using SQLite"""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize TransferHistory

        Args:
            db_path: Path to SQLite database. Defaults to ~/.rpi_transfer/history.db
        """
        self.db_path = db_path or Path.home() / ".rpi_transfer" / "history.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection

        Returns:
            sqlite3.Connection with row factory set
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_database(self):
        """Initialize database schema if needed"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Create transfer_records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transfer_records (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    remote_dir TEXT NOT NULL,
                    local_dir TEXT NOT NULL,
                    files_transferred INTEGER NOT NULL,
                    files_total INTEGER NOT NULL,
                    bytes_transferred INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    deleted_after INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    error_message TEXT,
                    timestamp TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_profile_id ON transfer_records(profile_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON transfer_records(timestamp)
            """)

            conn.commit()
        except Exception as e:
            print(f"Error initializing database: {e}")
        finally:
            conn.close()

    def add_record(self, record: TransferRecord) -> bool:
        """Add a transfer record

        Args:
            record: TransferRecord to add

        Returns:
            True if successful, False otherwise
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transfer_records
                (id, profile_id, remote_dir, local_dir, files_transferred, files_total,
                 bytes_transferred, duration_seconds, deleted_after, success,
                 error_message, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.profile_id,
                record.remote_dir,
                record.local_dir,
                record.files_transferred,
                record.files_total,
                record.bytes_transferred,
                record.duration_seconds,
                1 if record.deleted_after else 0,
                1 if record.success else 0,
                record.error_message,
                record.timestamp.isoformat(),
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding transfer record: {e}")
            return False
        finally:
            conn.close()

    def get_recent_transfers(self, limit: int = 20) -> List[TransferRecord]:
        """Get recent transfers across all profiles

        Args:
            limit: Maximum number of records to return

        Returns:
            List of TransferRecord objects sorted by timestamp (newest first)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM transfer_records
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))

            records = []
            for row in cursor.fetchall():
                record = self._row_to_record(row)
                records.append(record)

            return records
        except Exception as e:
            print(f"Error fetching recent transfers: {e}")
            return []
        finally:
            conn.close()

    def get_transfers_by_profile(self, profile_id: str, limit: int = 50) -> List[TransferRecord]:
        """Get transfers for a specific profile

        Args:
            profile_id: Profile ID to filter by
            limit: Maximum number of records to return

        Returns:
            List of TransferRecord objects sorted by timestamp (newest first)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM transfer_records
                WHERE profile_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (profile_id, limit))

            records = []
            for row in cursor.fetchall():
                record = self._row_to_record(row)
                records.append(record)

            return records
        except Exception as e:
            print(f"Error fetching transfers for profile: {e}")
            return []
        finally:
            conn.close()

    def get_statistics(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Get transfer statistics

        Args:
            profile_id: Optional profile ID to filter by. If None, returns global statistics

        Returns:
            Dictionary with statistics
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Build query
            where_clause = "WHERE profile_id = ?" if profile_id else ""
            params = (profile_id,) if profile_id else ()

            # Query all statistics
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_transfers,
                    SUM(files_transferred) as total_files,
                    SUM(bytes_transferred) as total_bytes,
                    AVG(duration_seconds) as avg_duration,
                    MAX(timestamp) as last_transfer,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_transfers,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_transfers
                FROM transfer_records
                {where_clause}
            """, params)

            row = cursor.fetchone()
            return {
                "total_transfers": row["total_transfers"] or 0,
                "total_files": row["total_files"] or 0,
                "total_bytes": row["total_bytes"] or 0,
                "avg_duration": row["avg_duration"] or 0,
                "last_transfer": row["last_transfer"],
                "successful_transfers": row["successful_transfers"] or 0,
                "failed_transfers": row["failed_transfers"] or 0,
            }
        except Exception as e:
            print(f"Error fetching statistics: {e}")
            return {
                "total_transfers": 0,
                "total_files": 0,
                "total_bytes": 0,
                "avg_duration": 0,
                "last_transfer": None,
                "successful_transfers": 0,
                "failed_transfers": 0,
            }
        finally:
            conn.close()

    def cleanup_old_records(self, keep_days: int = 90) -> int:
        """Delete transfer records older than specified days

        Args:
            keep_days: Keep records from the last N days

        Returns:
            Number of records deleted
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cutoff_date = (datetime.now() - timedelta(days=keep_days)).isoformat()

            cursor.execute("""
                DELETE FROM transfer_records
                WHERE timestamp < ?
            """, (cutoff_date,))

            conn.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"Error cleaning up old records: {e}")
            return 0
        finally:
            conn.close()

    def delete_transfers_for_profile(self, profile_id: str) -> int:
        """Delete all transfer records for a profile

        Args:
            profile_id: Profile ID

        Returns:
            Number of records deleted
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transfer_records WHERE profile_id = ?", (profile_id,))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"Error deleting profile transfers: {e}")
            return 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TransferRecord:
        """Convert database row to TransferRecord

        Args:
            row: sqlite3.Row object

        Returns:
            TransferRecord instance
        """
        return TransferRecord(
            id=row["id"],
            profile_id=row["profile_id"],
            remote_dir=row["remote_dir"],
            local_dir=row["local_dir"],
            files_transferred=row["files_transferred"],
            files_total=row["files_total"],
            bytes_transferred=row["bytes_transferred"],
            duration_seconds=row["duration_seconds"],
            deleted_after=bool(row["deleted_after"]),
            success=bool(row["success"]),
            error_message=row["error_message"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

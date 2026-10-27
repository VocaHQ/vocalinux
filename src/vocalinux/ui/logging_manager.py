"""
Logging manager for VocaLinux.

This module provides centralized logging functionality with UI integration,
allowing users to view, filter, and export application logs for debugging.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..utils.paths import data_dir

logger = logging.getLogger(__name__)


class LogRecord:
    """Represents a single log record with additional metadata."""

    def __init__(
        self, timestamp: datetime, level: str, logger_name: str, message: str, module: str = ""
    ):
        self.timestamp = timestamp
        self.level = level
        self.logger_name = logger_name
        self.message = message
        self.module = module

    def to_dict(self):
        """Convert to dictionary for easy serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "logger_name": self.logger_name,
            "message": self.message,
            "module": self.module,
        }

    def __str__(self):
        """String representation for display."""
        time_str = self.timestamp.strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
        return f"[{time_str}] {self.level:8} {self.logger_name:20} | {self.message}"


class LoggingManager:
    """
    Centralized logging manager for VocaLinux.

    This class captures all application logs, stores them in memory,
    and provides functionality for viewing, filtering, and exporting logs.
    """

    def __init__(self, max_records: int = 1000):
        """
        Initialize the logging manager.

        Args:
            max_records: Maximum number of log records to keep in memory
        """
        self.max_records = max_records
        self.log_records: list[LogRecord] = []
        self.log_callbacks: list[Callable[[LogRecord], None]] = []
        self.lock = threading.Lock()

        # Create logs directory ($XDG_DATA_HOME/vocalinux/logs; Flatpak-safe)
        self.logs_dir = Path(data_dir()) / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Set up custom log handler
        self.handler = LoggingHandler(self)
        self.handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        self.handler.setFormatter(formatter)

        # Add handler to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self.handler)

        logger.info("Logging manager initialized")

    def add_log_record(self, record: LogRecord):
        """
        Add a new log record.

        Args:
            record: The log record to add
        """
        with self.lock:
            self.log_records.append(record)

            # Trim old records if we exceed max_records
            if len(self.log_records) > self.max_records:
                self.log_records = self.log_records[-self.max_records :]

            # Notify callbacks
            for callback in self.log_callbacks:
                try:
                    callback(record)
                except Exception as e:
                    # Don't let callback errors break logging
                    print(f"Error in log callback: {e}")

    def register_callback(self, callback: Callable[[LogRecord], None]):
        """
        Register a callback to be called when new log records are added.

        Args:
            callback: Function to call with new log records
        """
        with self.lock:
            self.log_callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[LogRecord], None]):
        """
        Unregister a log callback.

        Args:
            callback: The callback to remove
        """
        with self.lock:
            try:
                self.log_callbacks.remove(callback)
            except ValueError:
                pass

    def get_logs(
        self,
        level_filter: Optional[str] = None,
        module_filter: Optional[str] = None,
        last_n: Optional[int] = None,
    ) -> list[LogRecord]:
        """
        Get log records with optional filtering.

        Args:
            level_filter: Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            module_filter: Filter by module name (partial match)
            last_n: Return only the last N records

        Returns:
            List of filtered log records
        """
        with self.lock:
            records = self.log_records.copy()

        # Apply filters
        if level_filter:
            records = [r for r in records if r.level == level_filter]

        if module_filter:
            records = [r for r in records if module_filter.lower() in r.logger_name.lower()]

        # Return last N records
        if last_n:
            records = records[-last_n:]

        return records

    def export_logs(
        self, filepath: str, level_filter: Optional[str] = None, module_filter: Optional[str] = None
    ) -> bool:
        """
        Export logs to a file.

        Args:
            filepath: Path to save the log file
            level_filter: Filter by log level
            module_filter: Filter by module name

        Returns:
            True if export was successful, False otherwise
        """
        try:
            records = self.get_logs(level_filter, module_filter)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("VocaLinux Log Export\n")
                f.write(f"Generated: {datetime.now().isoformat()}\n")
                f.write(f"Total Records: {len(records)}\n")
                if level_filter:
                    f.write(f"Level Filter: {level_filter}\n")
                if module_filter:
                    f.write(f"Module Filter: {module_filter}\n")
                f.write("=" * 80 + "\n\n")

                for record in records:
                    f.write(str(record) + "\n")

            logger.info(f"Exported {len(records)} log records to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to export logs: {e}")
            return False

    def clear_logs(self):
        """Clear all stored log records."""
        with self.lock:
            self.log_records.clear()
        logger.info("Log records cleared")

    def get_log_stats(self) -> dict:
        """
        Get statistics about the current logs.

        Returns:
            Dictionary with log statistics
        """
        with self.lock:
            records = self.log_records.copy()

        if not records:
            return {"total": 0, "by_level": {}, "by_module": {}, "oldest": None, "newest": None}

        # Count by level
        by_level: dict[str, int] = {}
        for record in records:
            by_level[record.level] = by_level.get(record.level, 0) + 1

        # Count by module
        by_module: dict[str, int] = {}
        for record in records:
            module = (
                record.logger_name.split(".")[0]
                if "." in record.logger_name
                else record.logger_name
            )
            by_module[module] = by_module.get(module, 0) + 1

        return {
            "total": len(records),
            "by_level": by_level,
            "by_module": by_module,
            "oldest": records[0].timestamp if records else None,
            "newest": records[-1].timestamp if records else None,
        }


class LoggingHandler(logging.Handler):
    """Custom logging handler that feeds records to the LoggingManager."""

    def __init__(self, logging_manager: LoggingManager):
        super().__init__()
        self.logging_manager = logging_manager
        # Track depth to prevent recursive logging
        self._emitting = False

    def emit(self, record: logging.LogRecord):
        """
        Emit a log record to the logging manager.

        Args:
            record: The logging record to emit
        """
        # Prevent recursive calls
        if self._emitting:
            return

        try:
            self._emitting = True

            # Create our custom log record
            log_record = LogRecord(
                timestamp=datetime.fromtimestamp(record.created),
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                module=getattr(record, "module", record.name.split(".")[0]),
            )

            # Add to logging manager
            self.logging_manager.add_log_record(log_record)

        except Exception:
            # Don't let logging errors break the application
            self.handleError(record)
        finally:
            self._emitting = False


# Global logging manager instance
_logging_manager: Optional[LoggingManager] = None


def get_logging_manager() -> LoggingManager:
    """
    Get the global logging manager instance.

    Returns:
        The global LoggingManager instance
    """
    global _logging_manager
    if _logging_manager is None:
        _logging_manager = LoggingManager()
    return _logging_manager


def initialize_logging():
    """Initialize the global logging manager."""
    global _logging_manager
    if _logging_manager is None:
        _logging_manager = LoggingManager()
        logger.info("Global logging manager initialized")

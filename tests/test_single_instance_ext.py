"""
Tests for single_instance module.

Tests cover lock acquisition, release, PID file handling, and process checking.
"""

import fcntl
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, mock_open, patch

import vocalinux.single_instance as single_instance_module
from vocalinux.utils.paths import data_dir


class TestAcquireLock(unittest.TestCase):
    """Tests for acquire_lock() function."""

    def setUp(self):
        """Reset global state before each test."""
        single_instance_module._lock_file = None

    def tearDown(self):
        """Clean up after each test."""
        single_instance_module._lock_file = None

    @patch("vocalinux.single_instance._get_lock_file_fd")
    @patch("os.ftruncate")
    @patch("os.write")
    @patch("os.lseek")
    @patch("fcntl.flock")
    @patch("os.getpid")
    def test_acquire_lock_success(
        self, mock_getpid, mock_flock, mock_lseek, mock_write, mock_ftruncate, mock_get_fd
    ):
        """Test successfully acquiring lock on first run."""
        mock_getpid.return_value = 12345
        mock_get_fd.return_value = 5

        result = single_instance_module.acquire_lock()

        self.assertTrue(result)
        mock_flock.assert_called_once_with(5, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mock_ftruncate.assert_called_once_with(5, 0)
        mock_write.assert_called_once_with(5, b"12345\n")
        mock_lseek.assert_called_once_with(5, 0, os.SEEK_SET)

    @patch("vocalinux.single_instance._get_lock_file_fd")
    @patch("fcntl.flock")
    def test_acquire_lock_already_running_oserror(self, mock_flock, mock_get_fd):
        """Test acquiring lock when another instance is running (OSError)."""
        mock_get_fd.return_value = 5
        mock_flock.side_effect = OSError("Resource temporarily unavailable")

        result = single_instance_module.acquire_lock()

        self.assertFalse(result)
        mock_flock.assert_called_once_with(5, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @patch("vocalinux.single_instance._get_lock_file_fd")
    @patch("fcntl.flock")
    def test_acquire_lock_already_running_ioerror(self, mock_flock, mock_get_fd):
        """Test acquiring lock when another instance is running (IOError)."""
        mock_get_fd.return_value = 5
        mock_flock.side_effect = IOError("Device or resource busy")

        result = single_instance_module.acquire_lock()

        self.assertFalse(result)

    @patch("vocalinux.single_instance._get_lock_file_fd")
    @patch("fcntl.flock")
    def test_acquire_lock_unexpected_error(self, mock_flock, mock_get_fd):
        """Test acquiring lock with unexpected error (fails open)."""
        mock_get_fd.return_value = 5
        mock_flock.side_effect = Exception("Unexpected error")

        result = single_instance_module.acquire_lock()

        # Should return True (fail open) but log error
        self.assertTrue(result)


class TestReleaseLock(unittest.TestCase):
    """Tests for release_lock() function."""

    def setUp(self):
        """Reset global state before each test."""
        single_instance_module._lock_file = None

    def tearDown(self):
        """Clean up after each test."""
        single_instance_module._lock_file = None

    @patch("fcntl.flock")
    @patch("os.close")
    def test_release_lock_success(self, mock_close, mock_flock):
        """Test successfully releasing lock."""
        single_instance_module._lock_file = 5

        single_instance_module.release_lock()

        mock_flock.assert_called_once_with(5, fcntl.LOCK_UN)
        mock_close.assert_called_once_with(5)
        self.assertIsNone(single_instance_module._lock_file)

    @patch("fcntl.flock")
    @patch("os.close")
    def test_release_lock_oserror(self, mock_close, mock_flock):
        """Test release_lock with OSError (still cleans up)."""
        single_instance_module._lock_file = 5
        mock_flock.side_effect = OSError("Bad file descriptor")

        single_instance_module.release_lock()

        # Should still clear the global state even on error
        self.assertIsNone(single_instance_module._lock_file)

    @patch("fcntl.flock")
    @patch("os.close")
    def test_release_lock_ioerror(self, mock_close, mock_flock):
        """Test release_lock with IOError (still cleans up)."""
        single_instance_module._lock_file = 5
        mock_flock.side_effect = IOError("I/O error")

        single_instance_module.release_lock()

        self.assertIsNone(single_instance_module._lock_file)

    def test_release_lock_no_lock_held(self):
        """Test releasing lock when none is held."""
        single_instance_module._lock_file = None

        # Should not raise, just do nothing
        single_instance_module.release_lock()

        self.assertIsNone(single_instance_module._lock_file)


class TestGetLockFileFd(unittest.TestCase):
    """Tests for _get_lock_file_fd() function."""

    def setUp(self):
        """Reset global state before each test."""
        single_instance_module._lock_file = None

    def tearDown(self):
        """Clean up after each test."""
        single_instance_module._lock_file = None

    @patch("vocalinux.single_instance.LOCK_FILE_DIR")
    @patch("os.open")
    def test_get_lock_file_fd_creates_directory(self, mock_os_open, mock_lock_dir):
        """Test that directory is created if it doesn't exist."""
        mock_lock_dir_instance = MagicMock(spec=Path)
        mock_lock_dir_instance.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))
        mock_lock_dir = mock_lock_dir_instance

        with patch("vocalinux.single_instance.LOCK_FILE_DIR", mock_lock_dir_instance):
            mock_os_open.return_value = 5

            fd = single_instance_module._get_lock_file_fd()

            self.assertEqual(fd, 5)
            mock_os_open.assert_called_once()

    @patch("vocalinux.single_instance.LOCK_FILE_DIR")
    @patch("os.open")
    def test_get_lock_file_fd_reuses_existing_fd(self, mock_os_open, mock_lock_dir):
        """Test that existing file descriptor is reused."""
        single_instance_module._lock_file = 5

        fd = single_instance_module._get_lock_file_fd()

        self.assertEqual(fd, 5)
        # os.open should not be called if fd already exists
        mock_os_open.assert_not_called()


class TestLockFileConstants(unittest.TestCase):
    """Tests for lock file constants."""

    def test_lock_file_path_is_in_data_home(self):
        """Test that lock file lives under $XDG_DATA_HOME/vocalinux/."""
        expected_dir = Path(data_dir())
        self.assertEqual(single_instance_module.LOCK_FILE_DIR, expected_dir)
        self.assertEqual(single_instance_module.LOCK_FILE_PATH, expected_dir / "instance.lock")

    def test_lock_file_path_is_path_object(self):
        """Test that lock file path is a Path object."""
        self.assertIsInstance(single_instance_module.LOCK_FILE_PATH, Path)

    def test_lock_file_dir_is_path_object(self):
        """Test that lock file dir is a Path object."""
        self.assertIsInstance(single_instance_module.LOCK_FILE_DIR, Path)


if __name__ == "__main__":
    unittest.main()

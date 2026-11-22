"""Tests for PostProcessor and apply_post_processing."""

import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

from vocalinux.post_processor import (
    PostProcessor,
    abort_active_post_processors,
    apply_post_processing,
)
from vocalinux.utils.host_process import host_env


def _make_popen_mock(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    communicate_side_effect: Optional[object] = None,
) -> MagicMock:
    """Build a mock Popen object matching PostProcessor.process expectations."""
    proc = MagicMock()
    proc.pid = -1  # Prevent _signal_process_group from calling os.killpg on mocks
    proc.returncode = returncode
    if communicate_side_effect is not None:
        proc.communicate.side_effect = communicate_side_effect
    else:
        proc.communicate.return_value = (stdout, stderr)
    return proc


class TestPostProcessor(unittest.TestCase):
    def setUp(self) -> None:
        self.patch_popen = patch("vocalinux.post_processor.subprocess.Popen")
        self.mock_popen = self.patch_popen.start()

    def tearDown(self) -> None:
        self.patch_popen.stop()

    def test_convenience_newline_stripped_when_input_had_none(self) -> None:
        self.mock_popen.return_value = _make_popen_mock(stdout="hello\n")
        result = PostProcessor("/script.sh").process("hello")
        self.assertEqual(result, "hello")

    def test_internal_newlines_preserved(self) -> None:
        self.mock_popen.return_value = _make_popen_mock(stdout="a\nb\n")
        result = PostProcessor("/script.sh").process("a\nb")
        self.assertEqual(result, "a\nb")

    def test_paragraph_break_preserved_verbatim(self) -> None:
        """A passthrough script must not eat the "\n\n" from "new paragraph"."""
        self.mock_popen.return_value = _make_popen_mock(stdout="end of paragraph.\n\n")
        result = PostProcessor("/script.sh").process("end of paragraph.\n\n")
        self.assertEqual(result, "end of paragraph.\n\n")

    def test_script_added_paragraph_survives_convenience_strip(self) -> None:
        """Only one trailing newline is treated as a line terminator."""
        self.mock_popen.return_value = _make_popen_mock(stdout="a\n\n")
        result = PostProcessor("/script.sh").process("a")
        self.assertEqual(result, "a\n")

    def test_empty_stdout_returns_empty_string(self) -> None:
        self.mock_popen.return_value = _make_popen_mock(stdout="")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "")

    def test_nonzero_exit_returns_original(self) -> None:
        self.mock_popen.return_value = _make_popen_mock(returncode=1, stderr="oops")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")

    def test_timeout_kills_process_and_returns_original(self) -> None:
        proc = _make_popen_mock(
            communicate_side_effect=[
                subprocess.TimeoutExpired(cmd="/script.sh", timeout=10),
                ("", ""),
            ]
        )
        self.mock_popen.return_value = proc
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")
        proc.kill.assert_called_once()

    def test_os_error_returns_original(self) -> None:
        self.mock_popen.side_effect = OSError("not found")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")

    def test_subprocess_called_with_correct_args(self) -> None:
        proc = _make_popen_mock(stdout="out")
        self.mock_popen.return_value = proc
        PostProcessor("/my/script.sh").process("input text")
        self.mock_popen.assert_called_once_with(
            ["/my/script.sh"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=host_env(),
        )
        proc.communicate.assert_called_once_with(input="input text", timeout=10.0)

    def test_custom_timeout_forwarded_to_subprocess(self) -> None:
        """A valid custom timeout is passed verbatim to proc.communicate."""
        proc = _make_popen_mock(stdout="out")
        self.mock_popen.return_value = proc
        PostProcessor("/my/script.sh", timeout=120.5).process("input text")
        proc.communicate.assert_called_once_with(input="input text", timeout=120.5)

    def test_cancel_event_before_spawn_skips_subprocess(self) -> None:
        """A pre-set cancel_event returns original text without spawning."""
        cancel = threading.Event()
        cancel.set()
        result = PostProcessor("/my/script.sh", timeout=600).process(
            "original", cancel_event=cancel
        )
        self.assertEqual(result, "original")
        self.mock_popen.assert_not_called()

    def test_invalid_timeouts_fall_back_to_default(self) -> None:
        """Non-positive, boolean, non-numeric, and non-finite timeouts fall back to 10.0 s."""
        bad_values: list[object] = [
            True,
            False,
            0,
            -5,
            None,
            "60",
            float("nan"),
            float("inf"),
            float("-inf"),
        ]
        for bad in bad_values:
            with self.subTest(timeout=bad):
                processor = PostProcessor("/my/script.sh", timeout=bad)  # type: ignore[arg-type]
                self.assertEqual(processor.timeout, 10.0)

    def test_out_of_range_positive_timeouts_clamped(self) -> None:
        """Positive timeouts outside [1.0, 600.0] are clamped to supported bounds."""
        self.assertEqual(PostProcessor("/s.sh", timeout=0.25).timeout, 1.0)
        self.assertEqual(PostProcessor("/s.sh", timeout=9999).timeout, 600.0)


class TestPostProcessorAbortOnQuit(unittest.TestCase):
    """Real-subprocess test ensuring quit aborts a long-timeout script promptly."""

    def test_abort_active_post_processors_stops_long_running_script_immediately(self) -> None:
        """A 600 s post-processing script terminates promptly when quit aborts it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = os.path.join(tmpdir, "started")
            script = os.path.join(tmpdir, "slow.sh")
            with open(script, "w") as handle:
                handle.write(f"#!/bin/sh\ntouch '{marker}'\nsleep 60\n")
            os.chmod(script, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            cancel = threading.Event()
            results: list[str] = []

            def _run() -> None:
                results.append(
                    PostProcessor(script, timeout=600).process("hello", cancel_event=cancel)
                )

            worker = threading.Thread(target=_run)
            worker.start()
            deadline = time.monotonic() + 5.0
            while not os.path.exists(marker) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(marker), "slow post-processor script did not start")

            t0 = time.monotonic()
            cancel.set()
            abort_active_post_processors()
            worker.join(timeout=3.0)
            elapsed = time.monotonic() - t0

            self.assertFalse(worker.is_alive(), "worker stayed blocked after abort")
            self.assertLess(elapsed, 3.0)
            self.assertEqual(results, ["hello"])

    def test_abort_active_post_processors_kills_surviving_child_helpers(self) -> None:
        """If the parent shell exits on SIGTERM while a helper ignores SIGTERM, SIGKILL stops it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = os.path.join(tmpdir, "started")
            script = os.path.join(tmpdir, "parent_with_stubborn_child.sh")
            with open(script, "w") as handle:
                handle.write(
                    "#!/bin/sh\n"
                    "trap 'exit 0' TERM\n"
                    "(trap '' TERM; sleep 60) &\n"
                    f"touch '{marker}'\n"
                    "wait\n"
                )
            os.chmod(script, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            cancel = threading.Event()
            results: list[str] = []

            def _run() -> None:
                results.append(
                    PostProcessor(script, timeout=600).process("hello", cancel_event=cancel)
                )

            worker = threading.Thread(target=_run)
            worker.start()
            deadline = time.monotonic() + 5.0
            while not os.path.exists(marker) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(os.path.exists(marker), "stubborn helper script did not start")

            t0 = time.monotonic()
            cancel.set()
            abort_active_post_processors(grace_seconds=0.1)
            worker.join(timeout=3.0)
            elapsed = time.monotonic() - t0

            self.assertFalse(worker.is_alive(), "worker stayed blocked on surviving child helper")
            self.assertLess(elapsed, 3.0)
            self.assertEqual(results, ["hello"])


class TestApplyPostProcessing(unittest.TestCase):
    def setUp(self) -> None:
        self.patch_processor = patch("vocalinux.post_processor.PostProcessor")
        self.mock_processor_cls = self.patch_processor.start()
        self.mock_processor = MagicMock()
        self.mock_processor_cls.return_value = self.mock_processor

    def tearDown(self) -> None:
        self.patch_processor.stop()

    def _config(self, script_path: str, timeout_seconds: object = 10) -> MagicMock:
        config_manager = MagicMock()
        config_manager.get_str.return_value = script_path
        config_manager.get.return_value = timeout_seconds
        return config_manager

    def test_no_script_returns_original_text(self) -> None:
        config_manager = self._config("")
        result = apply_post_processing("hello", config_manager)
        self.assertEqual(result, "hello")
        self.mock_processor_cls.assert_not_called()

    def test_script_configured_returns_processed_text(self) -> None:
        self.mock_processor.process.return_value = "modified"
        result = apply_post_processing("hello", self._config("/s.sh"))
        self.assertEqual(result, "modified")
        self.mock_processor_cls.assert_called_once_with("/s.sh", timeout=10.0)

    def test_script_returns_empty_string_gives_none(self) -> None:
        self.mock_processor.process.return_value = ""
        result = apply_post_processing("hello", self._config("/s.sh"))
        self.assertIsNone(result)

    def test_configured_timeout_propagated_and_reloaded_dynamically(self) -> None:
        """apply_post_processing reads post_processing.timeout_seconds on each call."""
        self.mock_processor.process.return_value = "ok"
        cfg = self._config("/s.sh", timeout_seconds=180)
        apply_post_processing("first", cfg)
        self.mock_processor_cls.assert_called_with("/s.sh", timeout=180.0)

        cfg.get.return_value = 45.5
        apply_post_processing("second", cfg)
        self.mock_processor_cls.assert_called_with("/s.sh", timeout=45.5)

    def test_invalid_config_timeout_uses_default(self) -> None:
        """Invalid configured timeout values safely fall back to 10.0 s."""
        self.mock_processor.process.return_value = "ok"
        apply_post_processing("hello", self._config("/s.sh", timeout_seconds=True))
        self.mock_processor_cls.assert_called_with("/s.sh", timeout=10.0)

    def test_cancel_event_forwarded_to_processor(self) -> None:
        """apply_post_processing forwards cancel_event to PostProcessor.process."""
        self.mock_processor.process.return_value = "ok"
        cancel = threading.Event()
        apply_post_processing("hello", self._config("/s.sh"), cancel_event=cancel)
        self.mock_processor.process.assert_called_once_with("hello", cancel_event=cancel)

"""Tests for PostProcessor and apply_post_processing."""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from vocalinux.post_processor import PostProcessor, apply_post_processing
from vocalinux.utils.host_process import host_env


def _make_run_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestPostProcessor(unittest.TestCase):
    def setUp(self) -> None:
        self.patch_run = patch("vocalinux.post_processor.subprocess.run")
        self.mock_run = self.patch_run.start()

    def tearDown(self) -> None:
        self.patch_run.stop()

    def test_convenience_newline_stripped_when_input_had_none(self) -> None:
        self.mock_run.return_value = _make_run_result(stdout="hello\n")
        result = PostProcessor("/script.sh").process("hello")
        self.assertEqual(result, "hello")

    def test_internal_newlines_preserved(self) -> None:
        self.mock_run.return_value = _make_run_result(stdout="a\nb\n")
        result = PostProcessor("/script.sh").process("a\nb")
        self.assertEqual(result, "a\nb")

    def test_paragraph_break_preserved_verbatim(self) -> None:
        """A passthrough script must not eat the "\n\n" from "new paragraph"."""
        self.mock_run.return_value = _make_run_result(stdout="end of paragraph.\n\n")
        result = PostProcessor("/script.sh").process("end of paragraph.\n\n")
        self.assertEqual(result, "end of paragraph.\n\n")

    def test_script_added_paragraph_survives_convenience_strip(self) -> None:
        """Only one trailing newline is treated as a line terminator."""
        self.mock_run.return_value = _make_run_result(stdout="a\n\n")
        result = PostProcessor("/script.sh").process("a")
        self.assertEqual(result, "a\n")

    def test_empty_stdout_returns_empty_string(self) -> None:
        self.mock_run.return_value = _make_run_result(stdout="")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "")

    def test_nonzero_exit_returns_original(self) -> None:
        self.mock_run.return_value = _make_run_result(returncode=1, stderr="oops")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")

    def test_timeout_returns_original(self) -> None:
        self.mock_run.side_effect = subprocess.TimeoutExpired(cmd="/script.sh", timeout=10)
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")

    def test_os_error_returns_original(self) -> None:
        self.mock_run.side_effect = OSError("not found")
        result = PostProcessor("/script.sh").process("original")
        self.assertEqual(result, "original")

    def test_subprocess_called_with_correct_args(self) -> None:
        self.mock_run.return_value = _make_run_result(stdout="out")
        PostProcessor("/my/script.sh").process("input text")
        self.mock_run.assert_called_once_with(
            ["/my/script.sh"],
            input="input text",
            capture_output=True,
            text=True,
            timeout=10,
            env=host_env(),
        )

    def test_custom_timeout_forwarded_to_subprocess(self) -> None:
        """A valid custom timeout is passed verbatim to subprocess.run."""
        self.mock_run.return_value = _make_run_result(stdout="out")
        PostProcessor("/my/script.sh", timeout=120.5).process("input text")
        self.mock_run.assert_called_once_with(
            ["/my/script.sh"],
            input="input text",
            capture_output=True,
            text=True,
            timeout=120.5,
            env=host_env(),
        )

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

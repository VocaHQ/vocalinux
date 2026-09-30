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


class TestApplyPostProcessing(unittest.TestCase):
    def setUp(self) -> None:
        self.patch_processor = patch("vocalinux.post_processor.PostProcessor")
        self.mock_processor_cls = self.patch_processor.start()
        self.mock_processor = MagicMock()
        self.mock_processor_cls.return_value = self.mock_processor

    def tearDown(self) -> None:
        self.patch_processor.stop()

    def _config(self, script_path: str) -> MagicMock:
        config_manager = MagicMock()
        config_manager.get_str.return_value = script_path
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

    def test_script_returns_empty_string_gives_none(self) -> None:
        self.mock_processor.process.return_value = ""
        result = apply_post_processing("hello", self._config("/s.sh"))
        self.assertIsNone(result)

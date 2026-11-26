"""The Vulkan warm-up must run at load time and never break loading."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from vocalinux.speech_recognition import recognition_manager as rm
from vocalinux.utils.whispercpp_model_info import ComputeBackend


def _bare_manager() -> rm.SpeechRecognitionManager:
    manager = rm.SpeechRecognitionManager.__new__(rm.SpeechRecognitionManager)
    manager.model = MagicMock()
    manager.whispercpp_no_context = True
    return manager


def test_warm_up_transcribes_once() -> None:
    manager = _bare_manager()
    manager._warm_up_whispercpp()
    manager.model.transcribe.assert_called_once()


def test_warm_up_failure_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    manager = _bare_manager()
    manager.model.transcribe.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING):
        manager._warm_up_whispercpp()
    assert "whisper.cpp warm-up failed" in caplog.text


def test_warm_up_skipped_when_model_context_is_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """no_context=False must not seed the first dictation with warm-up audio."""
    manager = _bare_manager()
    manager.whispercpp_no_context = False
    with caplog.at_level(logging.INFO):
        manager._warm_up_for_backend(ComputeBackend.VULKAN)
    manager.model.transcribe.assert_not_called()
    assert "Skipping whisper.cpp warm-up" in caplog.text


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("vulkan", 1), ("cuda", 0), ("cpu", 0)],
)
def test_only_vulkan_warms_up(backend: str, expected: int) -> None:
    manager = _bare_manager()
    with patch.object(manager, "_warm_up_whispercpp") as warm_up:
        manager._warm_up_for_backend(getattr(ComputeBackend, backend.upper()))
    assert warm_up.call_count == expected

"""
Coverage boost tests targeting major gaps in recognition_manager and ibus_engine.

Key focus areas:
- Model download methods with progress tracking
- Audio reconnection logic
- IBus engine utility functions
"""

import os
import sys
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# test_recognition_manager.py replaces sys.modules["zipfile"] with a MagicMock at
# import time. Drop it so the archives built below are real archives — otherwise
# this file's VOSK tests silently exercise nothing when run after that module.
if isinstance(sys.modules.get("zipfile"), MagicMock):
    del sys.modules["zipfile"]

import zipfile as REAL_ZIPFILE  # noqa: E402

import requests as REAL_REQUESTS  # noqa: E402

from vocalinux.utils.model_integrity import ModelIntegrityError  # noqa: E402

# Mock GI imports before importing any vocalinux modules that use gi.
# On CI, real gi/IBus packages are installed; without mocks, importing
# ibus_engine would connect to a real IBus daemon and hang.
if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()

from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager


def _make_manager(engine="whisper_cpp", **kw):
    """Create a SpeechRecognitionManager with mocked initialization."""
    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                mgr = SpeechRecognitionManager(
                    engine=engine, model_size="small", language="en-us", defer_download=True, **kw
                )
                # Ensure vosk_model_map is set (normally done in _init_vosk)
                if not hasattr(mgr, "vosk_model_map"):
                    mgr.vosk_model_map = {
                        "small": "model-en-us-0.22-lgraph",
                        "medium": "vosk-model-en-us-0.22",
                        "large": "vosk-model-en-us-0.22-lgraph",
                    }
                return mgr


@pytest.fixture
def skip_integrity_check():
    """Bypass digest verification and UI paint pauses for plumbing tests.

    Integrity verification itself is covered by tests/test_model_integrity.py and
    the tampered-download tests below. Interruptible pauses are for GTK paint
    timing and would exhaust mocked time.time side effects.
    """
    with (
        patch("vocalinux.speech_recognition.recognition_manager.verify_downloaded_model"),
        patch.object(SpeechRecognitionManager, "_interruptible_pause"),
        patch(
            "vocalinux.speech_recognition.recognition_manager.get_pinned_digest",
            return_value={"sha256": "abc", "size": 1},
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def cleanup_sys_modules():
    """Cleanup sys.modules after each test - full snapshot/restore."""
    # Take a complete snapshot of sys.modules before the test
    saved_modules = dict(sys.modules)

    yield

    # Restore sys.modules to exact pre-test state
    added_keys = set(sys.modules.keys()) - set(saved_modules.keys())
    for key in added_keys:
        del sys.modules[key]
    for key, value in saved_modules.items():
        if key not in sys.modules or sys.modules[key] is not value:
            sys.modules[key] = value


class TestDownloadWhispercppModel:
    """Test _download_whispercpp_model() with runtime import mocking."""

    def test_download_whispercpp_success_basic(self, tmp_path, skip_integrity_check):
        """Test successful whisper.cpp model download."""
        manager = _make_manager(engine="whisper_cpp")
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "1000"}
        mock_response.iter_content.return_value = [b"x" * 500, b"y" * 500]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                manager._download_whispercpp_model()

        assert os.path.exists(model_file)
        assert os.path.getsize(model_file) == 1000

    def test_download_whispercpp_progress_callback(self, tmp_path, skip_integrity_check):
        """Test progress callback is invoked during download."""
        manager = _make_manager(engine="whisper_cpp")
        progress_calls = []

        def track_progress(progress, speed, status):
            progress_calls.append((progress, speed, status))

        manager._download_progress_callback = track_progress
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "1000"}
        mock_response.iter_content.return_value = [b"x" * 500, b"y" * 500]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with patch("time.time", side_effect=[0, 0.2, 0.4, 0.6]):
                    manager._download_whispercpp_model()

        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        assert call_args is not None
        assert len(call_args[0]) > 0 or "url" in call_args[1]
        assert len(progress_calls) >= 1

    def test_download_whispercpp_no_content_length(self, tmp_path, skip_integrity_check):
        """Test download when content-length header is missing."""
        manager = _make_manager(engine="whisper_cpp")
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {}  # No content-length
        mock_response.iter_content.return_value = [b"x" * 500, b"y" * 500]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                manager._download_whispercpp_model()

        assert os.path.exists(model_file)

    def test_download_whispercpp_request_error(self, tmp_path):
        """Test download request error handling."""
        manager = _make_manager(engine="whisper_cpp")
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_error = Exception("Network error")
        mock_requests.get.side_effect = mock_error
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with pytest.raises(RuntimeError, match="Failed to download"):
                    manager._download_whispercpp_model()

    def test_download_whispercpp_appends_download_true(self, tmp_path, skip_integrity_check):
        """Hugging Face URLs get ?download=true for reliable binary responses."""
        manager = _make_manager(engine="whisper_cpp")
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "4", "content-type": "application/octet-stream"}
        mock_response.iter_content.return_value = [b"data"]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                manager._download_whispercpp_model()

        called_url = mock_requests.get.call_args[0][0]
        assert "huggingface.co" in called_url
        assert "download=true" in called_url
        assert mock_requests.get.call_args[1].get("timeout") == manager._MODEL_DOWNLOAD_TIMEOUT

    def test_download_whispercpp_timeout_message(self, tmp_path):
        """Timeout-like errors surface a dedicated user-facing message."""
        manager = _make_manager(engine="whisper_cpp")
        model_file = str(tmp_path / "ggml-small.bin")

        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Read timeout")
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with pytest.raises(RuntimeError, match="timed out"):
                    manager._download_whispercpp_model()

    def test_stream_model_download_rejects_html(self, tmp_path):
        """HTML error pages must not be written as model binaries."""
        manager = _make_manager(engine="whisper_cpp")
        dest = str(tmp_path / "bad.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_response.status_code = 200
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with pytest.raises(RuntimeError, match="HTML"):
                manager._stream_model_download(
                    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/model.bin", dest
                )

        assert not os.path.exists(dest)

    def test_stream_model_download_empty_body(self, tmp_path):
        """Zero-byte downloads are treated as failure and cleaned up."""
        manager = _make_manager(engine="whisper_cpp")
        dest = str(tmp_path / "empty.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": "0", "content-type": "application/octet-stream"}
        mock_response.iter_content.return_value = [b"", b""]
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with pytest.raises(RuntimeError, match="0 bytes"):
                manager._stream_model_download(
                    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/model.bin", dest
                )

        assert not os.path.exists(dest)

    def test_stream_model_download_cancelled(self, tmp_path):
        """User cancel mid-stream removes the partial file."""
        manager = _make_manager(engine="whisper_cpp")
        manager._download_cancelled = True
        dest = str(tmp_path / "partial.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {
            "content-length": "100",
            "content-type": "application/octet-stream",
        }
        mock_response.iter_content.return_value = [b"chunk"]
        mock_requests.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with pytest.raises(RuntimeError, match="cancelled"):
                manager._stream_model_download(
                    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/model.bin", dest
                )

        assert not os.path.exists(dest)

    def test_stream_model_download_eta_minutes_and_empty_chunks(self, tmp_path):
        """Progress path covers multi-minute ETA and skips empty chunks."""
        manager = _make_manager(engine="whisper_cpp")
        progress_calls = []
        manager._download_progress_callback = lambda progress, speed, status: progress_calls.append(
            status
        )
        dest = str(tmp_path / "big.bin")

        mock_requests = MagicMock()
        mock_response = MagicMock()
        # Large total so remaining/speed yields ETA >= 60s
        mock_response.headers = {
            "content-length": str(100 * 1024 * 1024),
            "content-type": "application/octet-stream",
        }
        mock_response.iter_content.return_value = [b"", b"x" * 1024]
        mock_requests.get.return_value = mock_response

        # start=0, then 0.2 for progress update (elapsed > 0, small speed)
        times = [0.0, 0.2, 0.2]
        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch("time.time", side_effect=lambda: times.pop(0) if times else 1.0):
                manager._stream_model_download(
                    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/model.bin", dest
                )

        assert os.path.exists(dest)
        assert os.path.getsize(dest) == 1024
        assert any("m " in s or "ETA" in s for s in progress_calls)


class TestDownloadVoskModel:
    """Test _download_vosk_model() with runtime import mocking."""

    def test_download_vosk_progress_callback(self, tmp_path, skip_integrity_check):
        """Test progress callback during Vosk download."""
        manager = _make_manager(engine="vosk")
        progress_calls = []

        def track_progress(progress, speed, status):
            progress_calls.append((progress, speed, status))

        manager._download_progress_callback = track_progress

        zip_data = BytesIO()
        with REAL_ZIPFILE.ZipFile(zip_data, "w") as zf:
            zf.writestr("model-en-us-0.22-lgraph/am/model.pkl", "x" * 5000)
        zip_bytes = zip_data.getvalue()

        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(zip_bytes))}
        mock_response.iter_content.return_value = [zip_bytes]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.MODELS_DIR", str(tmp_path)
            ):
                # Extraction is covered by tests/test_model_integrity.py; this test
                # only cares about the download progress callbacks.
                with patch("vocalinux.speech_recognition.recognition_manager.safe_extract_zip"):
                    with patch("time.time", side_effect=[0, 0.2, 0.4, 0.6]):
                        manager._download_vosk_model()

        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        assert call_args is not None
        assert len(call_args[0]) > 0 or "url" in call_args[1]
        assert len(progress_calls) >= 1

    def test_download_vosk_request_error(self, tmp_path):
        """Test Vosk download request error handling."""
        manager = _make_manager(engine="vosk")

        mock_requests = MagicMock()
        mock_error = Exception("Network error")
        mock_requests.get.side_effect = mock_error
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.MODELS_DIR", str(tmp_path)
            ):
                with pytest.raises(RuntimeError, match="Failed to download"):
                    manager._download_vosk_model()


class TestSecuredDownloadStatusReporting:
    """The downloader must narrate pin lookup and verification for the UI."""

    def test_announce_reports_pinned_digest(self):
        manager = _make_manager(engine="whisper_cpp")
        statuses = []
        manager.set_download_progress_callback(
            lambda fraction, speed, status: statuses.append(status)
        )

        with patch("time.sleep"):  # don't slow the suite for UI paint pauses
            manager._announce_secured_download("whispercpp", "ggml-tiny.bin")

        assert any("Looking up pinned SHA256" in s for s in statuses)
        assert any("Pinned digest found" in s for s in statuses)

    def test_verify_reports_match_before_returning(self, tmp_path):
        manager = _make_manager(engine="whisper_cpp")
        statuses = []
        manager.set_download_progress_callback(
            lambda fraction, speed, status: statuses.append(status)
        )
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"weights")

        with (
            patch("time.sleep"),
            patch(
                "vocalinux.speech_recognition.recognition_manager.verify_downloaded_model"
            ) as verify,
        ):
            manager._verify_download_with_status(str(model), "whispercpp", "ggml-tiny.bin")

        verify.assert_called_once()
        assert any("Verifying SHA256" in s for s in statuses)
        assert any("Hash matches" in s for s in statuses)

    def test_verify_does_not_claim_match_when_unpinned(self, tmp_path):
        manager = _make_manager(engine="whisper_cpp")
        statuses = []
        manager.set_download_progress_callback(
            lambda fraction, speed, status: statuses.append(status)
        )
        model = tmp_path / "ggml-unlisted.bin"
        model.write_bytes(b"weights")

        with (
            patch("time.sleep"),
            patch("vocalinux.speech_recognition.recognition_manager.verify_downloaded_model"),
            patch(
                "vocalinux.speech_recognition.recognition_manager.get_pinned_digest",
                return_value=None,
            ),
        ):
            manager._verify_download_with_status(str(model), "whispercpp", "ggml-unlisted.bin")

        assert any("skipping hash check" in s for s in statuses)
        assert not any("Hash matches" in s for s in statuses)

    def test_interruptible_pause_honours_cancel(self):
        manager = _make_manager(engine="whisper_cpp")
        manager._download_cancelled = True
        with pytest.raises(RuntimeError, match="cancelled"):
            manager._interruptible_pause(1.0)

    def test_verify_honours_cancel_before_hashing(self, tmp_path):
        manager = _make_manager(engine="whisper_cpp")
        manager._download_cancelled = True
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"weights")
        with pytest.raises(RuntimeError, match="cancelled"):
            manager._verify_download_with_status(str(model), "whispercpp", "ggml-tiny.bin")

    def test_verify_honours_cancel_during_hash(self, tmp_path):
        manager = _make_manager(engine="whisper_cpp")
        model = tmp_path / "ggml-tiny.bin"
        model.write_bytes(b"weights")

        def cancel_mid_hash(*_args, **_kwargs):
            manager._download_cancelled = True
            raise RuntimeError("Download cancelled")

        with (
            patch("time.sleep"),
            patch(
                "vocalinux.speech_recognition.recognition_manager.verify_downloaded_model",
                side_effect=cancel_mid_hash,
            ),
        ):
            with pytest.raises(RuntimeError, match="cancelled"):
                manager._verify_download_with_status(str(model), "whispercpp", "ggml-tiny.bin")


class TestDownloadIntegrityEnforcement:
    """The download paths must refuse artifacts that fail an integrity check."""

    def _mock_requests(self, chunks):
        mock_requests = MagicMock()
        mock_response = MagicMock()
        payload = b"".join(chunks)
        mock_response.headers = {
            "content-length": str(len(payload)),
            "content-type": "application/octet-stream",
        }
        mock_response.url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/x.bin"
        mock_response.iter_content.return_value = list(chunks)
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = REAL_REQUESTS.exceptions.RequestException
        return mock_requests

    def test_whispercpp_download_rejects_tampered_bytes(self, tmp_path):
        """A body that does not match the pinned digest never becomes the model."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model_size = "tiny"
        model_file = str(tmp_path / "ggml-tiny.bin")

        with patch.dict("sys.modules", {"requests": self._mock_requests([b"not the real model"])}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with pytest.raises(ModelIntegrityError):
                    manager._download_whispercpp_model()

        assert not os.path.exists(model_file)
        assert not os.path.exists(model_file + ".tmp"), "the partial download must be removed"

    def test_whisper_download_rejects_tampered_bytes(self, tmp_path):
        manager = _make_manager(engine="whisper")
        manager.model_size = "tiny"

        with patch.dict("sys.modules", {"requests": self._mock_requests([b"not a checkpoint"])}):
            with pytest.raises(ModelIntegrityError):
                manager._download_whisper_model(cache_dir=str(tmp_path))

        assert not os.path.exists(tmp_path / "tiny.pt")
        assert not os.path.exists(tmp_path / "tiny.pt.tmp")

    def test_whispercpp_download_refuses_plain_http_redirect(self, tmp_path):
        """A redirect that downgrades to HTTP aborts before anything is kept."""
        manager = _make_manager(engine="whisper_cpp")
        mock_requests = self._mock_requests([b"payload"])
        mock_requests.get.return_value.url = "http://cdn.example/ggml-tiny.bin"
        model_file = str(tmp_path / "ggml-tiny.bin")

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with pytest.raises(ModelIntegrityError, match="insecure URL"):
                    manager._download_whispercpp_model()

        assert not os.path.exists(model_file)

    def test_vosk_download_refuses_archive_that_escapes_models_dir(self, tmp_path):
        """A hostile VOSK archive must not write outside the models directory."""
        manager = _make_manager(engine="vosk")
        models_dir = tmp_path / "models"
        models_dir.mkdir()

        zip_data = BytesIO()
        with REAL_ZIPFILE.ZipFile(zip_data, "w") as zf:
            zf.writestr("../pwned.txt", "escaped")
        zip_bytes = zip_data.getvalue()

        with patch.dict("sys.modules", {"requests": self._mock_requests([zip_bytes])}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.MODELS_DIR", str(models_dir)
            ):
                with patch(
                    "vocalinux.speech_recognition.recognition_manager.verify_downloaded_model"
                ):
                    with pytest.raises(ModelIntegrityError, match="escapes"):
                        manager._download_vosk_model()

        assert not (tmp_path / "pwned.txt").exists()
        assert list(models_dir.iterdir()) == [], "the archive must be cleaned up"

    def test_whispercpp_cancel_after_verify_does_not_install(self, tmp_path):
        """Cancel during SHA256 verify must not rename the temp file into place."""
        manager = _make_manager(engine="whisper_cpp")
        manager.model_size = "tiny"
        model_file = str(tmp_path / "ggml-tiny.bin")

        def verify_then_cancel(*_args, **_kwargs):
            manager._download_cancelled = True

        with patch.dict("sys.modules", {"requests": self._mock_requests([b"payload"])}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.get_model_path",
                return_value=model_file,
            ):
                with patch(
                    "vocalinux.speech_recognition.recognition_manager.verify_downloaded_model",
                    side_effect=verify_then_cancel,
                ):
                    with pytest.raises(RuntimeError, match="cancelled"):
                        manager._download_whispercpp_model()

        assert not os.path.exists(model_file)
        assert not os.path.exists(model_file + ".tmp")


class TestAudioReconnection:
    """Test audio reconnection logic."""

    def test_attempt_audio_reconnection_success(self):
        """Test successful audio reconnection."""
        manager = _make_manager(engine="whisper_cpp")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00" * 1024
        mock_audio_instance = MagicMock()
        mock_audio_instance.open.return_value = mock_stream

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}):
            with patch("time.sleep"):
                result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is True
        assert manager._audio_stream == mock_stream

    def test_attempt_audio_reconnection_falls_back_to_default_resolver(self):
        """Test reconnection falls back when saved device name/index cannot resolve."""
        manager = _make_manager(engine="whisper_cpp", audio_device_name="Missing Mic")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00" * 1024
        mock_audio_instance = MagicMock()
        mock_audio_instance.get_default_input_device_info.return_value = {"index": 0}
        mock_audio_instance.open.return_value = mock_stream

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}),
            patch("time.sleep"),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_device_by_name",
                return_value=None,
            ) as mock_resolve_name,
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_valid_input_device",
                return_value=1,
            ) as mock_resolve_default,
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_channels",
                return_value=1,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_sample_rate",
                return_value=16000,
            ),
        ):
            result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is True
        assert manager._audio_stream == mock_stream
        mock_resolve_name.assert_called_once_with(mock_audio_instance, "Missing Mic", None)
        mock_resolve_default.assert_called_once_with(mock_audio_instance, None)

    def test_attempt_audio_reconnection_no_resolved_device(self):
        """When no safe device is enumerated, reconnect via system default."""
        manager = _make_manager(engine="whisper_cpp", audio_device_name="Missing Mic")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_audio_instance = MagicMock()
        mock_stream = MagicMock()

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}),
            patch("time.sleep"),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_device_by_name",
                return_value=None,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._resolve_valid_input_device",
                return_value=None,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, mock_stream),
            ) as mock_open,
        ):
            result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is True
        mock_open.assert_called_once_with(mock_audio_instance, None)

    def test_attempt_audio_reconnection_max_attempts(self):
        """Test reconnection stops after max attempts."""
        manager = _make_manager(engine="whisper_cpp")
        manager._reconnection_attempts = manager._max_reconnection_attempts

        mock_audio_instance = MagicMock()

        with patch.dict("sys.modules", {"pyaudio": MagicMock()}):
            result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is False

    def test_attempt_audio_reconnection_open_failure(self):
        """Test reconnection when stream open fails."""
        manager = _make_manager(engine="whisper_cpp")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_audio_instance = MagicMock()
        mock_audio_instance.open.side_effect = IOError("Cannot open stream")

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}):
            with patch("time.sleep"):
                result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is False

    def test_attempt_audio_reconnection_exponential_backoff(self):
        """Test exponential backoff in reconnection attempts."""
        manager = _make_manager(engine="whisper_cpp")
        manager._reconnection_delay = 0.1

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00" * 1024
        mock_audio_instance = MagicMock()
        mock_audio_instance.open.return_value = mock_stream

        sleep_durations = []

        def track_sleep(duration):
            sleep_durations.append(duration)

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}):
            with patch("time.sleep", side_effect=track_sleep):
                manager._reconnection_attempts = 0
                manager._attempt_audio_reconnection(mock_audio_instance)
                first_delay = sleep_durations[-1]

                manager._reconnection_attempts = 1
                manager._attempt_audio_reconnection(mock_audio_instance)
                second_delay = sleep_durations[-1]

        assert second_delay > first_delay
        assert second_delay == first_delay * 2

    def test_attempt_audio_reconnection_negotiation_fallback(self):
        """When negotiation returns no stream, reconnect falls back to plain open."""
        manager = _make_manager(engine="whisper_cpp")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_stream = MagicMock()
        mock_stream.read.return_value = b"\x00" * 1024
        mock_audio_instance = MagicMock()
        mock_audio_instance.open.return_value = mock_stream

        with (
            patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}),
            patch("time.sleep"),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(1, 16000, None),
            ),
        ):
            result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is True
        assert manager._audio_stream == mock_stream
        mock_audio_instance.open.assert_called_once()

    def test_attempt_audio_reconnection_empty_read_closes_stream(self):
        """A reconnected stream that returns no data must be closed safely."""
        manager = _make_manager(engine="whisper_cpp")

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.paInt16 = 8
        mock_stream = MagicMock()
        mock_stream.read.return_value = b""
        mock_audio_instance = MagicMock()
        mock_audio_instance.open.return_value = mock_stream

        with patch.dict("sys.modules", {"pyaudio": mock_pyaudio_mod}):
            with patch("time.sleep"):
                result = manager._attempt_audio_reconnection(mock_audio_instance)

        assert result is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()


class TestIBusEngineUtilities:
    """Test ibus_engine utility functions."""

    def test_is_ibus_available(self):
        """Test is_ibus_available() function."""
        from vocalinux.text_injection.ibus_engine import is_ibus_available

        result = is_ibus_available()
        assert isinstance(result, bool)

    def test_is_ibus_daemon_running(self):
        """Test daemon detection when not running."""
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            result = is_ibus_daemon_running()
            assert result is False

    def test_is_ibus_daemon_running_success(self):
        """Test daemon detection when running."""
        from vocalinux.text_injection.ibus_engine import is_ibus_daemon_running

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

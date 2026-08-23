"""
Coverage boost tests targeting major gaps in recognition_manager and ibus_engine.

Key focus areas:
- Model download methods with progress tracking
- Audio reconnection logic
- IBus engine utility functions
"""

import base64
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock GI imports before importing any vocalinux modules that use gi.
# On CI, real gi/IBus packages are installed; without mocks, importing
# ibus_engine would connect to a real IBus daemon and hang.
if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()

from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager
from vocalinux.utils.model_checksums import VERIFICATION_STAMP_NAME, expected_for


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
                    # The names _init_vosk() would pick for en-us. They have to be
                    # real: the download path looks each one up in the checksum
                    # manifest to stamp the tree it extracts.
                    mgr.vosk_model_map = {
                        "small": "vosk-model-small-en-us-0.15",
                        "medium": "vosk-model-en-us-0.22",
                        "large": "vosk-model-en-us-0.22",
                    }
                return mgr


# A real zip, embedded rather than built here: by the time this module is
# imported, other test modules have already replaced zipfile/BytesIO in
# sys.modules with mocks, so building one here yields empty bytes. Its single
# entry sits under the directory VOSK's small en-us archive unpacks to, because
# that is the tree the downloader stamps after extracting.
VOSK_ZIP_BYTES = base64.b64decode(
    "UEsDBBQAAAAIAHV2F12oDuXYFgAAAIgTAAAoAAAAdm9zay1tb2RlbC1zbWFsbC1lbi11cy0wLjE1L2FtL2Zp"
    "bmFsLm1kbO3BMQEAAADCoPVPbQo/oAAAAACAtwFQSwECFAMUAAAACAB1dhddqA7l2BYAAACIEwAAKAAAAAAA"
    "AAAAAAAAgAEAAAAAdm9zay1tb2RlbC1zbWFsbC1lbi11cy0wLjE1L2FtL2ZpbmFsLm1kbFBLBQYAAAAAAQAB"
    "AFYAAABcAAAAAAA="
)


class FakeRequestError(Exception):
    """Stands in for requests.exceptions.RequestException.

    A leaked mock makes ``except requests.exceptions.RequestException`` a
    TypeError, so the mocked module needs a real class here. It must not be
    ``Exception`` itself, or that clause swallows every other failure the
    downloader is supposed to surface unwrapped.
    """


def _fake_clock(step=0.2):
    """Monotonic stand-in for time.time().

    A fixed side_effect list runs out unpredictably: time.time is patched
    globally, so logging consumes ticks too.
    """
    from itertools import count

    counter = count()
    return lambda: next(counter) * step


@pytest.fixture
def skip_checksum():
    """Accept the synthetic payloads these tests stream.

    Downloads are verified against the digests pinned in model_checksums.txt, so
    a few hundred bytes of ``b"x"`` are correctly rejected. These tests cover
    download *mechanics* (progress, content-length, URL shaping); integrity
    itself is covered by tests/test_model_checksums.py. Yielding the mock lets
    each test still assert that verification was reached.
    """
    with patch("vocalinux.speech_recognition.recognition_manager.verify_model_file") as mock_verify:
        yield mock_verify


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

    def test_download_whispercpp_success_basic(self, tmp_path, skip_checksum):
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
        # The model is only installed after it is verified.
        skip_checksum.assert_called_once()

    def test_download_whispercpp_progress_callback(self, tmp_path, skip_checksum):
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
                with patch("time.time", side_effect=_fake_clock()):
                    manager._download_whispercpp_model()

        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        assert call_args is not None
        assert len(call_args[0]) > 0 or "url" in call_args[1]
        assert len(progress_calls) >= 1

    def test_download_whispercpp_no_content_length(self, tmp_path, skip_checksum):
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

    def test_download_whispercpp_appends_download_true(self, tmp_path, skip_checksum):
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
                manager._stream_model_download("https://example.com/model.bin", dest)

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
                manager._stream_model_download("https://example.com/model.bin", dest)

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
                manager._stream_model_download("https://example.com/model.bin", dest)

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
                manager._stream_model_download("https://example.com/model.bin", dest)

        assert os.path.exists(dest)
        assert os.path.getsize(dest) == 1024
        assert any("m " in s or "ETA" in s for s in progress_calls)


class TestDownloadWhisperModel:
    """OpenAI Whisper downloads run through the shared streaming helper.

    Vocalinux fetches the checkpoint only to give the UI progress and a working
    cancel; whisper.load_model() is what verifies it. Both were briefly lost when
    the downloader was removed altogether, so they are pinned here.
    """

    @staticmethod
    def _fake_stream(url, dest_path):
        with open(dest_path, "wb") as handle:
            handle.write(b"checkpoint")

    def test_writes_the_name_whisper_expects(self, tmp_path):
        manager = _make_manager(engine="whisper")
        manager.model_size = "large"

        with patch.object(manager, "_stream_model_download", side_effect=self._fake_stream):
            manager._download_whisper_model(str(tmp_path))

        # large is stored as large-v3.pt; "large.pt" here would mean load_model
        # downloads the 2.9GB checkpoint a second time.
        assert (tmp_path / "large-v3.pt").exists()
        assert not (tmp_path / "large.pt").exists()

    def test_reports_progress(self, tmp_path):
        manager = _make_manager(engine="whisper")
        progress_calls = []
        manager._download_progress_callback = lambda f, s, st: progress_calls.append(st)

        with patch.object(manager, "_stream_model_download", side_effect=self._fake_stream):
            manager._download_whisper_model(str(tmp_path))

        assert progress_calls, "the download dialog would sit at zero"

    def test_cancel_propagates_and_cleans_up(self, tmp_path):
        """Cancel raised by the stream helper must reach the caller."""
        manager = _make_manager(engine="whisper")

        def cancel(url, dest_path):
            with open(dest_path, "wb") as handle:
                handle.write(b"partial")
            raise RuntimeError("Download cancelled")

        # A leaked requests mock from another module makes
        # `except requests.exceptions.RequestException` a TypeError, so pin a
        # real exception class here as the other download tests do.
        mock_requests = MagicMock()
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            with patch.object(manager, "_stream_model_download", side_effect=cancel):
                with pytest.raises(RuntimeError, match="cancelled"):
                    manager._download_whisper_model(str(tmp_path))

        assert not list(tmp_path.glob("*"))


class TestDownloadVoskModel:
    """Test _download_vosk_model() with runtime import mocking."""

    @staticmethod
    def _serve_zip(manager, tmp_path):
        """Run a full download+extract of VOSK_ZIP_BYTES into tmp_path."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.headers = {"content-length": str(len(VOSK_ZIP_BYTES))}
        mock_response.iter_content.return_value = [VOSK_ZIP_BYTES]
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = FakeRequestError

        # Extraction has to really happen here — the stamp lands in the tree it
        # creates — and other modules leave a MagicMock in sys.modules["zipfile"].
        real_zipfile = getattr(sys, "_vocalinux_real_zipfile", None) or __import__("zipfile")

        with patch.dict("sys.modules", {"requests": mock_requests, "zipfile": real_zipfile}):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.MODELS_DIR", str(tmp_path)
            ):
                with patch("time.time", side_effect=_fake_clock()):
                    manager._download_vosk_model()
        return mock_requests

    def test_download_vosk_progress_callback(self, tmp_path, skip_checksum):
        """Test progress callback during Vosk download."""
        manager = _make_manager(engine="vosk")
        progress_calls = []

        def track_progress(progress, speed, status):
            progress_calls.append((progress, speed, status))

        manager._download_progress_callback = track_progress

        mock_requests = self._serve_zip(manager, tmp_path)

        mock_requests.get.assert_called_once()
        call_args = mock_requests.get.call_args
        assert call_args is not None
        assert len(call_args[0]) > 0 or "url" in call_args[1]
        assert len(progress_calls) >= 1
        # Otherwise the digest check could be deleted and this stay green.
        skip_checksum.assert_called_once()

    def test_download_vosk_stamps_the_extracted_tree(self, tmp_path, skip_checksum):
        """A directory has no digest; install.sh reads this stamp instead.

        Leave it out and every model fetched at first run or from Settings looks
        unverified to the next ./install.sh, which downloads it again.
        """
        manager = _make_manager(engine="vosk")

        self._serve_zip(manager, tmp_path)

        stamp = tmp_path / "vosk-model-small-en-us-0.15" / VERIFICATION_STAMP_NAME
        pinned = expected_for("vosk-model-small-en-us-0.15.zip")
        assert pinned is not None, "the fixture model must be in the manifest"
        assert stamp.read_text().strip() == pinned.digest

    def test_download_vosk_fails_when_the_stamp_cannot_be_written(self, tmp_path, skip_checksum):
        """An unstampable tree is one we would silently refetch; say so instead."""
        manager = _make_manager(engine="vosk")

        with patch(
            "vocalinux.speech_recognition.recognition_manager.write_verification_stamp",
            side_effect=OSError("read-only models directory"),
        ):
            with pytest.raises(OSError):
                self._serve_zip(manager, tmp_path)

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

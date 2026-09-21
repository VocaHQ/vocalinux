"""
Test coverage for remote API speech recognition engine.

These tests cover the remote API engine added in PR #335.
"""

import sys
import unittest
from unittest.mock import ANY, MagicMock, Mock

import pytest


# autouse fixture: inject mock modules before each test, restore sys.modules after test,
# prevent polluting other test files in the same pytest session.
@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    """Mock heavy dependencies via sys.modules, restoring after each test."""
    for mod in [
        "vosk",
        "whisper",
        "pyaudio",
        "wave",
        "tqdm",
        "numpy",
        "torch",
        "psutil",
    ]:
        monkeypatch.setitem(sys.modules, mod, MagicMock())

    # pywhispercpp requires submodule structure
    mock_pywhispercpp = MagicMock()
    mock_pywhispercpp.model = MagicMock()
    mock_pywhispercpp.model.Model = MagicMock()
    monkeypatch.setitem(sys.modules, "pywhispercpp", mock_pywhispercpp)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", mock_pywhispercpp.model)

    # requests needs to keep real exception classes for except statements to work properly
    mock_requests = MagicMock()
    mock_requests.exceptions.ConnectionError = ConnectionError
    mock_requests.exceptions.RequestException = Exception
    monkeypatch.setitem(sys.modules, "requests", mock_requests)

    yield


def _import_manager():
    """Delayed import of SpeechRecognitionManager to ensure fixture mocks take effect before execution."""
    from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager

    return SpeechRecognitionManager


def _get_mock_requests():
    """Get the mock requests object currently injected into sys.modules."""
    return sys.modules["requests"]


def _get_mock_session():
    """Get the mock session instance returned by requests.Session()."""
    return _get_mock_requests().Session.return_value


def _setup_requests_get_ok(status_code=200):
    """Configure mock session.get to return a successful response."""
    mock_session = _get_mock_session()
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = status_code
    mock_session.get.return_value = mock_response
    return mock_session.get


def _setup_requests_get_error(exception):
    """Configure mock session.get to throw an exception."""
    mock_session = _get_mock_session()
    mock_session.get.side_effect = exception
    return mock_session.get


def _setup_requests_get_non_ok(status_code=500):
    """Configure mock session.get to return a non-successful response."""
    mock_session = _get_mock_session()
    mock_response = Mock()
    mock_response.ok = False
    mock_response.status_code = status_code
    mock_session.get.return_value = mock_response
    return mock_session.get


def _setup_requests_post_ok(json_data, status_code=200):
    """Configure mock session.post to return a successful response."""
    mock_session = _get_mock_session()
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    mock_session.post.return_value = mock_response
    return mock_session.post


def _setup_requests_post_error(exception):
    """Configure mock session.post to throw an exception."""
    mock_session = _get_mock_session()
    mock_session.post.side_effect = exception
    return mock_session.post


def _setup_requests_post_status(status_code, raise_for_status_error=None):
    """Configure mock session.post to return a response with a specific status code."""
    mock_session = _get_mock_session()
    mock_response = Mock()
    mock_response.status_code = status_code
    if raise_for_status_error:
        mock_response.raise_for_status.side_effect = raise_for_status_error
    mock_session.post.return_value = mock_response
    return mock_session.post


class TestRemoteAPIEngine(unittest.TestCase):
    """Test cases for remote API speech recognition engine."""

    def test_remote_api_init_without_url(self):
        """Test remote API initialization without URL."""
        SpeechRecognitionManager = _import_manager()
        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="",
        )
        # Should not raise, just set _model_initialized to False
        self.assertFalse(manager._model_initialized)

    def test_remote_api_init_with_invalid_url(self):
        """Test remote API initialization with invalid URL format."""
        SpeechRecognitionManager = _import_manager()
        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="invalid-url",
        )
        # Should not raise, just set _model_initialized to False
        self.assertFalse(manager._model_initialized)

    def test_remote_api_init_with_valid_url(self):
        """Test remote API initialization with valid HTTP URL."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        # Should set _model_initialized to True
        self.assertTrue(manager._model_initialized)

    def test_remote_api_init_with_valid_https_url(self):
        """Test remote API initialization with HTTPS URL."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="https://192.168.1.100:9090",
        )
        self.assertTrue(manager._model_initialized)

    def test_remote_api_init_strips_trailing_slash(self):
        """Test remote API initialization strips trailing slash from URL."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090/",
        )
        # URL should have trailing slash stripped
        self.assertFalse(manager.remote_api_url.endswith("/"))

    def test_remote_api_init_with_connection_failure(self):
        """Test remote API initialization handles connection failure gracefully."""
        SpeechRecognitionManager = _import_manager()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        # Should still set _model_initialized to True (will retry later)
        self.assertTrue(manager._model_initialized)

    def test_remote_api_init_with_server_error(self):
        """Test remote API initialization handles non-OK server response."""
        SpeechRecognitionManager = _import_manager()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        # Should still set _model_initialized to True (warns but continues)
        self.assertTrue(manager._model_initialized)

    def test_remote_api_init_with_api_key(self):
        """Test remote API initialization includes API key in headers."""
        SpeechRecognitionManager = _import_manager()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_key="test-api-key",
        )
        self.assertTrue(manager._model_initialized)
        self.assertEqual(manager.remote_api_key, "test-api-key")

    def test_remote_api_init_with_inference_endpoint(self):
        """Test remote API initialization with whisper.cpp server endpoint."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_endpoint="/inference",
        )
        self.assertEqual(manager.remote_api_endpoint, "/inference")

    def test_remote_api_init_with_openai_endpoint(self):
        """Test remote API initialization with OpenAI compatible endpoint."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:8080",
            remote_api_endpoint="/v1/audio/transcriptions",
        )
        self.assertEqual(manager.remote_api_endpoint, "/v1/audio/transcriptions")

    def test_remote_api_init_with_model_name(self):
        """Test remote API initialization stores a configurable model name."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:8000",
            remote_api_endpoint="/v1/audio/transcriptions",
            remote_api_model="sensevoice",
        )
        self.assertEqual(manager.remote_api_model, "sensevoice")

    def test_model_ready_remote_api_initialized(self):
        """Test model_ready returns True for remote API when initialized."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        # Should be available after initialization
        self.assertTrue(manager.model_ready)

    def test_model_ready_remote_api_not_initialized(self):
        """Test model_ready returns False when remote API not initialized."""
        SpeechRecognitionManager = _import_manager()
        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="",
        )
        # Should not be available without URL
        self.assertFalse(manager.model_ready)


class TestRemoteAPITranscription(unittest.TestCase):
    """Test cases for remote API transcription functionality."""

    def setUp(self):
        """Set up test fixtures."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        self.manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_key="test-key",
            remote_api_endpoint="/inference",
        )

    def test_transcribe_with_empty_buffer(self):
        """Test transcription with empty audio buffer."""
        result = self.manager._transcribe_with_remote_api([], None)
        self.assertEqual(result, "")

    def test_transcribe_with_no_url(self):
        """Test transcription when URL is not set."""
        self.manager.remote_api_url = ""
        result = self.manager._transcribe_with_remote_api([b"test"], None)
        self.assertEqual(result, "")

    def test_transcribe_with_openai_endpoint_success(self):
        """Test successful transcription via OpenAI endpoint."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_openai_api") as mock_openai:
            mock_openai.return_value = "test transcription"

            # Change endpoint to OpenAI
            self.manager.remote_api_endpoint = "/v1/audio/transcriptions"
            result = self.manager._transcribe_with_remote_api(
                [b"test-audio-data"], self.manager._http_session
            )

            self.assertEqual(result, "test transcription")

    def test_transcribe_with_whisper_cpp_server_endpoint_success(self):
        """Test successful transcription via whisper.cpp server endpoint."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.return_value = "hello world"

            result = self.manager._transcribe_with_remote_api(
                [b"audio-bytes"], self.manager._http_session
            )

            self.assertEqual(result, "hello world")

    def test_transcribe_with_whispercpp_api_failing(self):
        """Test transcription returns empty string when whisper.cpp server API fails."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.return_value = None

            result = self.manager._transcribe_with_remote_api(
                [b"some-audio"], self.manager._http_session
            )

            # Should return empty string when API returns None
            self.assertEqual(result, "")
            mock_server.assert_called_once()

    def test_transcribe_with_openai_api_failing(self):
        """Test transcription returns empty string when OpenAI API fails."""
        from unittest.mock import patch

        self.manager.remote_api_endpoint = "/v1/audio/transcriptions"
        with patch.object(self.manager, "_try_openai_api") as mock_openai:
            mock_openai.return_value = None

            result = self.manager._transcribe_with_remote_api(
                [b"some-audio"], self.manager._http_session
            )

            # Should return empty string when API returns None
            self.assertEqual(result, "")
            mock_openai.assert_called_once()

    def test_transcribe_with_language_en_us_conversion(self):
        """Test language code conversion from en-us to en."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.return_value = "test"

            self.manager.language = "en-us"
            self.manager._transcribe_with_remote_api([b"audio"], self.manager._http_session)

            # Should have been called with "en" (converted from "en-us")
            mock_server.assert_called_once_with(ANY, "en", ANY, ANY)

    def test_transcribe_with_language_en_in_conversion(self):
        """English (India) catalog id must map to Whisper code 'en'."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.return_value = "test"

            self.manager.language = "en-in"
            self.manager._transcribe_with_remote_api([b"audio"], self.manager._http_session)

            mock_server.assert_called_once_with(ANY, "en", ANY, ANY)

    def test_transcribe_with_language_auto(self):
        """Test with auto language detection."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.return_value = "test"

            self.manager.language = "auto"
            self.manager._transcribe_with_remote_api([b"audio"], self.manager._http_session)

            # Should pass None for auto detection
            mock_server.assert_called_once_with(ANY, None, ANY, ANY)

    def test_transcribe_unexpected_exception_returns_empty(self):
        """An unexpected exception inside transcription is caught and returns ''."""
        from unittest.mock import patch

        with patch.object(self.manager, "_try_whispercpp_server_api") as mock_server:
            mock_server.side_effect = RuntimeError("boom")

            result = self.manager._transcribe_with_remote_api(
                [b"audio"], self.manager._http_session
            )

            self.assertEqual(result, "")


class TestOpenAIAPIFormat(unittest.TestCase):
    """Test cases for OpenAI compatible API format."""

    def setUp(self):
        """Set up test fixtures."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        self.manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:8080",
            remote_api_key="my-api-key",
            remote_api_endpoint="/v1/audio/transcriptions",
        )

    def test_try_openai_api_success(self):
        """Test successful transcription via OpenAI API format."""
        _setup_requests_post_ok({"text": "transcribed text"})

        result = self.manager._try_openai_api(
            b"wav-bytes", "en", {"Authorization": "Bearer key"}, self.manager._http_session
        )

        self.assertEqual(result, "transcribed text")

    def test_try_openai_api_with_404(self):
        """Test OpenAI API format returns None for 404."""
        _setup_requests_post_status(404)

        result = self.manager._try_openai_api(b"wav", "en", {}, self.manager._http_session)

        self.assertIsNone(result)

    def test_try_openai_api_connection_error(self):
        """Test OpenAI API handles connection errors gracefully."""
        _setup_requests_post_error(Exception("Connection refused"))

        result = self.manager._try_openai_api(b"wav", "en", {}, self.manager._http_session)

        self.assertIsNone(result)

    def test_try_openai_api_with_language(self):
        """Test OpenAI API includes language in request."""
        mock_post = _setup_requests_post_ok({"text": "result"})

        self.manager._try_openai_api(b"wav-bytes", "fr", {}, self.manager._http_session)

        # Check that language was included in the data
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["data"]["language"], "fr")

    def test_try_openai_api_uses_configured_model(self):
        """Test OpenAI API sends the configured model name."""
        mock_post = _setup_requests_post_ok({"text": "result"})
        self.manager.remote_api_model = "custom-asr-model"

        self.manager._try_openai_api(b"wav-bytes", "en", {}, self.manager._http_session)

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["data"]["model"], "custom-asr-model")

    def test_try_openai_api_accepts_funasr_metadata_response(self):
        """Test OpenAI-compatible FunASR/SenseVoice responses with metadata."""
        _setup_requests_post_ok(
            {
                "text": "hello from sensevoice",
                "language": "en",
                "emotion": "neutral",
                "duration": 1.2,
            }
        )

        result = self.manager._try_openai_api(b"wav-bytes", "en", {}, self.manager._http_session)

        self.assertEqual(result, "hello from sensevoice")

    def test_try_openai_api_strips_sensevoice_inline_labels(self):
        """Test SenseVoice rich-text labels are not injected into the desktop."""
        _setup_requests_post_ok({"text": "<|en|><|NEUTRAL|><|Speech|><|withitn|>hello"})

        result = self.manager._try_openai_api(b"wav-bytes", "en", {}, self.manager._http_session)

        self.assertEqual(result, "hello")

    def test_try_openai_api_accepts_segmented_response(self):
        """Test OpenAI-compatible responses that include transcript segments."""
        _setup_requests_post_ok(
            {
                "segments": [
                    {"text": "first part"},
                    {"text": "second part"},
                ],
                "metadata": {"model": "sensevoice"},
            }
        )

        result = self.manager._try_openai_api(b"wav-bytes", "en", {}, self.manager._http_session)

        self.assertEqual(result, "first part\nsecond part")

    def test_try_openai_api_server_error(self):
        """Test OpenAI API handles 500 server error via raise_for_status."""
        _setup_requests_post_status(500, Exception("500 Server Error"))

        result = self.manager._try_openai_api(b"wav", "en", {}, self.manager._http_session)

        self.assertIsNone(result)

    def test_try_openai_api_auth_error(self):
        """Test OpenAI API handles 401 unauthorized via raise_for_status."""
        _setup_requests_post_status(401, Exception("401 Unauthorized"))

        result = self.manager._try_openai_api(b"wav", "en", {}, self.manager._http_session)

        self.assertIsNone(result)


class TestWhisperCppServerAPIFormat(unittest.TestCase):
    """Test cases for whisper.cpp server API format."""

    def setUp(self):
        """Set up test fixtures."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        self.manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_key="server-key",
            remote_api_endpoint="/inference",
        )

    def test_try_whispercpp_server_api_success(self):
        """Test successful transcription via whisper.cpp server API."""
        _setup_requests_post_ok({"text": "spoken words"})

        result = self.manager._try_whispercpp_server_api(
            b"audio-wav", "de", {"Authorization": "Bearer key"}, self.manager._http_session
        )

        self.assertEqual(result, "spoken words")

    def test_try_whispercpp_server_api_404(self):
        """Test whisper.cpp server returns None for 404."""
        _setup_requests_post_status(404)

        result = self.manager._try_whispercpp_server_api(
            b"wav", "es", {}, self.manager._http_session
        )

        self.assertIsNone(result)

    def test_try_whispercpp_server_api_connection_error(self):
        """Test whisper.cpp server handles connection errors."""
        _setup_requests_post_error(Exception("Connection refused"))

        result = self.manager._try_whispercpp_server_api(
            b"wav", "es", {}, self.manager._http_session
        )

        self.assertIsNone(result)

    def test_try_whispercpp_server_api_server_error(self):
        """Test whisper.cpp server handles 500 error via raise_for_status."""
        _setup_requests_post_status(500, Exception("500 Server Error"))

        result = self.manager._try_whispercpp_server_api(
            b"wav", "en", {}, self.manager._http_session
        )

        self.assertIsNone(result)

    def test_try_whispercpp_server_api_auth_error(self):
        """Test whisper.cpp server handles 401 unauthorized via raise_for_status."""
        _setup_requests_post_status(401, Exception("401 Unauthorized"))

        result = self.manager._try_whispercpp_server_api(
            b"wav", "en", {}, self.manager._http_session
        )

        self.assertIsNone(result)


class TestRemoteAPIReconfiguration(unittest.TestCase):
    """Test cases for remote API settings updates."""

    def setUp(self):
        """Set up test fixtures."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        self.manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

    def test_update_remote_api_url(self):
        """Test updating remote API URL via reconfigure triggers reinit."""
        _setup_requests_get_ok()

        self.manager.reconfigure(remote_api_url="https://new-server:9090")

        self.assertEqual(self.manager.remote_api_url, "https://new-server:9090")
        # Verify successful reinitialization after reconfigure
        self.assertTrue(self.manager._model_initialized)
        self.assertTrue(self.manager.model_ready)

    def test_update_remote_api_key(self):
        """Test updating remote API key via reconfigure."""
        self.manager.reconfigure(remote_api_key="new-secret-key")
        self.assertEqual(self.manager.remote_api_key, "new-secret-key")

    def test_update_remote_api_endpoint(self):
        """Test updating remote API endpoint via reconfigure."""
        self.manager.reconfigure(remote_api_endpoint="/v1/audio/transcriptions")
        self.assertEqual(self.manager.remote_api_endpoint, "/v1/audio/transcriptions")

    def test_update_remote_api_model(self):
        """Test updating remote API model via reconfigure."""
        self.manager.reconfigure(remote_api_model="sensevoice")
        self.assertEqual(self.manager.remote_api_model, "sensevoice")


class TestRemoteAPIReinitializeAfterResume(unittest.TestCase):
    """Test cases for reinitialize_after_resume with remote_api engine."""

    def test_reinitialize_after_resume_calls_init_remote_api(self):
        """Test that reinitialize_after_resume dispatches to _init_remote_api."""
        from unittest.mock import patch

        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

        with patch.object(manager, "_init_remote_api") as mock_init:
            manager.reinitialize_after_resume()

        mock_init.assert_called_once()

    def test_reinitialize_after_resume_without_url_does_not_raise(self):
        """Test that reinitialize_after_resume with empty URL sets _model_initialized False."""
        SpeechRecognitionManager = _import_manager()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="",
        )

        # Should not raise any exception
        manager.reinitialize_after_resume()

        self.assertFalse(manager._model_initialized)

    def test_reinitialize_after_resume_unknown_engine_returns_silently(self):
        """Unknown engine value short-circuits reinit without raising or dispatching."""
        from unittest.mock import patch

        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        manager.engine = "bogus_engine"

        with (
            patch.object(manager, "_init_remote_api") as mock_remote,
            patch.object(manager, "_init_vosk") as mock_vosk,
            patch.object(manager, "_init_whisper") as mock_whisper,
            patch.object(manager, "_init_whispercpp") as mock_whispercpp,
        ):
            manager.reinitialize_after_resume()

        mock_remote.assert_not_called()
        mock_vosk.assert_not_called()
        mock_whisper.assert_not_called()
        mock_whispercpp.assert_not_called()
        self.assertFalse(manager._model_initialized)


class TestHTTPSession(unittest.TestCase):
    """Test cases for manager-owned requests.Session (connection pooling)."""

    def test_init_remote_api_creates_session(self):
        """_init_remote_api creates a requests.Session and stores it on _http_session."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

        mock_requests = _get_mock_requests()
        mock_requests.Session.assert_called()
        self.assertIs(manager._http_session, mock_requests.Session.return_value)

    def test_transcribe_uses_session_post(self):
        """_try_whispercpp_server_api calls self._http_session.post, not module-level requests.post."""
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_endpoint="/inference",
        )

        mock_session = _get_mock_session()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "hello"}
        mock_session.post.return_value = mock_response

        result = manager._try_whispercpp_server_api(b"wav-bytes", "en", {}, manager._http_session)

        self.assertEqual(result, "hello")
        mock_session.post.assert_called_once()
        # Module-level requests.post must NOT have been called
        self.assertFalse(_get_mock_requests().post.called)

    def test_reconfigure_away_from_remote_api_closes_session(self):
        """reconfigure(engine='vosk') from remote_api calls session.close() and nulls _http_session."""
        from unittest.mock import patch

        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

        session = manager._http_session

        with patch.object(manager, "_init_vosk"):
            manager.reconfigure(engine="vosk")

        session.close.assert_called_once()
        self.assertIsNone(manager._http_session)

    def test_reinit_closes_previous_session_before_creating_new(self):
        """A second _init_remote_api call closes the previous session before creating a new one."""
        from unittest.mock import MagicMock

        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        # Give Session() distinct return values for each call so we can track them
        mock_requests = _get_mock_requests()
        first_session = MagicMock(name="session1")
        second_session = MagicMock(name="session2")
        first_session.get.return_value = Mock(ok=True, status_code=200)
        second_session.get.return_value = Mock(ok=True, status_code=200)
        mock_requests.Session.side_effect = [first_session, second_session]

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

        self.assertIs(manager._http_session, first_session)

        # Call _init_remote_api a second time (simulates back-to-back inits)
        manager._init_remote_api()

        first_session.close.assert_called_once()
        self.assertIs(manager._http_session, second_session)


class TestProcessAudioBufferRemoteAPI(unittest.TestCase):
    """Test _process_audio_buffer dispatching to remote API engine."""

    def setUp(self):
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        self.manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )
        self.manager._voice_commands_enabled = False
        self.manager.text_callbacks = []
        self.manager.action_callbacks = []

    def test_process_audio_buffer_remote_api_success(self):
        """_process_audio_buffer snapshots session under lock and dispatches to remote API."""
        from unittest.mock import patch

        with patch.object(
            self.manager, "_transcribe_with_remote_api", return_value="hello"
        ) as mock_transcribe:
            self.manager._process_audio_buffer([b"audio-data"])

        mock_transcribe.assert_called_once()
        args, _ = mock_transcribe.call_args
        self.assertEqual(args[0], [b"audio-data"])
        self.assertIs(args[1], self.manager._http_session)

    def test_process_audio_buffer_remote_api_session_none_returns_early(self):
        """_process_audio_buffer returns early when _http_session is None."""
        from unittest.mock import patch

        self.manager._http_session = None

        with patch.object(self.manager, "_transcribe_with_remote_api") as mock_transcribe:
            self.manager._process_audio_buffer([b"audio-data"])

        mock_transcribe.assert_not_called()


class TestReinitializeAfterResumeSessionClose(unittest.TestCase):
    """Test that reinitialize_after_resume closes the HTTP session."""

    def test_reinitialize_after_resume_closes_http_session(self):
        """reinitialize_after_resume calls session.close() before nulling _http_session."""
        from unittest.mock import patch

        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()

        manager = SpeechRecognitionManager(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
        )

        session = manager._http_session

        with patch.object(manager, "_init_remote_api"):
            manager.reinitialize_after_resume()

        session.close.assert_called_once()
        self.assertIsNone(manager._http_session)


class TestRemoteAPIVocabularyBiasing(unittest.TestCase):
    """Custom vocabulary is injected as a prompt into remote API requests."""

    def _make_manager(self, **kwargs):
        SpeechRecognitionManager = _import_manager()
        _setup_requests_get_ok()
        defaults = dict(
            engine="remote_api",
            remote_api_url="http://localhost:9090",
            remote_api_endpoint="/v1/audio/transcriptions",
        )
        defaults.update(kwargs)
        return SpeechRecognitionManager(**defaults)

    def _mock_response(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "hello"}
        return response

    def test_init_stores_custom_vocabulary(self):
        manager = self._make_manager(custom_vocabulary=["Cyrille", "Kubernetes"])
        self.assertEqual(manager.custom_vocabulary, ["Cyrille", "Kubernetes"])

    def test_init_defaults_to_empty_vocabulary(self):
        manager = self._make_manager()
        self.assertEqual(manager.custom_vocabulary, [])

    def test_reconfigure_updates_vocabulary(self):
        manager = self._make_manager(custom_vocabulary=[])
        manager.reconfigure(custom_vocabulary=["Cyrille"])
        self.assertEqual(manager.custom_vocabulary, ["Cyrille"])

    def test_openai_api_sends_prompt_when_vocabulary_set(self):
        manager = self._make_manager(custom_vocabulary=["Cyrille", "Kubernetes"])
        session = MagicMock()
        session.post.return_value = self._mock_response()

        manager._try_openai_api(b"audio", "en", {}, session)

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["data"]["prompt"], "Cyrille, Kubernetes")

    def test_openai_api_omits_prompt_when_vocabulary_empty(self):
        manager = self._make_manager(custom_vocabulary=[])
        session = MagicMock()
        session.post.return_value = self._mock_response()

        manager._try_openai_api(b"audio", "en", {}, session)

        _, kwargs = session.post.call_args
        self.assertNotIn("prompt", kwargs["data"])

    def test_whispercpp_server_api_sends_prompt_when_vocabulary_set(self):
        manager = self._make_manager(
            remote_api_endpoint="/inference",
            custom_vocabulary=["Cyrille"],
        )
        session = MagicMock()
        session.post.return_value = self._mock_response()

        manager._try_whispercpp_server_api(b"audio", "en", {}, session)

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["data"]["prompt"], "Cyrille")

    def test_whispercpp_server_api_omits_prompt_when_vocabulary_empty(self):
        manager = self._make_manager(remote_api_endpoint="/inference", custom_vocabulary=[])
        session = MagicMock()
        session.post.return_value = self._mock_response()

        manager._try_whispercpp_server_api(b"audio", "en", {}, session)

        _, kwargs = session.post.call_args
        self.assertNotIn("prompt", kwargs["data"])


if __name__ == "__main__":
    unittest.main()

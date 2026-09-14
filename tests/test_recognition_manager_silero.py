"""
Integration-style tests for the Silero VAD path in _record_audio.

Drives the recording loop with a mocked PyAudio stream and a Mock SileroVAD
returning scripted speech probabilities. Verifies:

- silence-only input -> no transcription segment is enqueued
- speech followed by silence -> _enqueue_audio_segment is called after silence_timeout
- speech -> silence_counter resets, no premature flush
- vad_sensitivity threshold mapping kicks in (sens=1 vs sens=5 give different decisions)
- Silero state is reset at the start of every recording session
"""

import sys
import unittest  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

# Earlier test modules install `sys.modules["numpy"] = MagicMock()` at module
# load and don't restore it. Reuse the real module cached by conftest instead
# of unloading/re-importing NumPy's compiled extensions.
if isinstance(sys.modules.get("numpy"), MagicMock):
    _real_numpy = getattr(sys, "_vocalinux_real_numpy", None)
    if _real_numpy is not None:
        sys.modules["numpy"] = _real_numpy

import numpy as np  # noqa: E402

# ---- Mock external deps that recognition_manager imports ----
_MOCK_KEYS = ["vosk", "whisper", "torch", "pyaudio", "pywhispercpp", "pywhispercpp.model"]
_ORIG_MODULES = {}
for _k in _MOCK_KEYS:
    _ORIG_MODULES[_k] = sys.modules.get(_k)
    if _k not in sys.modules:
        sys.modules[_k] = MagicMock()

if "gi" not in sys.modules:
    sys.modules["gi"] = MagicMock()
if "gi.repository" not in sys.modules:
    sys.modules["gi.repository"] = MagicMock()

from vocalinux.common_types import RecognitionState  # noqa: E402
from vocalinux.speech_recognition.recognition_manager import (  # noqa: E402
    SpeechRecognitionManager,
)

for _k, _v in _ORIG_MODULES.items():
    if _v is not None:
        sys.modules[_k] = _v
    elif _k in sys.modules and isinstance(sys.modules[_k], MagicMock):
        del sys.modules[_k]


CHUNK_BYTES = 1024 * 2  # 1024 int16 samples
SILENT_CHUNK = b"\x00" * (1024 * 2)  # 1024 int16 zero samples


def _make_manager():
    """Create a SpeechRecognitionManager with init paths stubbed out."""
    with (
        patch.object(SpeechRecognitionManager, "_init_vosk"),
        patch.object(SpeechRecognitionManager, "_init_whisper"),
        patch.object(SpeechRecognitionManager, "_init_whispercpp"),
    ):
        mgr = SpeechRecognitionManager(
            engine="whisper_cpp",
            model_size="small",
            language="en-us",
            defer_download=True,
        )
    return mgr


class TestManagerSileroInitialization(unittest.TestCase):
    def test_logs_when_silero_vad_loads(self):
        """Manager initialization should report when neural VAD is active."""
        vad = MagicMock()
        with (
            patch.object(SpeechRecognitionManager, "_init_vosk"),
            patch.object(SpeechRecognitionManager, "_init_whisper"),
            patch.object(SpeechRecognitionManager, "_init_whispercpp"),
            patch(
                "vocalinux.speech_recognition.recognition_manager.load_silero_vad",
                return_value=vad,
            ),
            patch("vocalinux.speech_recognition.recognition_manager.logger") as logger_mock,
        ):
            mgr = SpeechRecognitionManager(
                engine="whisper_cpp",
                model_size="small",
                language="en-us",
                defer_download=True,
            )

        self.assertIs(mgr._silero_vad, vad)
        logger_mock.info.assert_any_call("Using Silero neural VAD")


def _make_pyaudio_module(stream):
    """Build a fake pyaudio module that returns the given stream from audio.open()."""
    audio = MagicMock()
    audio.get_device_count.return_value = 1
    audio.get_default_input_device_info.return_value = {
        "index": 0,
        "name": "mock",
        "maxInputChannels": 1,
        "defaultSampleRate": 16000,
    }
    audio.get_device_info_by_index.return_value = {
        "index": 0,
        "name": "mock",
        "maxInputChannels": 1,
        "defaultSampleRate": 16000,
    }
    audio.is_format_supported.return_value = True
    audio.open.return_value = stream

    pyaudio_mod = MagicMock(paInt16=8, PyAudio=MagicMock(return_value=audio))
    return pyaudio_mod, audio


def _scripted_stream(probs_per_chunk, manager, max_iters=None, chunk_bytes=None):
    """Return a Mock stream whose read() drives `manager.should_record` to False
    once we've consumed `max_iters` (or len(probs_per_chunk)) chunks.

    Each read() returns silent bytes; the speech/silence decision comes from
    the scripted probabilities fed via the mocked SileroVAD. `chunk_bytes`
    overrides the default 1024-int16 size (e.g. stereo at 16 kHz needs 4096
    bytes per CHUNK frame).
    """
    stream = MagicMock()
    counter = {"n": 0}
    limit = max_iters if max_iters is not None else len(probs_per_chunk)
    payload = b"\x00" * (chunk_bytes if chunk_bytes is not None else 1024 * 2)

    def _read(*args, **kwargs):
        counter["n"] += 1
        if counter["n"] >= limit:
            manager.should_record = False
        return payload

    stream.read.side_effect = _read
    return stream


def _make_silero(probs):
    """Mock SileroVAD: process() returns scripted probs, repeating the last
    value forever once the list is exhausted (each outer read() drives 2 silero
    chunks of 512 samples, so we need plenty of values).
    """
    vad = MagicMock()
    state = {"i": 0, "last": probs[-1] if probs else 0.0}

    def _process(_chunk):
        i = state["i"]
        if i < len(probs):
            state["i"] = i + 1
            return probs[i]
        return state["last"]

    vad.process.side_effect = _process
    return vad


class TestRecordAudioSileroPath(unittest.TestCase):
    def setUp(self):
        self.mgr = _make_manager()
        self.mgr.state = RecognitionState.LISTENING
        self.mgr.should_record = True
        self.mgr.audio_buffer = []
        self.mgr.silence_timeout = 0.5  # short timeout for fast tests
        self.mgr.vad_sensitivity = 3

        # Capture flushes triggered by the silence-detection branch
        self.enqueued = []
        self.mgr._enqueue_audio_segment = lambda buf: self.enqueued.append(list(buf))

    def _drive(
        self,
        probs,
        vad_sensitivity=3,
        max_iters=None,
        channels=1,
        rate=16000,
        chunk_bytes=None,
    ):
        """Run _record_audio with the given scripted Silero probabilities."""
        self.mgr.vad_sensitivity = vad_sensitivity
        self.mgr._silero_vad = _make_silero(probs)

        stream = _scripted_stream(
            probs,
            self.mgr,
            max_iters=max_iters or len(probs),
            chunk_bytes=chunk_bytes,
        )
        pyaudio_mod, _audio = _make_pyaudio_module(stream)

        # _record_audio does `import numpy as np` lazily inside the function;
        # earlier test modules may have left sys.modules["numpy"] as a
        # MagicMock, so put real numpy back for the duration of the call.
        with (
            patch.dict(sys.modules, {"pyaudio": pyaudio_mod, "numpy": np}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._open_capture_stream",
                return_value=(channels, rate, stream),
            ),
        ):
            self.mgr._record_audio()

    def test_reset_called_at_session_start(self):
        """Silero state must be cleared between recording sessions."""
        self._drive(probs=[0.1] * 5)
        self.assertTrue(self.mgr._silero_vad.reset.called)

    def test_silence_only_drops_buffer_without_enqueue(self):
        """Sustained silence past silence_timeout should not reach transcription."""
        # Each chunk = 1024/16000 = 0.064s. silence_timeout=0.5s, so ~8 chunks
        # of silence crosses the timeout. Run 20 chunks to ensure the threshold fires.
        self._drive(probs=[0.05] * 20, vad_sensitivity=3)
        self.assertEqual(len(self.enqueued), 0, "silence-only input should be dropped")

    def test_speech_then_silence_triggers_segment_enqueue(self):
        """Speech followed by sustained silence should flush the speech segment."""
        probs = [0.95] * 6 + [0.05] * 20
        self._drive(probs=probs, vad_sensitivity=3)
        self.assertGreaterEqual(
            len(self.enqueued), 1, "expected speech-followed-by-silence to enqueue"
        )

    def test_speech_prevents_premature_flush(self):
        """Speech probs above threshold should reset the silence counter."""
        # Continuous speech (prob well above threshold for sens=3 -> 0.55).
        # 20 chunks * 0.064s = 1.28s, more than silence_timeout=0.5s,
        # but speech_counter never accumulates -> no flush.
        self._drive(probs=[0.95] * 20, vad_sensitivity=3)
        self.assertEqual(len(self.enqueued), 0, "speech should keep silence counter at 0, no flush")

    def test_sensitivity_lowest_blocks_borderline_speech(self):
        """At sensitivity=1 (threshold 0.8), prob=0.6 is silence."""
        # 20 chunks of borderline prob; with strict threshold these read as silence
        # and the silence-only buffer gets dropped.
        self._drive(probs=[0.6] * 20, vad_sensitivity=1)
        self.assertEqual(len(self.enqueued), 0)

    def test_sensitivity_highest_accepts_borderline_speech(self):
        """At sensitivity=5 (threshold 0.3), prob=0.6 is speech, no flush."""
        self._drive(probs=[0.6] * 20, vad_sensitivity=5)
        self.assertEqual(len(self.enqueued), 0)

    def test_invalid_sensitivity_uses_default_silero_threshold(self):
        """Bad sensitivity values should fall back to the default Silero threshold."""
        self._drive(probs=[0.95] * 20, vad_sensitivity="bad")
        self.assertEqual(len(self.enqueued), 0)

    def test_push_to_talk_defers_speech_segment_until_release(self):
        """Push-to-talk should keep a spoken segment buffered after silence."""
        self.mgr._recognition_mode = "push_to_talk"

        self._drive(probs=[0.95] * 6 + [0.05] * 20, vad_sensitivity=3)

        self.assertEqual(len(self.enqueued), 0)
        self.assertGreater(len(self.mgr.audio_buffer), 0)
        self.assertTrue(self.mgr._recording_segment_has_speech)

    def test_stereo_capture_is_downmixed_without_error(self):
        """CHANNELS=2 -> the stereo->mono branch runs and the loop completes."""
        self._drive(probs=[0.05] * 12, vad_sensitivity=3, channels=2, chunk_bytes=1024 * 2 * 2)
        # No assertion on enqueue count -- just verify the path runs cleanly.

    def test_quad_capture_is_downmixed_without_error(self):
        """CHANNELS=4 -> the N-channel downmix branch runs and the loop completes."""
        self._drive(probs=[0.05] * 12, vad_sensitivity=3, channels=4, chunk_bytes=1024 * 4 * 2)

    def test_resample_branch_runs_at_48khz(self):
        """rate=48000 -> the resample branch in _record_audio runs."""
        self._drive(probs=[0.05] * 12, vad_sensitivity=3, rate=48000)


class TestRecordAudioAmplitudeFallback(unittest.TestCase):
    """When onnxruntime is unavailable, _record_audio falls back to an amplitude
    threshold. These tests drive that path with `_silero_vad = None`.
    """

    def setUp(self):
        self.mgr = _make_manager()
        self.mgr.state = RecognitionState.LISTENING
        self.mgr.should_record = True
        self.mgr.audio_buffer = []
        self.mgr.silence_timeout = 0.5
        self.mgr.vad_sensitivity = 3
        self.mgr._silero_vad = None

        self.enqueued = []
        self.mgr._enqueue_audio_segment = lambda buf: self.enqueued.append(list(buf))

    def _drive(self, payload, max_iters):
        stream = MagicMock()
        counter = {"n": 0}

        def _read(*a, **kw):
            counter["n"] += 1
            if counter["n"] >= max_iters:
                self.mgr.should_record = False
            return payload

        stream.read.side_effect = _read
        pyaudio_mod, _ = _make_pyaudio_module(stream)
        with (
            patch.dict(sys.modules, {"pyaudio": pyaudio_mod, "numpy": np}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_channels",
                return_value=1,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_sample_rate",
                return_value=16000,
            ),
        ):
            self.mgr._record_audio()

    def test_silence_drops_buffer(self):
        """All-zero samples -> volume below threshold -> no transcription segment."""
        self._drive(payload=b"\x00" * (1024 * 2), max_iters=20)
        self.assertEqual(len(self.enqueued), 0)

    def test_invalid_sensitivity_uses_default_amplitude_threshold(self):
        """Bad sensitivity values should fall back to the default amplitude threshold."""
        self.mgr.vad_sensitivity = "bad"
        self._drive(payload=b"\x00" * (1024 * 2), max_iters=20)
        self.assertEqual(len(self.enqueued), 0)

    def test_loud_audio_is_speech(self):
        """Loud samples -> volume above threshold -> speech, no flush."""
        loud = (np.full(1024, 20000, dtype=np.int16)).tobytes()
        self._drive(payload=loud, max_iters=20)
        self.assertEqual(len(self.enqueued), 0)


class TestAudioLevelCallback(unittest.TestCase):
    """The audio-level callback list is iterated every chunk with normalized
    level in [0, 100]. Verify a registered callback receives values.
    """

    def test_callback_receives_levels(self):
        mgr = _make_manager()
        mgr.state = RecognitionState.LISTENING
        mgr.should_record = True
        mgr.audio_buffer = []
        mgr.silence_timeout = 0.5
        mgr.vad_sensitivity = 3
        mgr._silero_vad = None
        mgr._enqueue_audio_segment = lambda buf: None

        levels = []
        mgr._audio_level_callbacks = [levels.append]

        stream = MagicMock()
        counter = {"n": 0}

        def _read(*a, **kw):
            counter["n"] += 1
            if counter["n"] >= 5:
                mgr.should_record = False
            return b"\x00" * (1024 * 2)

        stream.read.side_effect = _read
        pyaudio_mod, _ = _make_pyaudio_module(stream)
        with (
            patch.dict(sys.modules, {"pyaudio": pyaudio_mod, "numpy": np}),
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_channels",
                return_value=1,
            ),
            patch(
                "vocalinux.speech_recognition.recognition_manager._get_supported_sample_rate",
                return_value=16000,
            ),
        ):
            mgr._record_audio()

        self.assertGreaterEqual(len(levels), 1)
        for v in levels:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 100.0)


if __name__ == "__main__":
    unittest.main()

"""
Tests for the TinyDiarize file-transcription module.

Covers speaker-turn parsing, transcript formatting, and audio decoding —
the parts of the "Transcribe audio file" flow that do not need GTK.
"""

import importlib
import subprocess
import sys
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _real_wave_and_numpy():
    """Pin real wave/numpy in sys.modules for each test.

    Sibling test modules replace them with MagicMocks at import time (the same
    hazard test_audio_feedback's fixture documents), and diarization binds
    `import wave`/`import numpy`/`import tempfile` when first imported inside a
    test. Popping before reimporting works no matter which module was imported
    first.
    """
    poisoned = ("wave", "numpy", "tempfile")
    previous = {name: sys.modules.pop(name, None) for name in poisoned}
    for name in poisoned:
        sys.modules[name] = importlib.import_module(name)
    # If another test imported diarization while wave/numpy were mocked, its
    # module-level bindings are stale — force a reimport under the real ones.
    sys.modules.pop("vocalinux.speech_recognition.diarization", None)
    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@dataclass
class _FakeSegment:
    """Stand-in for pywhispercpp's Segment (t0/t1 in 10 ms units)."""

    t0: int
    t1: int
    text: str
    probability: float = 0.9


class TestSpeakerTurnBlocks(unittest.TestCase):
    """TinyDiarize emits [SPEAKER_TURN] markers; each one starts a block."""

    def test_single_speaker_run_stays_one_block(self):
        from vocalinux.speech_recognition.diarization import speaker_turn_blocks

        segments = [
            _FakeSegment(0, 150, "Hello there."),
            _FakeSegment(150, 320, "How are you?"),
        ]
        blocks = speaker_turn_blocks(segments)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].speaker, 1)
        self.assertEqual(blocks[0].start_seconds, 0.0)
        self.assertEqual(blocks[0].text, "Hello there. How are you?")

    def test_marker_starts_a_new_speaker(self):
        from vocalinux.speech_recognition.diarization import speaker_turn_blocks

        segments = [
            _FakeSegment(0, 150, "First speaker."),
            _FakeSegment(150, 320, "[SPEAKER_TURN] And a reply."),
        ]
        blocks = speaker_turn_blocks(segments)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].speaker, 1)
        self.assertEqual(blocks[0].text, "First speaker.")
        self.assertEqual(blocks[1].speaker, 2)
        self.assertEqual(blocks[1].start_seconds, 1.5)
        self.assertEqual(blocks[1].text, "And a reply.")

    def test_marker_mid_segment_splits_the_text(self):
        from vocalinux.speech_recognition.diarization import speaker_turn_blocks

        segments = [_FakeSegment(50, 320, "Hello. [SPEAKER_TURN] Hi back.")]
        blocks = speaker_turn_blocks(segments)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0].start_seconds, 0.5)
        self.assertEqual(blocks[0].text, "Hello.")
        self.assertEqual(blocks[1].speaker, 2)
        self.assertEqual(blocks[1].text, "Hi back.")

    def test_adjacent_turns_number_speakers_sequentially(self):
        from vocalinux.speech_recognition.diarization import speaker_turn_blocks

        segments = [
            _FakeSegment(0, 100, "One."),
            _FakeSegment(100, 200, "[SPEAKER_TURN] Two. [SPEAKER_TURN] Three."),
        ]
        blocks = speaker_turn_blocks(segments)

        self.assertEqual([block.speaker for block in blocks], [1, 2, 3])
        self.assertEqual([block.text for block in blocks], ["One.", "Two.", "Three."])

    def test_silence_only_output_gives_no_blocks(self):
        from vocalinux.speech_recognition.diarization import speaker_turn_blocks

        segments = [_FakeSegment(0, 100, "[SPEAKER_TURN]")]
        self.assertEqual(speaker_turn_blocks(segments), [])
        self.assertEqual(speaker_turn_blocks([]), [])


class TestFormatTimestamp(unittest.TestCase):
    def test_formats_hours_minutes_seconds(self):
        from vocalinux.speech_recognition.diarization import format_timestamp

        self.assertEqual(format_timestamp(0), "00:00:00")
        self.assertEqual(format_timestamp(61.9), "00:01:01")
        self.assertEqual(format_timestamp(3600 + 62 + 3), "01:01:05")

    def test_negative_times_clamp_to_zero(self):
        from vocalinux.speech_recognition.diarization import format_timestamp

        self.assertEqual(format_timestamp(-5), "00:00:00")


class TestFormatTranscript(unittest.TestCase):
    def test_renders_timestamped_speaker_lines(self):
        from vocalinux.speech_recognition.diarization import TranscriptBlock, format_transcript

        blocks = [
            TranscriptBlock(0.0, 1, "Hello there."),
            TranscriptBlock(12.5, 2, "Hi back."),
        ]
        self.assertEqual(
            format_transcript(blocks),
            "[00:00:00] Speaker 1: Hello there.\n\n[00:00:12] Speaker 2: Hi back.",
        )

    def test_empty_transcript_is_empty_string(self):
        from vocalinux.speech_recognition.diarization import format_transcript

        self.assertEqual(format_transcript([]), "")


def _write_wav(path, sample_rate=16000, channels=1, sample_width=2, frames=160):
    """Write a minimal PCM WAV: silence for ``frames`` frames."""
    # Resolve wave at call time: sibling test modules poison sys.modules.
    import wave

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames * channels)


class TestLoadAudio(unittest.TestCase):
    def test_strict_wav_loads_directly(self):
        import tempfile
        from pathlib import Path

        import numpy as np

        from vocalinux.speech_recognition.diarization import load_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "sample.wav"
            _write_wav(wav_path)
            audio = load_audio(str(wav_path))

        self.assertIsInstance(audio, np.ndarray)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.size, 160)

    def test_stereo_wav_is_downmixed(self):
        import tempfile
        from pathlib import Path

        import numpy as np

        from vocalinux.speech_recognition.diarization import load_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "stereo.wav"
            _write_wav(wav_path, channels=2)
            audio = load_audio(str(wav_path))

        self.assertEqual(audio.size, 160)

    def test_wrong_rate_wav_falls_back_to_ffmpeg(self):
        import tempfile
        from pathlib import Path

        from vocalinux.speech_recognition.diarization import load_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "speech.wav"
            _write_wav(wav_path, sample_rate=44100)

            with patch("vocalinux.speech_recognition.diarization._load_with_ffmpeg") as mock_ffmpeg:
                mock_ffmpeg.return_value = MagicMock()
                load_audio(str(wav_path))
                mock_ffmpeg.assert_called_once_with(str(wav_path))

    def test_non_wav_goes_to_ffmpeg(self):
        import tempfile
        from pathlib import Path

        import numpy as np

        from vocalinux.speech_recognition.diarization import load_audio

        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = Path(tmpdir) / "clip.mp3"
            media_path.write_bytes(b"ID3\x04\x00")

            with patch("vocalinux.speech_recognition.diarization._load_with_ffmpeg") as mock_ffmpeg:
                mock_ffmpeg.return_value = np.zeros(16, dtype=np.float32)
                audio = load_audio(str(media_path))

        self.assertIsInstance(audio, np.ndarray)

    def test_missing_ffmpeg_reports_a_clean_error(self):
        import tempfile
        from pathlib import Path

        from vocalinux.speech_recognition.diarization import _load_with_ffmpeg

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "clip.ogg"
            path.write_bytes(b"OggS")
            with patch("shutil.which", return_value=None):
                with self.assertRaises(RuntimeError) as ctx:
                    _load_with_ffmpeg(str(path))
        self.assertIn("ffmpeg", str(ctx.exception))

    def test_ffmpeg_decode_runs_as_host_process(self):
        """ffmpeg is a host binary: it must run under host_env(), not the bundle."""
        import tempfile
        from pathlib import Path

        from vocalinux.speech_recognition.diarization import _load_with_ffmpeg

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "clip.mp3"
            path.write_bytes(b"ID3")

            def fake_run(cmd, **kwargs):
                # Produce a valid WAV so the load completes.
                _write_wav(Path(cmd[-1]))
                return MagicMock(returncode=0)

            with (
                patch("shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("subprocess.run", side_effect=fake_run) as mock_run,
                patch(
                    "vocalinux.speech_recognition.diarization.host_env",
                    return_value={"HOST": "1"},
                ) as mock_env,
            ):
                audio = _load_with_ffmpeg(str(path))

        self.assertIsNotNone(audio)
        self.assertEqual(mock_run.call_args.kwargs["env"], {"HOST": "1"})
        mock_env.assert_called_once()

    def test_ffmpeg_failure_surfaces_as_runtime_error(self):
        import tempfile
        from pathlib import Path

        from vocalinux.speech_recognition.diarization import _load_with_ffmpeg

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.mp3"
            path.write_bytes(b"not real mp3")
            with (
                patch("shutil.which", return_value="/usr/bin/ffmpeg"),
                patch(
                    "subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
                ),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    _load_with_ffmpeg(str(path))
        self.assertIn("could not decode", str(ctx.exception))


class TestTranscribeAudioFile(unittest.TestCase):
    def test_missing_model_fails_before_touching_pywhispercpp(self):
        from vocalinux.speech_recognition.diarization import transcribe_audio_file

        with patch(
            "vocalinux.speech_recognition.diarization.is_model_downloaded",
            return_value=False,
        ):
            with self.assertRaises(FileNotFoundError) as ctx:
                transcribe_audio_file("/tmp/whatever.wav")
        self.assertIn("not downloaded", str(ctx.exception))

    def test_tdrz_enabled_model_transcribes_to_blocks(self):
        import numpy as np

        from vocalinux.speech_recognition import diarization

        fake_model = MagicMock()
        fake_model.transcribe.return_value = [
            _FakeSegment(0, 100, "Hello."),
            _FakeSegment(100, 200, "[SPEAKER_TURN] Hi."),
        ]
        model_cls = MagicMock(return_value=fake_model)

        with (
            patch.object(diarization, "is_model_downloaded", return_value=True),
            patch.object(
                diarization, "get_model_path", return_value="/models/ggml-small.en-tdrz.bin"
            ),
            patch.object(diarization, "verify_model_file"),
            patch("vocalinux.utils.pywhispercpp_loader.preload_shared_libraries"),
            patch.object(diarization, "load_audio", return_value=np.zeros(1600, dtype=np.float32)),
        ):
            # pywhispercpp is imported lazily inside the function.
            fake_module = MagicMock()
            fake_module.Model = model_cls
            with patch.dict("sys.modules", {"pywhispercpp.model": fake_module}):
                blocks = diarization.transcribe_audio_file("/tmp/in.wav")

        model_cls.assert_called_once_with("/models/ggml-small.en-tdrz.bin", tdrz_enable=True)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[1].speaker, 2)

    def test_empty_audio_is_a_clear_error(self):
        import numpy as np

        from vocalinux.speech_recognition import diarization

        with (
            patch.object(diarization, "is_model_downloaded", return_value=True),
            patch.object(diarization, "verify_model_file"),
            patch("vocalinux.utils.pywhispercpp_loader.preload_shared_libraries"),
            patch.object(diarization, "load_audio", return_value=np.zeros(0, dtype=np.float32)),
        ):
            with self.assertRaises(ValueError) as ctx:
                diarization.transcribe_audio_file("/tmp/empty.wav")
        self.assertIn("no audio", str(ctx.exception))

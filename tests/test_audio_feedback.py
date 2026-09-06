"""
Tests for the audio feedback functionality.
"""

import os
import sys
import unittest
from unittest.mock import patch

import pytest

# We need to use absolute paths for patching in module scope
AUDIO_FEEDBACK_MODULE = "vocalinux.ui.audio_feedback"


@pytest.fixture(autouse=True)
def reset_audio_module():
    """Reset the audio_feedback module before each test to allow proper testing."""
    # Remove the mock that conftest installs
    if AUDIO_FEEDBACK_MODULE in sys.modules:
        del sys.modules[AUDIO_FEEDBACK_MODULE]

    yield

    # Restore the mock after test for other tests that need it
    from conftest import mock_audio_feedback

    sys.modules[AUDIO_FEEDBACK_MODULE] = mock_audio_feedback


class TestAudioFeedback(unittest.TestCase):
    """Test cases for audio feedback functionality."""

    def test_resource_paths(self):
        """Test that resource paths are correctly set up."""
        # Import fresh module
        import vocalinux.ui.audio_feedback as audio_feedback

        # Import the resource manager to test paths
        from vocalinux.utils.resource_manager import ResourceManager

        resource_manager = ResourceManager()

        # Verify that resource paths are correctly set and accessible
        self.assertTrue(
            resource_manager.resources_dir.endswith("resources"),
            f"Resources directory is not valid: {resource_manager.resources_dir}",
        )
        self.assertTrue(
            resource_manager.sounds_dir.endswith("sounds"),
            f"Sounds directory path is not valid: {resource_manager.sounds_dir}",
        )
        self.assertEqual(os.path.basename(audio_feedback.START_SOUND), "start_recording.wav")
        self.assertEqual(os.path.basename(audio_feedback.STOP_SOUND), "stop_recording.wav")
        self.assertEqual(os.path.basename(audio_feedback.ERROR_SOUND), "error.wav")

    def test_get_audio_player_pulseaudio(self):
        """Test detecting PulseAudio player."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.shutil, "which") as mock_which:
            # Mock shutil.which to return True for paplay and False for others
            def which_side_effect(cmd):
                return cmd == "paplay"

            mock_which.side_effect = which_side_effect

            # Call the function
            player, formats = audio_feedback._get_audio_player()

            # Verify the correct player was detected
            self.assertEqual(player, "paplay")
            self.assertEqual(formats, ["wav"])

    def test_get_audio_player_alsa(self):
        """Test detecting ALSA player."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.shutil, "which") as mock_which:
            # Mock shutil.which to return False for paplay, True for aplay
            def which_side_effect(cmd):
                return {
                    "paplay": False,
                    "aplay": True,
                    "play": False,
                    "mplayer": False,
                }.get(cmd, False)

            mock_which.side_effect = which_side_effect

            # Call the function
            player, formats = audio_feedback._get_audio_player()

            # Verify the correct player was detected
            self.assertEqual(player, "aplay")
            self.assertEqual(formats, ["wav"])

    def test_get_audio_player_sox(self):
        """Test detecting SoX player."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.shutil, "which") as mock_which:
            # Mock shutil.which to return False for paplay/aplay, True for play
            def which_side_effect(cmd):
                return {
                    "paplay": False,
                    "aplay": False,
                    "play": True,
                    "mplayer": False,
                }.get(cmd, False)

            mock_which.side_effect = which_side_effect

            # Call the function
            player, formats = audio_feedback._get_audio_player()

            # Verify the correct player was detected
            self.assertEqual(player, "play")
            self.assertEqual(formats, ["wav"])

    def test_get_audio_player_mplayer(self):
        """Test detecting MPlayer."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.shutil, "which") as mock_which:
            # Mock shutil.which to return False for all except mplayer
            def which_side_effect(cmd):
                return {
                    "paplay": False,
                    "aplay": False,
                    "play": False,
                    "mplayer": True,
                }.get(cmd, False)

            mock_which.side_effect = which_side_effect

            # Call the function
            player, formats = audio_feedback._get_audio_player()

            # Verify the correct player was detected
            self.assertEqual(player, "mplayer")
            self.assertEqual(formats, ["wav"])

    def test_get_audio_player_none(self):
        """Test behavior when no audio player is available."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.shutil, "which", return_value=None):
            # Call the function
            player, formats = audio_feedback._get_audio_player()

            # Verify no player was detected
            self.assertIsNone(player)
            self.assertEqual(formats, [])

    def test_play_sound_file_missing(self):
        """Test playing a missing sound file."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback.os.path, "exists", return_value=False):
            # Call the function
            result = audio_feedback._play_sound_file("nonexistent.wav")

            # Verify the function returned False
            self.assertFalse(result)

    def test_play_sound_file_no_player(self):
        """Test playing sound with no available player."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(audio_feedback, "_get_audio_player", return_value=(None, [])),
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned False
            self.assertFalse(result)

    def test_play_sound_file_paplay(self):
        """Test playing sound with paplay."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(
                audio_feedback,
                "_get_audio_player",
                return_value=("paplay", ["wav"]),
            ),
            patch.object(audio_feedback.subprocess, "Popen") as mock_popen,
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned True and called Popen correctly
            self.assertTrue(result)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "paplay")
            self.assertEqual(args[0][1], "test.wav")

    def test_play_sound_file_aplay(self):
        """Test playing sound with aplay."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(
                audio_feedback,
                "_get_audio_player",
                return_value=("aplay", ["wav"]),
            ),
            patch.object(audio_feedback.subprocess, "Popen") as mock_popen,
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned True and called Popen correctly
            self.assertTrue(result)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "aplay")
            self.assertEqual(args[0][1], "-q")
            self.assertEqual(args[0][2], "test.wav")

    def test_play_sound_file_mplayer(self):
        """Test playing sound with mplayer."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(
                audio_feedback,
                "_get_audio_player",
                return_value=("mplayer", ["wav"]),
            ),
            patch.object(audio_feedback.subprocess, "Popen") as mock_popen,
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned True and called Popen correctly
            self.assertTrue(result)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "mplayer")
            self.assertEqual(args[0][1], "-really-quiet")
            self.assertEqual(args[0][2], "test.wav")

    def test_play_sound_file_play(self):
        """Test playing sound with play (SoX)."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(audio_feedback, "_get_audio_player", return_value=("play", ["wav"])),
            patch.object(audio_feedback.subprocess, "Popen") as mock_popen,
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned True and called Popen correctly
            self.assertTrue(result)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "play")
            self.assertEqual(args[0][1], "-q")
            self.assertEqual(args[0][2], "test.wav")

    def test_play_sound_file_exception(self):
        """Test handling exception when playing sound."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(
                audio_feedback,
                "_get_audio_player",
                return_value=("paplay", ["wav"]),
            ),
            patch.object(
                audio_feedback.subprocess,
                "Popen",
                side_effect=Exception("Mock error"),
            ),
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned False
            self.assertFalse(result)

    def test_play_start_sound(self):
        """Test playing start sound (default tone is voca)."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
            patch.object(audio_feedback, "_resolved_tone", return_value="voca"),
            patch.object(audio_feedback, "_play_sound_file") as mock_play,
        ):
            audio_feedback.play_start_sound()
            mock_play.assert_called_once_with(audio_feedback.tone_sound_path("voca", "start"))

    def test_play_stop_sound(self):
        """Test playing stop sound (default tone is voca)."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
            patch.object(audio_feedback, "_resolved_tone", return_value="voca"),
            patch.object(audio_feedback, "_play_sound_file") as mock_play,
        ):
            audio_feedback.play_stop_sound()
            mock_play.assert_called_once_with(audio_feedback.tone_sound_path("voca", "stop"))

    def test_play_error_sound(self):
        """Test playing error sound."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback, "_play_sound_file") as mock_play:
            # Call the function
            audio_feedback.play_error_sound()

            # Verify _play_sound_file was called with correct path
            mock_play.assert_called_once_with(audio_feedback.ERROR_SOUND)

    def test_play_sound_file_ci_test_player(self):
        """Test playing sound with ci_test_player (GitHub Actions fallback)."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.object(
                audio_feedback,
                "_get_audio_player",
                return_value=("ci_test_player", ["wav"]),
            ),
            patch.object(audio_feedback.subprocess, "Popen") as mock_popen,
        ):
            # Call the function
            result = audio_feedback._play_sound_file("test.wav")

            # Verify the function returned True and called Popen correctly
            self.assertTrue(result)
            mock_popen.assert_called_once()
            args, kwargs = mock_popen.call_args
            self.assertEqual(args[0][0], "ci_test_player")
            self.assertEqual(args[0][1], "test.wav")

    def test_get_audio_player_github_actions_fallback(self):
        """Test ci_test_player assignment in GitHub Actions without audio player."""
        # Import the module first
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback.shutil, "which", return_value=None),
            patch.object(audio_feedback.os.path, "exists", return_value=True),
            patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}),
        ):
            # First verify _get_audio_player returns None
            player, formats = audio_feedback._get_audio_player()
            self.assertIsNone(player)

            # Now test _play_sound_file which should assign ci_test_player
            with patch.object(audio_feedback.subprocess, "Popen") as mock_popen:
                result = audio_feedback._play_sound_file("test.wav")

                # Should have used ci_test_player
                self.assertTrue(result)
                mock_popen.assert_called_once()
                args, _ = mock_popen.call_args
                self.assertEqual(args[0][0], "ci_test_player")

    def test_play_start_sound_when_disabled(self):
        """Test that start sound is not played when sound effects are disabled."""
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=False):
            result = audio_feedback.play_start_sound()
            self.assertFalse(result)

    def test_play_stop_sound_when_disabled(self):
        """Test that stop sound is not played when sound effects are disabled."""
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=False):
            result = audio_feedback.play_stop_sound()
            self.assertFalse(result)

    def test_play_error_sound_when_disabled(self):
        """Test that error sound is not played when sound effects are disabled."""
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=False):
            result = audio_feedback.play_error_sound()
            self.assertFalse(result)

    def test_is_sound_effects_enabled_returns_true_on_error(self):
        """Test that sound effects are enabled by default when config is unavailable."""
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch(
            "vocalinux.ui.config_manager.get_shared_config_manager",
            side_effect=Exception("No config"),
        ):
            result = audio_feedback._is_sound_effects_enabled()
            self.assertTrue(result)

    def test_missing_or_unknown_tone_uses_voca_not_legacy_pair(self):
        """Unset or unknown tone ids play voca, not start_recording/stop_recording."""
        import vocalinux.ui.audio_feedback as audio_feedback
        from vocalinux.ui.config_manager import (
            DEFAULT_SOUND_EFFECT_TONE,
            normalize_sound_effect_tone,
        )

        self.assertEqual(DEFAULT_SOUND_EFFECT_TONE, "voca")
        for raw in (None, "", "fifth", "01-linux-glide", "not-a-tone"):
            self.assertEqual(normalize_sound_effect_tone(raw), "voca")

        with (
            patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
            patch.object(audio_feedback, "_resolved_tone", return_value="voca"),
            patch.object(audio_feedback, "_play_sound_file") as mock_play,
        ):
            audio_feedback.play_start_sound()
            audio_feedback.play_stop_sound()
            played = [call.args[0] for call in mock_play.call_args_list]
            self.assertTrue(played[0].endswith("voca_start.wav"))
            self.assertTrue(played[1].endswith("voca_stop.wav"))
            self.assertFalse(any("start_recording.wav" in path for path in played))

    def test_off_plays_nothing_for_start_stop(self):
        import vocalinux.ui.audio_feedback as audio_feedback

        with (
            patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
            patch.object(audio_feedback, "_resolved_tone", return_value="off"),
            patch.object(audio_feedback, "_play_sound_file") as mock_play,
        ):
            self.assertFalse(audio_feedback.play_start_sound())
            self.assertFalse(audio_feedback.play_stop_sound())
            mock_play.assert_not_called()

        with (
            patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
            patch.object(audio_feedback, "_play_sound_file") as mock_play,
        ):
            self.assertTrue(audio_feedback.play_error_sound())
            mock_play.assert_called_once_with(audio_feedback.ERROR_SOUND)

    def test_each_catalog_id_maps_to_its_pair(self):
        import vocalinux.ui.audio_feedback as audio_feedback
        from vocalinux.ui.config_manager import SOUND_EFFECT_TONE_IDS, normalize_sound_effect_tone

        catalog_ids = (
            "lift",
            "flick",
            "ember",
            "step",
            "voca",
            "soft",
            "chirp",
            "scale",
            "drop",
            "glass",
            "off",
        )
        self.assertEqual(set(catalog_ids), set(SOUND_EFFECT_TONE_IDS))
        self.assertNotIn("fifth", SOUND_EFFECT_TONE_IDS)

        for tone_id in catalog_ids:
            self.assertEqual(normalize_sound_effect_tone(tone_id), tone_id)
            if tone_id == "off":
                continue
            start = audio_feedback.tone_sound_path(tone_id, "start")
            stop = audio_feedback.tone_sound_path(tone_id, "stop")
            self.assertTrue(os.path.isfile(start), start)
            self.assertTrue(os.path.isfile(stop), stop)
            self.assertTrue(start.endswith(f"{tone_id}_start.wav"))
            self.assertTrue(stop.endswith(f"{tone_id}_stop.wav"))

            with (
                patch.object(audio_feedback, "_is_sound_effects_enabled", return_value=True),
                patch.object(audio_feedback, "_resolved_tone", return_value=tone_id),
                patch.object(audio_feedback, "_play_sound_file") as mock_play,
            ):
                audio_feedback.play_start_sound()
                audio_feedback.play_stop_sound()
                self.assertEqual(mock_play.call_args_list[0].args[0], start)
                self.assertEqual(mock_play.call_args_list[1].args[0], stop)

    def test_preview_tone_does_not_crash(self):
        import vocalinux.ui.audio_feedback as audio_feedback

        class ImmediateTimer:
            def __init__(self, delay, function, args=None, kwargs=None):
                self.function = function
                self.args = args or ()
                self.kwargs = kwargs or {}

            def start(self):
                self.function(*self.args, **self.kwargs)

        with (
            patch.object(audio_feedback, "_play_sound_file", return_value=True) as mock_play,
            patch.object(audio_feedback.threading, "Timer", ImmediateTimer),
        ):
            self.assertTrue(audio_feedback.preview_tone("voca"))
            self.assertEqual(len(mock_play.call_args_list), 2)
            self.assertTrue(mock_play.call_args_list[0].args[0].endswith("voca_start.wav"))
            self.assertTrue(mock_play.call_args_list[1].args[0].endswith("voca_stop.wav"))

            mock_play.reset_mock()
            self.assertFalse(audio_feedback.preview_tone("off"))
            mock_play.assert_not_called()

            mock_play.reset_mock()
            self.assertTrue(audio_feedback.preview_tone("not-a-tone"))
            self.assertTrue(mock_play.call_args_list[0].args[0].endswith("voca_start.wav"))

    def test_preview_tone_cue_plays_one_side(self):
        import vocalinux.ui.audio_feedback as audio_feedback

        with patch.object(audio_feedback, "_play_sound_file", return_value=True) as mock_play:
            self.assertTrue(audio_feedback.preview_tone_cue("voca", "start"))
            self.assertTrue(mock_play.call_args_list[0].args[0].endswith("voca_start.wav"))
            mock_play.reset_mock()
            self.assertTrue(audio_feedback.preview_tone_cue("voca", "stop"))
            self.assertTrue(mock_play.call_args_list[0].args[0].endswith("voca_stop.wav"))
            mock_play.reset_mock()
            self.assertFalse(audio_feedback.preview_tone_cue("off", "start"))
            mock_play.assert_not_called()

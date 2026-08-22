"""Tests for OpenAI Whisper checkpoint file naming.

Regression cover for the review finding on #713: the file name was derived as
``f"{model_size}.pt"`` in three places, which is wrong for "large" — upstream
only ships the versioned checkpoint, so `openai-whisper` stores `large-v3.pt`.
The consequences were a 2.9GB model downloaded and stored twice, and a settings
dialog that reported "large" as missing no matter how often it was fetched.
"""

import os
import unittest
from unittest.mock import patch

from vocalinux.utils.whisper_model_info import (
    WHISPER_MODEL_SIZES,
    whisper_model_file,
)


class TestWhisperModelFile(unittest.TestCase):
    def test_large_maps_to_the_versioned_checkpoint(self):
        self.assertEqual(whisper_model_file("large"), "large-v3.pt")

    def test_other_sizes_keep_their_own_name(self):
        for size in ("tiny", "base", "small", "medium"):
            self.assertEqual(whisper_model_file(size), f"{size}.pt")

    def test_every_catalog_size_is_covered(self):
        for size in WHISPER_MODEL_SIZES:
            self.assertTrue(whisper_model_file(size).endswith(".pt"), size)

    def test_names_match_what_openai_whisper_stores(self):
        """openai-whisper names each file after the basename of its URL."""
        upstream = {
            "tiny": "tiny.pt",
            "base": "base.pt",
            "small": "small.pt",
            "medium": "medium.pt",
            # whisper's _MODELS maps "large" to the large-v3 URL
            "large": "large-v3.pt",
        }
        for size, expected in upstream.items():
            self.assertEqual(whisper_model_file(size), expected, size)


class TestSettingsDialogUsesTheSameName(unittest.TestCase):
    """The UI must look for the file that is actually written to disk."""

    def test_large_is_detected_once_present(self):
        from vocalinux.ui import settings_dialog

        with patch.object(settings_dialog, "_get_whisper_cache_dir", return_value="/models"):

            def exists(path):
                return path == os.path.join("/models", "large-v3.pt")

            with patch("os.path.exists", side_effect=exists):
                self.assertTrue(settings_dialog._is_whisper_model_downloaded("large"))

    def test_a_copy_only_in_the_default_cache_is_not_reported_as_downloaded(self):
        """The engine cannot use ~/.cache/whisper, so the UI must not promise it."""
        from vocalinux.ui import settings_dialog

        with patch.object(settings_dialog, "_get_whisper_cache_dir", return_value="/models"):

            def exists(path):
                return path == os.path.expanduser("~/.cache/whisper/base.pt")

            with patch("os.path.exists", side_effect=exists):
                self.assertFalse(settings_dialog._is_whisper_model_downloaded("base"))

    def test_large_is_not_detected_under_the_wrong_name(self):
        """`large.pt` is a name nothing writes; it must not count as downloaded."""
        from vocalinux.ui import settings_dialog

        with patch.object(settings_dialog, "_get_whisper_cache_dir", return_value="/models"):

            def exists(path):
                return path == os.path.join("/models", "large.pt")

            with patch("os.path.exists", side_effect=exists):
                self.assertFalse(settings_dialog._is_whisper_model_downloaded("large"))


if __name__ == "__main__":
    unittest.main()

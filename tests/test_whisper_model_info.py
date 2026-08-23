"""Tests for OpenAI Whisper checkpoint file naming.

Regression cover for the review finding on #713: the file name was derived as
``f"{model_size}.pt"`` in three places, which is wrong for "large" — upstream
only ships the versioned checkpoint, so `openai-whisper` stores `large-v3.pt`.
The consequences were a 2.9GB model downloaded and stored twice, and a settings
dialog that reported "large" as missing no matter how often it was fetched.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vocalinux.utils.whisper_model_info import (
    WHISPER_MODEL_SIZES,
    migrate_legacy_checkpoint_names,
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


class TestLegacyCheckpointMigration(unittest.TestCase):
    """A checkpoint fetched by an earlier release must not be stranded.

    That release saved "large" as large.pt, from the same large-v3 URL used
    today. Under the old name load_model() cannot see it (2.9GB refetched),
    Settings does not list it, and what is not listed cannot be deleted there.
    """

    def setUp(self):
        self.cache = Path(self.enterContext(TemporaryDirectory()))

    def test_a_legacy_large_is_renamed(self):
        (self.cache / "large.pt").write_bytes(b"checkpoint")

        renamed = migrate_legacy_checkpoint_names(str(self.cache))

        self.assertEqual(renamed, ["large-v3.pt"])
        self.assertEqual((self.cache / "large-v3.pt").read_bytes(), b"checkpoint")
        self.assertFalse((self.cache / "large.pt").exists())

    def test_names_that_already_match_are_untouched(self):
        for size in ("tiny", "base", "small", "medium"):
            (self.cache / f"{size}.pt").write_bytes(size.encode())

        self.assertEqual(migrate_legacy_checkpoint_names(str(self.cache)), [])
        for size in ("tiny", "base", "small", "medium"):
            self.assertEqual((self.cache / f"{size}.pt").read_bytes(), size.encode())

    def test_an_existing_upstream_file_is_never_clobbered(self):
        """The real checkpoint wins; the stale duplicate is left for the user."""
        (self.cache / "large.pt").write_bytes(b"legacy")
        (self.cache / "large-v3.pt").write_bytes(b"current")

        self.assertEqual(migrate_legacy_checkpoint_names(str(self.cache)), [])
        self.assertEqual((self.cache / "large-v3.pt").read_bytes(), b"current")
        self.assertEqual((self.cache / "large.pt").read_bytes(), b"legacy")

    def test_a_rename_failure_is_not_fatal(self):
        """Worst case is the refetch that would have happened regardless."""
        (self.cache / "large.pt").write_bytes(b"checkpoint")

        with patch("os.rename", side_effect=OSError("read-only")):
            self.assertEqual(migrate_legacy_checkpoint_names(str(self.cache)), [])

    def test_an_empty_cache_is_fine(self):
        self.assertEqual(migrate_legacy_checkpoint_names(str(self.cache)), [])


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


class TestTheDialogRescuesALegacyCheckpoint(unittest.TestCase):
    """Wiring test: the rename has to happen where the list is built.

    Without it a "large" downloaded by an earlier release stays absent from the
    dialog, and absent means the delete button never offers it, so 2.9GB sits
    there with no way to reclaim it short of a file manager.
    """

    def test_a_legacy_large_becomes_listed_and_therefore_deletable(self):
        from vocalinux.ui import settings_dialog

        with TemporaryDirectory() as cache:
            Path(cache, "large.pt").write_bytes(b"checkpoint")

            with patch.object(settings_dialog, "_get_whisper_cache_dir", return_value=cache):
                listed = settings_dialog._list_downloaded_whisper_models()
                self.assertIn("large", listed)
                # Listed is only half of it: deletion resolves the path again.
                self.assertEqual(
                    settings_dialog._whisper_model_files("large"),
                    [os.path.realpath(os.path.join(cache, "large-v3.pt"))],
                )


if __name__ == "__main__":
    unittest.main()

"""
Tests for the custom dictionary transcript corrector.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from vocalinux.speech_recognition.dictionary_corrector import (
    apply_dictionary,
    load_custom_dictionary,
)


def _entry(spoken: str, replacement: str) -> dict:
    """Build a single dictionary entry."""
    return {"spoken": spoken, "replacement": replacement}


class TestApplyDictionary(unittest.TestCase):
    """Test cases for apply_dictionary."""

    def test_basic_phrase_replacement(self):
        """A multi-word misheard phrase is replaced with the intended term."""
        entries = [_entry("super base", "Supabase")]
        self.assertEqual(
            apply_dictionary("I use super base daily", entries), "I use Supabase daily"
        )

    def test_case_insensitive_match(self):
        """Matching is case-insensitive; replacement is inserted as typed."""
        entries = [_entry("super base", "Supabase")]
        self.assertEqual(
            apply_dictionary("I use SUPER BASE daily", entries), "I use Supabase daily"
        )
        self.assertEqual(
            apply_dictionary("I use Super Base daily", entries), "I use Supabase daily"
        )

    def test_no_match_inside_larger_words(self):
        """Word boundaries prevent matching a phrase inside other words."""
        entries = [_entry("base", "basis")]
        self.assertEqual(apply_dictionary("The database is down", entries), "The database is down")

    def test_no_match_without_inner_space(self):
        """A multi-word phrase requires the exact word sequence."""
        entries = [_entry("super base", "Supabase")]
        self.assertEqual(
            apply_dictionary("I use superbase daily", entries), "I use superbase daily"
        )

    def test_match_adjacent_to_punctuation(self):
        """Phrases are matched when touching punctuation."""
        entries = [_entry("super base", "Supabase")]
        self.assertEqual(apply_dictionary("(super base), really.", entries), "(Supabase), really.")

    def test_all_occurrences_replaced(self):
        """Every occurrence in the segment is corrected."""
        entries = [_entry("super base", "Supabase")]
        self.assertEqual(
            apply_dictionary("super base and super base again", entries),
            "Supabase and Supabase again",
        )

    def test_longest_phrase_wins(self):
        """Longer phrases take priority over shorter overlapping ones."""
        entries = [_entry("super", "great"), _entry("super base", "Supabase")]
        self.assertEqual(
            apply_dictionary("super base and super work", entries), "Supabase and great work"
        )

    def test_regex_metacharacters_are_escaped(self):
        """User phrases containing regex metacharacters match literally."""
        entries = [_entry("C++", "C plus plus")]
        self.assertEqual(apply_dictionary("I write C++ code", entries), "I write C plus plus code")
        # The trailing (?!\w) guard still applies after non-word characters
        self.assertEqual(apply_dictionary("I write C++code here", entries), "I write C++code here")

    def test_replacement_keeps_configured_case(self):
        """The replacement is inserted exactly as configured, even lowercase."""
        entries = [_entry("Supabase", "supabase")]
        self.assertEqual(apply_dictionary("SUPABASE rocks", entries), "supabase rocks")

    def test_empty_text_unchanged(self):
        """Empty text is passed through."""
        self.assertEqual(apply_dictionary("", [_entry("a", "b")]), "")

    def test_empty_entries_unchanged(self):
        """No entries means no changes."""
        self.assertEqual(apply_dictionary("super base", []), "super base")

    def test_malformed_entries_ignored(self):
        """Entries with missing or empty fields are skipped."""
        entries = [
            {"spoken": "super base"},  # missing replacement
            {"replacement": "Supabase"},  # missing spoken
            _entry("", "Supabase"),  # empty spoken
            _entry("super base", ""),  # empty replacement
            "not a dict",
            None,
            _entry("next door", "Nextdoor"),  # valid
        ]
        self.assertEqual(
            apply_dictionary("super base near next door", entries), "super base near Nextdoor"
        )

    def test_entries_with_only_invalid_content_unchanged(self):
        """Text is unchanged when every entry is malformed."""
        entries = [{"spoken": "x"}, "garbage"]
        self.assertEqual(apply_dictionary("unchanged text", entries), "unchanged text")


class TestLoadCustomDictionary(unittest.TestCase):
    """Test cases for load_custom_dictionary reading config.json from disk."""

    def setUp(self):
        """Point the corrector's config_dir at a temp directory."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_dir_patcher = patch(
            "vocalinux.speech_recognition.dictionary_corrector.config_dir",
            return_value=self.temp_dir.name,
        )
        self.config_dir_patcher.start()

    def tearDown(self):
        self.config_dir_patcher.stop()
        self.temp_dir.cleanup()

    def _write_config(self, payload) -> None:
        with open(os.path.join(self.temp_dir.name, "config.json"), "w") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f)

    def test_no_config_file_returns_empty(self):
        self.assertEqual(load_custom_dictionary(), [])

    def test_loads_valid_entries(self):
        self._write_config(
            {
                "text_injection": {
                    "custom_dictionary": [
                        {"spoken": "super base", "replacement": "Supabase"},
                        {"spoken": "next door", "replacement": "Nextdoor"},
                    ]
                }
            }
        )
        self.assertEqual(
            load_custom_dictionary(),
            [
                {"spoken": "super base", "replacement": "Supabase"},
                {"spoken": "next door", "replacement": "Nextdoor"},
            ],
        )

    def test_missing_key_returns_empty(self):
        self._write_config({"text_injection": {}})
        self.assertEqual(load_custom_dictionary(), [])

    def test_malformed_entries_dropped(self):
        self._write_config(
            {
                "text_injection": {
                    "custom_dictionary": [
                        {"spoken": "super base", "replacement": "Supabase"},
                        {"spoken": ""},
                        {"replacement": "orphan"},
                        42,
                        {"spoken": "  ", "replacement": "  "},
                    ]
                }
            }
        )
        self.assertEqual(
            load_custom_dictionary(),
            [{"spoken": "super base", "replacement": "Supabase"}],
        )

    def test_non_list_config_returns_empty(self):
        self._write_config({"text_injection": {"custom_dictionary": "nope"}})
        self.assertEqual(load_custom_dictionary(), [])

    def test_invalid_json_returns_empty(self):
        self._write_config("{not valid json")
        self.assertEqual(load_custom_dictionary(), [])


if __name__ == "__main__":
    unittest.main()

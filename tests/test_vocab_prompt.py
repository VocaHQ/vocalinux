"""Tests for the vocabulary biasing prompt builder."""

from vocalinux.speech_recognition.vocab_prompt import (
    MAX_VOCAB_WORDS,
    build_vocab_prompt,
)


class TestBuildVocabPrompt:
    """Test build_vocab_prompt behavior."""

    def test_empty_list_returns_empty_string(self):
        """An empty vocabulary should produce no prompt."""
        assert build_vocab_prompt([]) == ""

    def test_joins_with_comma_space(self):
        """Words are joined into a single comma-separated string."""
        assert build_vocab_prompt(["Cyrille", "Kubernetes"]) == "Cyrille, Kubernetes"

    def test_single_word(self):
        """A single word is returned as-is."""
        assert build_vocab_prompt(["Cyrille"]) == "Cyrille"

    def test_strips_whitespace(self):
        """Surrounding whitespace on entries is removed."""
        assert build_vocab_prompt(["  Cyrille  ", "\tKubernetes\n"]) == "Cyrille, Kubernetes"

    def test_drops_empty_entries(self):
        """Empty and whitespace-only entries are dropped."""
        assert build_vocab_prompt(["", "   ", "Cyrille"]) == "Cyrille"

    def test_dedupes_case_insensitive_keeps_first(self):
        """Case-insensitive duplicates keep the first spelling."""
        assert build_vocab_prompt(["Cyrille", "cyrille", "CYRILLE"]) == "Cyrille"

    def test_caps_at_max_words(self):
        """The prompt never exceeds MAX_VOCAB_WORDS entries."""
        words = [f"word{i}" for i in range(MAX_VOCAB_WORDS + 40)]
        result = build_vocab_prompt(words)
        assert len(result.split(", ")) == MAX_VOCAB_WORDS

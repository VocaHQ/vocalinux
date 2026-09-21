"""Build vocabulary-biasing prompts for whisper-family speech engines.

Whisper-style decoders accept an optional prompt that biases recognition
toward expected vocabulary. This module turns the user's custom word list
into that prompt string, shared by every whisper-family engine.
"""

import logging

logger = logging.getLogger(__name__)

# Whisper prompts are capped at ~224 tokens; 60 words keeps us safely inside.
MAX_VOCAB_WORDS = 60


def build_vocab_prompt(words: list[str]) -> str:
    """Return a comma-separated prompt string from the user's vocabulary.

    Entries are trimmed, deduplicated case-insensitively (first spelling
    wins), and capped at ``MAX_VOCAB_WORDS``. An empty list yields an empty
    string so callers can skip sending a prompt entirely.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for word in words:
        entry = word.strip()
        if not entry or entry.lower() in seen:
            continue
        seen.add(entry.lower())
        cleaned.append(entry)
    if len(cleaned) > MAX_VOCAB_WORDS:
        logger.warning(
            "Custom vocabulary capped from %d to %d entries",
            len(cleaned),
            MAX_VOCAB_WORDS,
        )
        cleaned = cleaned[:MAX_VOCAB_WORDS]
    return ", ".join(cleaned)

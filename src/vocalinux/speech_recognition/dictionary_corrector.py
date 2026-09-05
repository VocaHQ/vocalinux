"""
Custom dictionary post-correction for Vocalinux.

Applies user-configured phrase corrections to the final transcript so that
commonly misheard words are replaced with the intended term, e.g. a
dictionary entry of "super base" -> "Supabase" fixes the transcript even
though the word is not in the speech model's vocabulary.
"""

import json
import logging
import os
import re

from ..utils.paths import config_dir

logger = logging.getLogger(__name__)

CONFIG_SECTION = "text_injection"
CONFIG_KEY = "custom_dictionary"


def load_custom_dictionary() -> list[dict]:
    """Load validated dictionary entries from config.json on disk.

    Reads the file on each call so Settings changes take effect on the next
    transcription segment without a restart (same live-reload pattern as
    ``main._should_append_trailing_space``). Malformed or empty entries are
    dropped; on any read error the dictionary is treated as empty.

    Returns:
        List of ``{"spoken": str, "replacement": str}`` dicts.
    """
    try:
        config_path = os.path.join(config_dir(), "config.json")
        if not os.path.exists(config_path):
            return []
        with open(config_path, "r") as f:
            config = json.load(f)
        raw_entries = config.get(CONFIG_SECTION, {}).get(CONFIG_KEY, []) or []
    except Exception as e:
        logger.debug(f"Could not read {CONFIG_KEY} setting: {e}")
        return []

    if not isinstance(raw_entries, list):
        logger.warning(f"{CONFIG_KEY} config is not a list; ignoring it")
        return []

    entries = []
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            logger.warning(f"Ignoring malformed {CONFIG_KEY} entry {index}: not a dict")
            continue
        spoken = str(entry.get("spoken", "")).strip()
        replacement = str(entry.get("replacement", "")).strip()
        if not spoken or not replacement:
            logger.warning(f"Ignoring malformed {CONFIG_KEY} entry {index}: empty field")
            continue
        entries.append({"spoken": spoken, "replacement": replacement})
    return entries


def apply_dictionary(text: str, entries: list[dict]) -> str:
    """Apply dictionary corrections to a transcript.

    Matching is case-insensitive on whole words/phrases, and the replacement
    is inserted exactly as configured. Longer phrases are matched first so
    "super base" wins over a shorter phrase that shares a word. Lookarounds
    are used instead of ``\\b`` so phrases that start or end with non-word
    characters (e.g. "C++") still match correctly.

    Args:
        text: The transcript text to correct.
        entries: Dictionary entries as returned by ``load_custom_dictionary``.

    Returns:
        The corrected text, or the input unchanged when there is nothing
        to do.
    """
    if not text or not entries:
        return text

    valid_entries = [
        (str(e.get("spoken", "")).strip(), str(e.get("replacement", "")).strip())
        for e in entries
        if isinstance(e, dict)
        and str(e.get("spoken", "")).strip()
        and str(e.get("replacement", "")).strip()
    ]
    if not valid_entries:
        return text

    # Longest first (word count, then length) so multi-word phrases take
    # priority over shorter overlapping ones in the alternation.
    ordered = sorted(
        valid_entries, key=lambda pair: (len(pair[0].split()), len(pair[0])), reverse=True
    )

    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(spoken) for spoken, _ in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )
    corrections = {spoken.lower(): replacement for spoken, replacement in ordered}
    corrected = pattern.sub(lambda m: corrections[m.group(0).lower()], text)

    if corrected != text:
        logger.debug(f"Applied {CONFIG_KEY} corrections: '{text[:60]}' -> '{corrected[:60]}'")
    return corrected

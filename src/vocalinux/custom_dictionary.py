"""File-backed custom dictionary support for recognition bias and transcript fixes."""

import json
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .utils.paths import config_dir

if TYPE_CHECKING:
    from .ui.config_manager import ConfigManager

logger = logging.getLogger(__name__)

TERMS_FILENAME = "custom-dictionary.txt"
CORRECTIONS_FILENAME = "custom-dictionary-corrections.json"
CORRECTIONS_VERSION = 1
DEFAULT_MAX_TERMS = 200
MAX_TERM_CHARACTERS = 200
MAX_PROMPT_CHARACTERS = 2_000
MAX_CORRECTIONS = 500
MAX_CORRECTION_CHARACTERS = 500


def normalize_corrections(raw_entries: Any) -> list[dict[str, str]]:
    """Validate correction entries, retaining the first case-insensitive source.

    Input order is meaningful for equal-length overlapping entries.  Keeping the
    first duplicate makes hand-edited JSON deterministic and agrees with the
    order used when building the matching expression.
    """
    if not isinstance(raw_entries, list):
        return []

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_entries):
        if len(entries) >= MAX_CORRECTIONS:
            logger.warning("Ignoring corrections after the supported limit of %d", MAX_CORRECTIONS)
            break
        if not isinstance(entry, dict):
            logger.warning("Ignoring correction %d: expected an object", index)
            continue
        heard = entry.get("heard")
        replacement = entry.get("replacement")
        if not isinstance(heard, str) or not isinstance(replacement, str):
            logger.warning("Ignoring correction %d: both fields must be strings", index)
            continue
        heard = unicodedata.normalize("NFC", heard.strip())
        replacement = replacement.strip()
        if not heard or not replacement:
            logger.warning("Ignoring correction %d: both fields must be non-empty", index)
            continue
        if len(heard) > MAX_CORRECTION_CHARACTERS or len(replacement) > MAX_CORRECTION_CHARACTERS:
            logger.warning("Ignoring correction %d: phrase is too long", index)
            continue
        normalized_heard = heard.casefold()
        if normalized_heard in seen:
            logger.warning("Ignoring duplicate correction source %r", heard)
            continue
        seen.add(normalized_heard)
        entries.append({"heard": heard, "replacement": replacement})
    return entries


def apply_corrections(text: str, entries: list[dict[str, str]]) -> str:
    """Replace configured phrases in *text* using the custom-dictionary policy.

    Sources are matched case-insensitively only when neither adjacent character
    is a Unicode word character.  Replacements retain the exact user-provided
    spelling.  Longer source phrases take precedence; ties retain JSON order.
    """
    if not text or not entries:
        return text

    normalized_text = unicodedata.normalize("NFC", text)
    ordered = sorted(
        entries,
        key=lambda entry: (len(entry["heard"].split()), len(entry["heard"])),
        reverse=True,
    )
    alternatives = "|".join(
        f"(?P<correction_{index}>{re.escape(entry['heard'])})"
        for index, entry in enumerate(ordered)
    )
    pattern = re.compile(
        r"(?<![\w\u0300-\u036f])(?:" + alternatives + r")(?![\w\u0300-\u036f])",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        """Return the replacement associated with the matched alternative."""
        for index, entry in enumerate(ordered):
            if match.group(f"correction_{index}") is not None:
                return entry["replacement"]
        return match.group(0)

    corrected = pattern.sub(replace, normalized_text)
    if corrected != text:
        logger.debug("Applied custom dictionary corrections to final transcript")
    return corrected


class CustomDictionaryManager:
    """Read, write, and live-reload the two custom dictionary file contracts."""

    def __init__(
        self, config_manager: "ConfigManager", transient_terms_path: Optional[str] = None
    ) -> None:
        self.config = config_manager
        self._transient_terms_path = transient_terms_path

    @property
    def is_transient_terms(self) -> bool:
        """Return whether a CLI session-only terms file supersedes the saved file."""
        return self._transient_terms_path is not None

    def terms_enabled(self) -> bool:
        """Return whether custom terms should be offered to Whisper-family engines."""
        return self.is_transient_terms or bool(
            self.config.get("dictionary", "terms_enabled", False)
        )

    def set_terms_enabled(self, enabled: bool) -> bool:
        """Persist terms enablement, rolling back the in-memory setting on failure."""
        if self.is_transient_terms:
            logger.info("Ignoring saved terms enablement while a CLI override is active")
            return False
        old_value = self.config.get("dictionary", "terms_enabled", False)
        if not self.config.set("dictionary", "terms_enabled", bool(enabled)):
            return False
        if self.config.save_config():
            return True
        self.config.set("dictionary", "terms_enabled", old_value)
        logger.warning("Could not save custom terms enablement; keeping previous setting")
        return False

    def terms_path(self) -> Path:
        """Return the active custom terms path, in the config directory by default."""
        if self._transient_terms_path is not None:
            return Path(self._transient_terms_path).expanduser()
        return Path(config_dir()) / TERMS_FILENAME

    @staticmethod
    def corrections_path() -> Path:
        """Return the fixed structured corrections file path."""
        return Path(config_dir()) / CORRECTIONS_FILENAME

    def get_terms(self) -> list[str]:
        """Read the current UTF-8 line file; external edits apply next segment."""
        try:
            contents = self.terms_path().read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError) as error:
            logger.warning("Could not read custom terms file: %s", error)
            return []

        terms: list[str] = []
        seen: set[str] = set()
        for line in contents.splitlines():
            term = unicodedata.normalize("NFC", line.strip())
            normalized_term = term.casefold()
            if not term or term.startswith("#") or normalized_term in seen:
                continue
            seen.add(normalized_term)
            terms.append(term)
        return terms

    def save_terms(self, terms: list[str]) -> bool:
        """Safely replace the standard terms file with normalized line entries."""
        if self.is_transient_terms:
            logger.info("Ignoring terms edit while a CLI override is active")
            return False
        normalized_terms = self._normalize_terms(terms)
        contents = "\n".join(normalized_terms)
        if contents:
            contents += "\n"
        return self._atomic_write(self.terms_path(), contents)

    def build_initial_prompt(self) -> Optional[str]:
        """Build the current Whisper prompt from enabled terms, if any."""
        if not self.terms_enabled():
            return None
        max_terms = self.config.get("dictionary", "max_terms", DEFAULT_MAX_TERMS)
        try:
            max_terms = max(0, int(max_terms))
        except (TypeError, ValueError):
            logger.warning("Invalid custom terms limit %r; using %d", max_terms, DEFAULT_MAX_TERMS)
            max_terms = DEFAULT_MAX_TERMS
        prompt_terms: list[str] = []
        prompt_characters = 0
        for term in self.get_terms()[:max_terms]:
            additional_characters = len(term) + (1 if prompt_terms else 0)
            if prompt_characters + additional_characters > MAX_PROMPT_CHARACTERS:
                logger.warning("Custom terms prompt reached %d characters", MAX_PROMPT_CHARACTERS)
                break
            prompt_terms.append(term)
            prompt_characters += additional_characters
        return " ".join(prompt_terms) or None

    def get_corrections(self) -> list[dict[str, str]]:
        """Read corrections from JSON for every segment, failing closed on errors."""
        path = self.corrections_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._legacy_corrections()
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            logger.warning("Could not read custom corrections file %s: %s", path, error)
            return []

        if not isinstance(payload, dict) or payload.get("version") != CORRECTIONS_VERSION:
            logger.warning("Ignoring custom corrections file with an unsupported schema")
            return []
        return normalize_corrections(payload.get("corrections"))

    def save_corrections(self, entries: list[dict[str, str]]) -> bool:
        """Safely write validated corrections in the versioned JSON contract."""
        payload = {
            "version": CORRECTIONS_VERSION,
            "corrections": normalize_corrections(entries),
        }
        return self._atomic_write(
            self.corrections_path(), json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    def apply_corrections(self, text: str) -> str:
        """Live-reload and apply corrections to a completed transcript."""
        return apply_corrections(text, self.get_corrections())

    def terms_status(self) -> str:
        """Return a concise, user-facing description of the custom terms file."""
        path = self.terms_path()
        try:
            if not path.exists():
                return "Terms file does not exist yet; add a term to create it."
            if not path.is_file():
                return "Terms path is not a regular file."
            path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            return "Terms file is not valid UTF-8."
        except OSError:
            return "Terms file cannot be inspected."
        return f"{len(self.get_terms())} term(s) available from the live file."

    @staticmethod
    def _normalize_terms(terms: list[str]) -> list[str]:
        """Return trimmed, de-duplicated terms suitable for the line-file contract."""
        normalized: list[str] = []
        seen: set[str] = set()
        for term in terms:
            if not isinstance(term, str):
                continue
            cleaned = unicodedata.normalize("NFC", term.strip())
            if len(cleaned) > MAX_TERM_CHARACTERS:
                logger.warning(
                    "Ignoring custom term longer than %d characters", MAX_TERM_CHARACTERS
                )
                continue
            key = cleaned.casefold()
            if not cleaned or cleaned.startswith("#") or key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
        return normalized

    def _legacy_corrections(self) -> list[dict[str, str]]:
        """Read the never-released #768 config shape without migrating it silently."""
        raw_entries = self.config.get("text_injection", "custom_dictionary", [])
        entries = normalize_corrections(
            [
                {"heard": entry.get("spoken"), "replacement": entry.get("replacement")}
                for entry in raw_entries
                if isinstance(entry, dict)
            ]
        )
        if entries:
            logger.warning("Using legacy config entries until %s is saved", CORRECTIONS_FILENAME)
        return entries

    @staticmethod
    def _atomic_write(path: Path, contents: str) -> bool:
        """Atomically write UTF-8 user data and leave the old file intact on failure."""
        temporary_path: Optional[Path] = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
            with temporary_path.open("x", encoding="utf-8") as temporary_file:
                temporary_file.write(contents)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
            return True
        except OSError as error:
            logger.error("Could not save custom dictionary file %s: %s", path, error)
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.warning("Could not remove temporary dictionary file: %s", cleanup_error)
            return False

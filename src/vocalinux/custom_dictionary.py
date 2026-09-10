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

TERMS_FILENAME = "dictionary.txt"
DEFAULT_TERMS_PATH = str(Path(config_dir()) / TERMS_FILENAME)
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
        return self.is_transient_terms or bool(self.config.get("dictionary", "enabled", False))

    def set_terms_enabled(self, enabled: bool) -> bool:
        """Persist terms enablement, rolling back the in-memory setting on failure."""
        if self.is_transient_terms:
            logger.info("Ignoring saved terms enablement while a CLI override is active")
            return False
        old_value = self.config.get("dictionary", "enabled", False)
        if not self.config.set("dictionary", "enabled", bool(enabled)):
            return False
        if self.config.save_config():
            return True
        self.config.set("dictionary", "enabled", old_value)
        logger.warning("Could not save custom terms enablement; keeping previous setting")
        return False

    def terms_path_text(self) -> str:
        """Return the configured or session-only terms path without expansion."""
        if self._transient_terms_path is not None:
            return self._transient_terms_path
        default_path = str(Path(config_dir()) / TERMS_FILENAME)
        configured = self.config.get("dictionary", "file_path", default_path)
        if not isinstance(configured, str) or not configured.strip():
            return default_path
        return configured.strip()

    def terms_path(self) -> Optional[Path]:
        """Return the active expanded terms path, or None when it is invalid."""
        configured = self.terms_path_text()
        try:
            return Path(configured).expanduser()
        except RuntimeError as error:
            logger.warning("Could not expand custom terms path %r: %s", configured, error)
            return None

    def set_terms_path(self, path: str) -> bool:
        """Persist a usable terms path, retaining the prior setting on save failure."""
        if self.is_transient_terms:
            logger.info("Ignoring terms path change while a CLI override is active")
            return False
        if not isinstance(path, str) or not path.strip():
            logger.warning("Ignoring empty custom terms path")
            return False
        configured = path.strip()
        try:
            candidate = Path(configured).expanduser()
            if candidate.exists() and (not candidate.is_file() or not self._is_readable(candidate)):
                logger.warning("Ignoring unusable custom terms path %s", candidate)
                return False
        except (OSError, RuntimeError) as error:
            logger.warning("Ignoring invalid custom terms path %r: %s", configured, error)
            return False

        old_value = self.config.get(
            "dictionary", "file_path", str(Path(config_dir()) / TERMS_FILENAME)
        )
        if not self.config.set("dictionary", "file_path", configured):
            return False
        if self.config.save_config():
            return True
        self.config.set("dictionary", "file_path", old_value)
        logger.warning("Could not save custom terms path; keeping previous setting")
        return False

    @staticmethod
    def corrections_path() -> Path:
        """Return the fixed structured corrections file path."""
        return Path(config_dir()) / CORRECTIONS_FILENAME

    def get_terms(self) -> list[str]:
        """Read the current UTF-8 line file; external edits apply next segment."""
        path = self.terms_path()
        if path is None:
            return []
        try:
            contents = path.read_text(encoding="utf-8-sig")
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
        path = self.terms_path()
        if path is None:
            logger.warning("Cannot save custom terms because the configured path is invalid")
            return False
        normalized_terms = self._normalize_terms(terms)
        contents = "\n".join(normalized_terms)
        if contents:
            contents += "\n"
        return self._atomic_write(path, contents)

    def add_term(self, term: str) -> bool:
        """Append one valid term without rewriting comments or blank lines."""
        if self.is_transient_terms:
            logger.info("Ignoring terms edit while a CLI override is active")
            return False
        cleaned = self._single_term(term)
        if cleaned is None:
            return False
        path = self.terms_path()
        if path is None:
            logger.warning("Cannot add custom term because the configured path is invalid")
            return False
        contents = self._read_terms_contents(path, missing_value="")
        if contents is None:
            return False
        if any(existing.casefold() == cleaned.casefold() for existing in self.get_terms()):
            logger.warning("Ignoring duplicate custom term %r", cleaned)
            return False
        separator = "" if not contents or contents.endswith(("\n", "\r")) else "\n"
        return self._atomic_write(path, f"{contents}{separator}{cleaned}\n")

    def remove_term(self, term: str) -> bool:
        """Remove matching term lines without changing unrelated file content."""
        if self.is_transient_terms:
            logger.info("Ignoring terms edit while a CLI override is active")
            return False
        cleaned = self._single_term(term)
        if cleaned is None:
            return False
        path = self.terms_path()
        if path is None:
            logger.warning("Cannot remove custom term because the configured path is invalid")
            return False
        contents = self._read_terms_contents(path)
        if contents is None:
            return False

        remaining_lines: list[str] = []
        removed = False
        for line in contents.splitlines(keepends=True):
            line_term = unicodedata.normalize("NFC", line.rstrip("\r\n").strip())
            if not line_term.startswith("#") and line_term.casefold() == cleaned.casefold():
                removed = True
                continue
            remaining_lines.append(line)
        if not removed:
            logger.warning("Custom term %r was not present in the terms file", cleaned)
            return False
        return self._atomic_write(path, "".join(remaining_lines))

    def build_initial_prompt(self) -> Optional[str]:
        """Build the current Whisper prompt from enabled terms, if any."""
        if not self.terms_enabled():
            return None
        max_terms = self.config.get("dictionary", "max_words", DEFAULT_MAX_TERMS)
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
        entries = self._read_corrections(for_edit=False)
        return entries if entries is not None else []

    def get_corrections_for_edit(self) -> Optional[list[dict[str, str]]]:
        """Return losslessly editable entries, or None for an unsafe source file.

        Runtime correction reads may safely ignore malformed individual entries,
        but a UI edit must never rewrite the file from that filtered view.
        """
        return self._read_corrections(for_edit=True)

    def _read_corrections(self, *, for_edit: bool) -> Optional[list[dict[str, str]]]:
        """Read corrections with stricter validation for write-back workflows."""
        path = self.corrections_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._legacy_corrections()
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            logger.warning("Could not read custom corrections file %s: %s", path, error)
            return None if for_edit else []

        if not isinstance(payload, dict) or payload.get("version") != CORRECTIONS_VERSION:
            logger.warning("Ignoring custom corrections file with an unsupported schema")
            return None if for_edit else []

        raw_entries = payload.get("corrections")
        entries = normalize_corrections(raw_entries)
        if for_edit and (not isinstance(raw_entries, list) or len(entries) != len(raw_entries)):
            logger.warning(
                "Refusing to edit custom corrections because some source entries are invalid"
            )
            return None
        return entries

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
        if path is None:
            return "Configured terms path is invalid or cannot be expanded."
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
    def _is_readable(path: Path) -> bool:
        """Return whether a path can be opened for reading."""
        try:
            with path.open("r", encoding="utf-8"):
                return True
        except OSError:
            return False

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

    @staticmethod
    def _single_term(term: str) -> Optional[str]:
        """Validate a single line-file term for an incremental edit."""
        if not isinstance(term, str) or "\n" in term or "\r" in term:
            logger.warning("Ignoring invalid custom term")
            return None
        normalized = CustomDictionaryManager._normalize_terms([term])
        return normalized[0] if normalized else None

    @staticmethod
    def _read_terms_contents(path: Path, missing_value: Optional[str] = None) -> Optional[str]:
        """Read terms text for an edit while reporting invalid source files safely."""
        try:
            return path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return missing_value
        except (OSError, UnicodeError) as error:
            logger.warning("Could not read custom terms file %s: %s", path, error)
            return None

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

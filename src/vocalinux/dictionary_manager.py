"""Custom dictionary support for Whisper-family recognition engines."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .ui.config_manager import ConfigManager

logger = logging.getLogger(__name__)

DEFAULT_DICTIONARY_FILE = "~/.config/vocalinux/dictionary.txt"
DEFAULT_MAX_WORDS = 200


class DictionaryManager:
    """Read the user dictionary and build a prompt for each transcription.

    The file format is UTF-8, one term per line. Empty lines and lines beginning
    with ``#`` are ignored. The file is read for every prompt build so external
    edits take effect on the next transcription without restarting Vocalinux.
    """

    def __init__(
        self, config_manager: "ConfigManager", transient_path: Optional[str] = None
    ) -> None:
        self.config = config_manager
        self._transient_path = transient_path

    def is_enabled(self) -> bool:
        """Return whether custom dictionary support is enabled."""
        return self._transient_path is not None or bool(
            self.config.get("dictionary", "enabled", False)
        )

    @property
    def is_transient(self) -> bool:
        """Return whether this manager was created by the CLI session override."""
        return self._transient_path is not None

    def set_enabled(self, enabled: bool) -> None:
        """Persist the enabled state."""
        if self._transient_path is None:
            self.config.set("dictionary", "enabled", bool(enabled))
            self.config.save_config()

    def get_path(self) -> Optional[Path]:
        """Return a safely expanded dictionary path, or ``None`` when invalid."""
        configured = self._transient_path
        if configured is None:
            configured = self.config.get("dictionary", "file_path", DEFAULT_DICTIONARY_FILE)
        if not isinstance(configured, str) or not configured.strip():
            configured = DEFAULT_DICTIONARY_FILE
        try:
            return Path(configured).expanduser()
        except RuntimeError as error:
            logger.warning("Could not expand custom dictionary path %r: %s", configured, error)
            return None

    def set_path(self, path: str) -> bool:
        """Persist a non-empty dictionary path, returning whether it was accepted."""
        if self._transient_path is not None:
            logger.info("Ignoring dictionary path change while a session-only override is active")
            return False
        if not isinstance(path, str) or not path.strip():
            logger.warning("Ignoring empty custom dictionary path")
            return False
        try:
            candidate = Path(path.strip()).expanduser()
            if candidate.exists() and (not candidate.is_file() or not self._is_readable(candidate)):
                logger.warning("Ignoring unusable custom dictionary path %s", candidate)
                return False
        except (OSError, RuntimeError) as error:
            logger.warning("Ignoring invalid custom dictionary path %r: %s", path, error)
            return False
        self.config.set("dictionary", "file_path", path.strip())
        self.config.save_config()
        return True

    def get_words(self) -> list[str]:
        """Read and return the current terms from the configured dictionary file."""
        path = self.get_path()
        if path is None:
            return []
        try:
            contents = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return []
        except OSError as error:
            logger.warning("Could not read custom dictionary %s: %s", path, error)
            return []

        words: list[str] = []
        seen: set[str] = set()
        for line in contents.splitlines():
            term = line.strip()
            if not term or term.startswith("#") or term in seen:
                continue
            seen.add(term)
            words.append(term)
        return words

    def get_status(self) -> str:
        """Return a safe, user-facing description of the dictionary file state."""
        path = self.get_path()
        if path is None:
            return "Dictionary path is invalid or cannot be expanded."
        try:
            if not path.exists():
                return "Dictionary file does not exist yet; it will be used when created."
            if not path.is_file() or not self._is_readable(path):
                return "Dictionary path is not a readable file."
        except OSError:
            return "Dictionary path cannot be inspected."
        try:
            return f"{len(self.get_words())} term(s) available from the live file."
        except UnicodeDecodeError:
            return "Dictionary file is not valid UTF-8."

    @staticmethod
    def _is_readable(path: Path) -> bool:
        """Return whether *path* can be opened for reading without leaking errors."""
        try:
            with path.open("r", encoding="utf-8"):
                return True
        except OSError:
            return False

    def build_initial_prompt(self) -> Optional[str]:
        """Build a live dictionary prompt, or return ``None`` when unavailable."""
        if not self.is_enabled():
            return None
        max_words = self.config.get("dictionary", "max_words", DEFAULT_MAX_WORDS)
        try:
            max_words = max(0, int(max_words))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid dictionary max_words value %r; using %d", max_words, DEFAULT_MAX_WORDS
            )
            max_words = DEFAULT_MAX_WORDS
        words = self.get_words()[:max_words]
        return " ".join(words) if words else None

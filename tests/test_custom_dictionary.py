"""Tests for the file-backed custom dictionary contract."""

import json
import threading
from pathlib import Path
from typing import Any

from vocalinux.custom_dictionary import (
    CORRECTIONS_FILENAME,
    DEFAULT_TERMS_PATH,
    TERMS_FILENAME,
    CustomDictionaryManager,
    apply_corrections,
    normalize_corrections,
)
from vocalinux.main import parse_arguments
from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager


class FakeConfig:
    """Minimal ConfigManager substitute with controllable persistence."""

    def __init__(self, values: dict[str, dict[str, Any]] | None = None, save_result: bool = True):
        self.values = values or {
            "dictionary": {
                "enabled": False,
                "file_path": DEFAULT_TERMS_PATH,
                "max_words": 200,
            }
        }
        self.save_result = save_result

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Return one configured value."""
        return self.values.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> bool:
        """Set one configured value."""
        self.values.setdefault(section, {})[key] = value
        return True

    def save_config(self) -> bool:
        """Return the requested persistence result."""
        return self.save_result


def manager_at(
    tmp_path: Path, monkeypatch, config: FakeConfig | None = None
) -> CustomDictionaryManager:
    """Create a manager whose configured files live in pytest's temp directory."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    config = config or FakeConfig()
    dictionary = config.values.setdefault("dictionary", {})
    if dictionary.get("file_path") in (None, DEFAULT_TERMS_PATH):
        dictionary["file_path"] = str(tmp_path / TERMS_FILENAME)
    return CustomDictionaryManager(config)


def test_terms_are_live_reloaded_and_scanner_friendly(tmp_path: Path, monkeypatch) -> None:
    """The UTF-8 line file accepts comments and applies an external replacement."""
    manager = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    terms_file = tmp_path / TERMS_FILENAME
    terms_file.write_text("# scanner comment\nVocaLinux\nvocalinux\nSupabase\n", encoding="utf-8")

    assert manager.get_terms() == ["VocaLinux", "Supabase"]
    assert manager.build_initial_prompt() == "VocaLinux Supabase"

    terms_file.write_text("PyGObject\n", encoding="utf-8")
    assert manager.build_initial_prompt() == "PyGObject"


def test_terms_save_is_atomic_shape_and_transient_override_is_not_written(
    tmp_path: Path, monkeypatch
) -> None:
    """UI saves standard terms safely while CLI terms remain session-only."""
    manager = manager_at(tmp_path, monkeypatch)
    assert manager.save_terms(["VocaLinux", "vocalinux", "# ignored", "  PyGObject  "])
    assert (tmp_path / TERMS_FILENAME).read_text(encoding="utf-8") == "VocaLinux\nPyGObject\n"

    override = tmp_path / "override.txt"
    override.write_text("Override\n", encoding="utf-8")
    transient = CustomDictionaryManager(FakeConfig(), str(override))
    assert transient.terms_enabled()
    assert transient.get_terms() == ["Override"]
    assert not transient.save_terms(["No write"])


def test_enable_rollback_when_config_persistence_fails(tmp_path: Path, monkeypatch) -> None:
    """A failed config save preserves the previous in-memory setting."""
    config = FakeConfig(save_result=False)
    manager = manager_at(tmp_path, monkeypatch, config)

    assert not manager.set_terms_enabled(True)
    assert not manager.terms_enabled()


def test_pr_767_dictionary_configuration_keys_and_contract_are_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    """Existing enabled, file_path, and max_words settings remain effective."""
    configured_path = tmp_path / TERMS_FILENAME
    configured_path.write_text("VocaLinux\nPyGObject\n", encoding="utf-8")
    config = FakeConfig(
        {
            "dictionary": {
                "enabled": True,
                "file_path": str(configured_path),
                "max_words": 1,
            }
        }
    )
    manager = manager_at(tmp_path, monkeypatch, config)

    assert TERMS_FILENAME == "dictionary.txt"
    assert DEFAULT_TERMS_PATH == "~/.config/vocalinux/dictionary.txt"
    assert CustomDictionaryManager(FakeConfig()).terms_path_text() == DEFAULT_TERMS_PATH
    assert manager.terms_enabled()
    assert manager.terms_path() == configured_path
    assert manager.build_initial_prompt() == "VocaLinux"


def test_invalid_or_unreadable_configured_terms_path_is_not_persisted(
    tmp_path: Path, monkeypatch
) -> None:
    """Invalid paths are harmless and leave the previous configured path intact."""
    previous_path = str(tmp_path / TERMS_FILENAME)
    config = FakeConfig({"dictionary": {"file_path": previous_path}})
    manager = manager_at(tmp_path, monkeypatch, config)

    assert not manager.set_terms_path("~vocalinux-user-does-not-exist/dictionary.txt")
    assert config.get("dictionary", "file_path") == previous_path

    assert not manager.set_terms_path(str(tmp_path))
    assert config.get("dictionary", "file_path") == previous_path


def test_invalid_saved_terms_path_is_safe_to_read_and_report(tmp_path: Path, monkeypatch) -> None:
    """A pre-existing unresolved path cannot crash recognition or Settings."""
    config = FakeConfig(
        {
            "dictionary": {
                "enabled": True,
                "file_path": "~vocalinux-user-does-not-exist/dictionary.txt",
            }
        }
    )
    manager = manager_at(tmp_path, monkeypatch, config)

    assert manager.terms_path() is None
    assert manager.get_terms() == []
    assert manager.build_initial_prompt() is None
    assert manager.terms_status() == "Configured terms path is invalid or cannot be expanded."


def test_terms_path_save_failure_preserves_the_previous_configured_path(
    tmp_path: Path, monkeypatch
) -> None:
    """A failed config save never claims a new path persisted."""
    previous_path = str(tmp_path / TERMS_FILENAME)
    config = FakeConfig({"dictionary": {"file_path": previous_path}}, save_result=False)
    manager = manager_at(tmp_path, monkeypatch, config)

    assert not manager.set_terms_path(str(tmp_path / "new-terms.txt"))
    assert config.get("dictionary", "file_path") == previous_path


def test_invalid_transient_terms_path_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    """An unresolved CLI tilde path disables only its session's terms safely."""
    manager_at(tmp_path, monkeypatch)
    manager = CustomDictionaryManager(FakeConfig(), "~vocalinux-user-does-not-exist/dictionary.txt")

    assert manager.terms_enabled()
    assert manager.terms_path() is None
    assert manager.get_terms() == []
    assert manager.terms_status() == "Configured terms path is invalid or cannot be expanded."


def test_atomic_save_failure_preserves_existing_terms_file(tmp_path: Path, monkeypatch) -> None:
    """A failed replacement leaves the scanner-visible file intact."""
    manager = manager_at(tmp_path, monkeypatch)
    terms_file = tmp_path / TERMS_FILENAME
    terms_file.write_text("Existing\n", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        """Simulate a filesystem failure during atomic replacement."""
        raise OSError("disk full")

    monkeypatch.setattr("vocalinux.custom_dictionary.os.replace", fail_replace)

    assert not manager.save_terms(["New"])
    assert terms_file.read_text(encoding="utf-8") == "Existing\n"


def test_dictionary_file_argument_is_available_for_a_session_override(monkeypatch) -> None:
    """The retained CLI option accepts a terms file without changing config."""
    monkeypatch.setattr("sys.argv", ["vocalinux", "--dictionary-file", "/tmp/terms.txt"])

    assert parse_arguments().dictionary_file == "/tmp/terms.txt"


def test_corrections_use_versioned_json_and_live_reload(tmp_path: Path, monkeypatch) -> None:
    """Structured corrections use exact replacement spelling on every read."""
    manager = manager_at(tmp_path, monkeypatch)
    assert manager.save_corrections([{"heard": "super base", "replacement": "Supabase"}])
    stored = json.loads((tmp_path / CORRECTIONS_FILENAME).read_text(encoding="utf-8"))
    assert stored == {
        "version": 1,
        "corrections": [{"heard": "super base", "replacement": "Supabase"}],
    }
    assert manager.apply_corrections("super base is useful") == "Supabase is useful"

    assert manager.save_corrections([{"heard": "pie object", "replacement": "PyGObject"}])
    assert manager.apply_corrections("pie object") == "PyGObject"


def test_corrections_are_literal_longest_first_and_unicode_safe() -> None:
    """Matching is whole-phrase, case-insensitive, and never maps through lower()."""
    entries = normalize_corrections(
        [
            {"heard": "super", "replacement": "short"},
            {"heard": "super base", "replacement": "Supabase"},
            {"heard": "C++", "replacement": "C plus plus"},
            {"heard": "i", "replacement": "letter"},
        ]
    )

    assert apply_corrections("SUPER BASE and super", entries) == "Supabase and short"
    assert apply_corrections("C++ is not C++foo", entries) == "C plus plus is not C++foo"
    assert apply_corrections("İ", entries) == "letter"
    assert apply_corrections("e\u0301clair", [{"heard": "e", "replacement": "E"}]) == "éclair"


def test_invalid_corrections_file_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """Malformed JSON never aborts a segment or invents replacements."""
    manager = manager_at(tmp_path, monkeypatch)
    (tmp_path / CORRECTIONS_FILENAME).write_text("{not json", encoding="utf-8")

    assert manager.get_corrections() == []
    assert manager.apply_corrections("super base") == "super base"


def test_invalid_terms_file_is_ignored_and_explained(tmp_path: Path, monkeypatch) -> None:
    """An invalid scanner file leaves prompt bias empty with a clear status."""
    manager = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    (tmp_path / TERMS_FILENAME).write_bytes(b"\xff\xfe")

    assert manager.build_initial_prompt() is None
    assert manager.terms_status() == "Terms file is not valid UTF-8."


def test_whispercpp_prompt_composes_advanced_and_terms() -> None:
    """Advanced prompt remains a prefix and an emptied terms file clears the value."""
    recognition_manager = object.__new__(SpeechRecognitionManager)
    recognition_manager.whispercpp_initial_prompt = "Write product names accurately."
    recognition_manager.dictionary_manager = type(
        "Dictionary", (), {"build_initial_prompt": lambda self: "VocaLinux"}
    )()

    assert (
        recognition_manager._get_whispercpp_prompt() == "Write product names accurately. VocaLinux"
    )
    recognition_manager.dictionary_manager = type(
        "Dictionary", (), {"build_initial_prompt": lambda self: None}
    )()
    assert recognition_manager._get_whispercpp_prompt() == "Write product names accurately."


def test_corrections_run_before_voice_commands() -> None:
    """A correction changes raw text before the command processor can act on it."""

    class Recognizer:
        """Minimal VOSK recognizer."""

        def AcceptWaveform(self, data: bytes) -> None:
            """Accept a fake audio chunk."""

        def FinalResult(self) -> str:
            """Return the raw model text."""
            return '{"text": "delete that"}'

    recognition_manager = object.__new__(SpeechRecognitionManager)
    recognition_manager.engine = "vosk"
    recognition_manager.recognizer = Recognizer()
    recognition_manager._model_lock = threading.Lock()
    recognition_manager._voice_commands_enabled = True
    recognition_manager.dictionary_manager = type(
        "Dictionary", (), {"apply_corrections": lambda self, text: "delete note"}
    )()
    received: list[str] = []
    recognition_manager.command_processor = type(
        "Commands", (), {"process_text": lambda self, text: (text, [])}
    )()
    recognition_manager.text_callbacks = [received.append]
    recognition_manager.action_callbacks = []

    recognition_manager._process_audio_buffer([b"audio"])

    assert received == ["delete note"]

"""Tests for the file-backed custom dictionary contract."""

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from vocalinux.custom_dictionary import (
    CORRECTIONS_FILENAME,
    DEFAULT_TERMS_PATH,
    LEGACY_DEFAULT_TERMS_PATH,
    MAX_CORRECTION_CHARACTERS,
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


def recognition_manager(
    engine: str, dictionary: CustomDictionaryManager, advanced_prompt: str = ""
) -> SpeechRecognitionManager:
    """Build a recognition manager without loading a real speech model."""
    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                return SpeechRecognitionManager(
                    engine=engine,
                    dictionary_manager=dictionary,
                    whispercpp_initial_prompt=advanced_prompt,
                )


def mock_numpy() -> MagicMock:
    """Return the minimum NumPy surface used by transcription helpers."""
    numpy = MagicMock()
    numpy.frombuffer.return_value = MagicMock(__len__=lambda _: 16_000)
    numpy.frombuffer.return_value.astype.return_value = numpy.frombuffer.return_value
    numpy.int16 = "int16"
    numpy.float32 = "float32"
    return numpy


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


def test_incremental_term_edits_preserve_comments_and_blank_lines(
    tmp_path: Path, monkeypatch
) -> None:
    """GTK add/remove operations retain unrelated scanner-managed source lines."""
    manager = manager_at(tmp_path, monkeypatch)
    terms_file = tmp_path / TERMS_FILENAME
    terms_file.write_text("# scanner note\n\nVocaLinux\n# retain me\nPyGObject\n", encoding="utf-8")

    assert manager.add_term("Supabase")
    assert terms_file.read_text(encoding="utf-8") == (
        "# scanner note\n\nVocaLinux\n# retain me\nPyGObject\nSupabase\n"
    )
    assert manager.remove_term("PyGObject")
    assert terms_file.read_text(encoding="utf-8") == (
        "# scanner note\n\nVocaLinux\n# retain me\nSupabase\n"
    )


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
    assert Path(DEFAULT_TERMS_PATH).name == TERMS_FILENAME
    assert manager.terms_enabled()
    assert manager.terms_path() == configured_path
    assert manager.build_initial_prompt() == "VocaLinux"


def test_default_terms_path_follows_xdg_config_home(tmp_path: Path, monkeypatch) -> None:
    """A missing saved path uses the same XDG-aware root as corrections."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    manager = CustomDictionaryManager(FakeConfig({"dictionary": {}}))

    assert manager.terms_path() == tmp_path / TERMS_FILENAME
    assert manager.corrections_path() == tmp_path / CORRECTIONS_FILENAME


def test_legacy_vocalinux_terms_root_colocates_corrections(tmp_path: Path, monkeypatch) -> None:
    """Persisted ~/.config/vocalinux terms keep corrections beside that root."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    legacy_corrections = Path.home() / ".config" / "vocalinux" / CORRECTIONS_FILENAME
    expanded_legacy = str(Path.home() / ".config" / "vocalinux" / TERMS_FILENAME)
    assert legacy_corrections != tmp_path / CORRECTIONS_FILENAME

    tilde_manager = CustomDictionaryManager(
        FakeConfig({"dictionary": {"file_path": LEGACY_DEFAULT_TERMS_PATH}})
    )
    assert tilde_manager.corrections_path() == legacy_corrections
    assert tilde_manager.corrections_path() != tmp_path / CORRECTIONS_FILENAME

    expanded_manager = CustomDictionaryManager(
        FakeConfig({"dictionary": {"file_path": expanded_legacy}})
    )
    assert expanded_manager.corrections_path() == legacy_corrections
    assert expanded_manager.corrections_path() != tmp_path / CORRECTIONS_FILENAME


def test_explicit_legacy_terms_path_colocates_corrections_away_from_xdg(
    tmp_path: Path, monkeypatch
) -> None:
    """An explicit leftover pre-XDG terms path keeps corrections as siblings."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    legacy_root = Path.home() / ".config" / "vocalinux"
    legacy_corrections = legacy_root / CORRECTIONS_FILENAME
    expanded_legacy = str(legacy_root / TERMS_FILENAME)
    assert legacy_corrections != tmp_path / CORRECTIONS_FILENAME

    tilde_manager = CustomDictionaryManager(
        FakeConfig(
            {
                "dictionary": {
                    "file_path": LEGACY_DEFAULT_TERMS_PATH,
                    "file_path_explicit": True,
                }
            }
        )
    )
    assert tilde_manager.corrections_path() == legacy_corrections
    assert tilde_manager.corrections_path() != tmp_path / CORRECTIONS_FILENAME

    stamped = FakeConfig({"dictionary": {"file_path": expanded_legacy}})
    stamped_manager = CustomDictionaryManager(stamped)
    stamped_manager.terms_path_text()
    assert stamped.get("dictionary", "file_path_explicit") is True
    assert stamped_manager.corrections_path() == legacy_corrections
    assert stamped_manager.corrections_path() != tmp_path / CORRECTIONS_FILENAME


def test_corrections_fall_back_from_config_dir_when_primary_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Leftover config_dir corrections are read and copied beside legacy terms."""
    fake_home = tmp_path / "home"
    xdg_dir = tmp_path / "xdg-config"
    legacy_root = fake_home / ".config" / "vocalinux"
    legacy_root.mkdir(parents=True)
    xdg_dir.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(xdg_dir))

    old_path = xdg_dir / CORRECTIONS_FILENAME
    payload = {
        "version": 1,
        "corrections": [{"heard": "super base", "replacement": "Supabase"}],
    }
    old_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    manager = CustomDictionaryManager(
        FakeConfig(
            {
                "dictionary": {
                    "file_path": LEGACY_DEFAULT_TERMS_PATH,
                    "file_path_explicit": True,
                }
            }
        )
    )
    primary = Path(LEGACY_DEFAULT_TERMS_PATH).expanduser().parent / CORRECTIONS_FILENAME
    assert manager.corrections_path() == primary
    assert primary != old_path
    assert not primary.exists()
    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert primary.is_file()
    old_path.unlink()
    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]


def test_corrections_fallback_survives_copy_failure(tmp_path: Path, monkeypatch) -> None:
    """A failed copy-once still returns leftover config_dir corrections."""
    terms_root = tmp_path / "legacy-root"
    xdg_dir = tmp_path / "xdg-config"
    terms_root.mkdir()
    xdg_dir.mkdir()
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(xdg_dir))
    old_path = xdg_dir / CORRECTIONS_FILENAME
    payload = {
        "version": 1,
        "corrections": [{"heard": "super base", "replacement": "Supabase"}],
    }
    old_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    manager = CustomDictionaryManager(
        FakeConfig(
            {
                "dictionary": {
                    "file_path": str(terms_root / TERMS_FILENAME),
                    "file_path_explicit": True,
                }
            }
        )
    )
    primary = terms_root / CORRECTIONS_FILENAME

    def fail_replace(source: Path, destination: Path) -> None:
        """Simulate a filesystem failure during atomic replacement."""
        raise OSError("disk full")

    monkeypatch.setattr("vocalinux.custom_dictionary.os.replace", fail_replace)

    assert manager.corrections_path() == primary
    assert not primary.exists()
    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert not primary.exists()


def test_corrections_colocated_with_arbitrary_terms_parent(tmp_path: Path, monkeypatch) -> None:
    """Corrections follow the terms file even outside a vocalinux directory."""
    xdg_dir = tmp_path / "xdg-config"
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(xdg_dir))
    terms = tmp_path / "my-terms.txt"
    manager = CustomDictionaryManager(
        FakeConfig(
            {
                "dictionary": {
                    "file_path": str(terms),
                    "file_path_explicit": True,
                }
            }
        )
    )
    assert manager.corrections_path() == tmp_path / CORRECTIONS_FILENAME
    assert manager.corrections_path() != xdg_dir / CORRECTIONS_FILENAME


def test_historical_legacy_looking_path_without_explicit_marker_is_not_migrated(
    tmp_path: Path, monkeypatch
) -> None:
    """A leftover pre-XDG path stays put when XDG_CONFIG_HOME points elsewhere."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    xdg_path = str(tmp_path / TERMS_FILENAME)
    tilde_path = LEGACY_DEFAULT_TERMS_PATH
    expanded_legacy = str(Path.home() / ".config" / "vocalinux" / TERMS_FILENAME)
    assert expanded_legacy != xdg_path

    config = FakeConfig({"dictionary": {"file_path": tilde_path}})
    manager = CustomDictionaryManager(config)

    assert manager.terms_path_text() == tilde_path
    assert manager.terms_path() == Path(tilde_path).expanduser()
    assert config.get("dictionary", "file_path") == tilde_path
    assert config.get("dictionary", "file_path") != xdg_path
    assert config.get("dictionary", "file_path_explicit") is True

    failing = FakeConfig(
        {"dictionary": {"file_path": tilde_path}},
        save_result=False,
    )
    failing_manager = CustomDictionaryManager(failing)
    assert failing_manager.terms_path_text() == tilde_path
    assert failing.get("dictionary", "file_path") == tilde_path
    assert failing.get("dictionary", "file_path") != xdg_path
    assert not failing.get("dictionary", "file_path_explicit", False)

    expanded_config = FakeConfig({"dictionary": {"file_path": expanded_legacy}})
    expanded_manager = CustomDictionaryManager(expanded_config)
    assert expanded_manager.terms_path_text() == expanded_legacy
    assert expanded_config.get("dictionary", "file_path") == expanded_legacy
    assert expanded_config.get("dictionary", "file_path") != xdg_path
    assert expanded_config.get("dictionary", "file_path_explicit") is True

    custom = str(tmp_path / "custom-terms.txt")
    custom_config = FakeConfig({"dictionary": {"file_path": custom}})
    custom_manager = CustomDictionaryManager(custom_config)
    assert custom_manager.terms_path_text() == custom
    assert custom_config.get("dictionary", "file_path") == custom


def test_explicit_legacy_terms_path_is_not_migrated(tmp_path: Path, monkeypatch) -> None:
    """set_terms_path of the pre-XDG string is kept when XDG points elsewhere."""
    monkeypatch.setattr("vocalinux.custom_dictionary.config_dir", lambda: str(tmp_path))
    xdg_path = str(tmp_path / TERMS_FILENAME)
    expanded_legacy = str(Path.home() / ".config" / "vocalinux" / TERMS_FILENAME)
    assert expanded_legacy != xdg_path

    tilde_config = FakeConfig({"dictionary": {"file_path": xdg_path}})
    tilde_manager = CustomDictionaryManager(tilde_config)
    assert tilde_manager.set_terms_path(LEGACY_DEFAULT_TERMS_PATH)
    assert tilde_config.get("dictionary", "file_path") == LEGACY_DEFAULT_TERMS_PATH
    assert tilde_config.get("dictionary", "file_path_explicit") is True
    assert tilde_manager.terms_path_text() == LEGACY_DEFAULT_TERMS_PATH
    assert tilde_config.get("dictionary", "file_path") == LEGACY_DEFAULT_TERMS_PATH

    expanded_config = FakeConfig({"dictionary": {"file_path": xdg_path}})
    expanded_manager = CustomDictionaryManager(expanded_config)
    assert expanded_manager.set_terms_path(expanded_legacy)
    assert expanded_config.get("dictionary", "file_path") == expanded_legacy
    assert expanded_config.get("dictionary", "file_path_explicit") is True
    assert expanded_manager.terms_path_text() == expanded_legacy
    assert expanded_config.get("dictionary", "file_path") == expanded_legacy


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
    assert not config.get("dictionary", "file_path_explicit", False)


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
    assert manager.get_corrections_for_edit() == [
        {"heard": "super base", "replacement": "Supabase"}
    ]
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
    assert manager.get_corrections_for_edit() is None
    assert manager.apply_corrections("super base") == "super base"


def test_partially_invalid_corrections_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """UI write-back is refused when runtime reads had to filter source entries."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    original = {
        "version": 1,
        "corrections": [
            {"heard": "super base", "replacement": "Supabase"},
            {"heard": "missing replacement"},
        ],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert manager.get_corrections_for_edit() is None
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrections_with_extra_fields_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """Unknown fields still apply at runtime but block a UI rewrite that would drop them."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    original = {
        "version": 1,
        "corrections": [
            {
                "heard": "super base",
                "replacement": "Supabase",
                "note": "scanner annotation",
            }
        ],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert manager.apply_corrections("super base is useful") == "Supabase is useful"
    assert manager.get_corrections_for_edit() is None
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrections_with_top_level_metadata_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """Unknown top-level keys apply at runtime but block a UI rewrite that would drop them."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    original = {
        "version": 1,
        "metadata": {"author": "scanner"},
        "corrections": [{"heard": "super base", "replacement": "Supabase"}],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert manager.apply_corrections("super base is useful") == "Supabase is useful"
    assert manager.get_corrections_for_edit() is None
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrections_with_whitespace_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """Leading or trailing whitespace still applies at runtime but blocks a UI rewrite."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    original = {
        "version": 1,
        "corrections": [{"heard": "  super base  ", "replacement": " Supabase "}],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    assert manager.get_corrections() == [{"heard": "super base", "replacement": "Supabase"}]
    assert manager.apply_corrections("super base is useful") == "Supabase is useful"
    assert manager.get_corrections_for_edit() is None
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrections_with_decomposed_unicode_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """NFD heard values still apply at runtime but block a UI rewrite to NFC."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    original = {
        "version": 1,
        "corrections": [{"heard": "e\u0301clair", "replacement": "éclair"}],
    }
    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    assert manager.get_corrections() == [{"heard": "éclair", "replacement": "éclair"}]
    assert manager.apply_corrections("e\u0301clair") == "éclair"
    assert manager.get_corrections_for_edit() is None
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_corrections_with_duplicate_keys_cannot_be_destructively_edited(
    tmp_path: Path, monkeypatch
) -> None:
    """Duplicate JSON keys still apply at runtime but block a UI rewrite that would drop them."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    cases = [
        (
            "{\n"
            '  "version": 1,\n'
            '  "corrections": [{"heard": "pie object", "replacement": "PyGObject"}],\n'
            '  "corrections": [{"heard": "super base", "replacement": "Supabase"}]\n'
            "}\n",
            [{"heard": "super base", "replacement": "Supabase"}],
        ),
        (
            "{\n"
            '  "version": 1,\n'
            '  "corrections": ['
            '{"heard": "super base", "replacement": "Wrong", "replacement": "Supabase"}'
            "]\n}\n",
            [{"heard": "super base", "replacement": "Supabase"}],
        ),
    ]
    for original, expected_runtime in cases:
        path.write_text(original, encoding="utf-8")
        before = path.read_bytes()

        assert manager.get_corrections() == expected_runtime
        assert manager.apply_corrections("super base is useful") == "Supabase is useful"
        assert manager.get_corrections_for_edit() is None
        assert path.read_bytes() == before


def test_invalid_correction_update_does_not_wipe_existing_entry(
    tmp_path: Path, monkeypatch
) -> None:
    """A too-long replacement must not delete the previous same-heard correction."""
    import importlib
    import sys

    import vocalinux.ui as ui_pkg

    manager = manager_at(tmp_path, monkeypatch)
    original = [{"heard": "super base", "replacement": "Supabase"}]
    assert manager.save_corrections(original)
    corrections_path = tmp_path / CORRECTIONS_FILENAME
    before = corrections_path.read_text(encoding="utf-8")

    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            settings_dialog = importlib.import_module("vocalinux.ui.settings_dialog")
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved
            ui_pkg.settings_dialog = saved
        else:
            ui_pkg.__dict__.pop("settings_dialog", None)

    dialog = Mock()
    dialog._initializing = False
    dialog._applying_settings = False
    dialog._dictionary_available.return_value = True
    dialog.dictionary_manager = manager
    dialog.dictionary_heard_entry.get_text.return_value = "super base"
    dialog.dictionary_replacement_entry.get_text.return_value = "x" * (
        MAX_CORRECTION_CHARACTERS + 1
    )

    settings_dialog.SettingsDialog._on_dictionary_add_correction(dialog, None)

    assert corrections_path.read_text(encoding="utf-8") == before
    assert manager.get_corrections() == original
    dialog.dictionary_heard_entry.set_text.assert_not_called()
    dialog.dictionary_replacement_entry.set_text.assert_not_called()
    dialog.dictionary_feedback_label.set_text.assert_called_once_with(
        "That correction is not valid for the file."
    )


def test_nfd_correction_update_replaces_nfc_entry(tmp_path: Path, monkeypatch) -> None:
    """A decomposed heard phrase must update the existing NFC correction."""
    import importlib
    import sys

    import vocalinux.ui as ui_pkg

    manager = manager_at(tmp_path, monkeypatch)
    original = [{"heard": "éclair", "replacement": "OLD"}]
    assert manager.save_corrections(original)
    corrections_path = tmp_path / CORRECTIONS_FILENAME

    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            settings_dialog = importlib.import_module("vocalinux.ui.settings_dialog")
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved
            ui_pkg.settings_dialog = saved
        else:
            ui_pkg.__dict__.pop("settings_dialog", None)

    dialog = Mock()
    dialog._initializing = False
    dialog._applying_settings = False
    dialog._dictionary_available.return_value = True
    dialog.dictionary_manager = manager
    dialog.dictionary_heard_entry.get_text.return_value = "e\u0301clair"
    dialog.dictionary_replacement_entry.get_text.return_value = "NEW"

    settings_dialog.SettingsDialog._on_dictionary_add_correction(dialog, None)

    stored = json.loads(corrections_path.read_text(encoding="utf-8"))
    assert stored == {
        "version": 1,
        "corrections": [{"heard": "éclair", "replacement": "NEW"}],
    }
    assert manager.get_corrections() == [{"heard": "éclair", "replacement": "NEW"}]
    dialog.dictionary_feedback_label.set_text.assert_called_once_with("Correction updated.")


def test_non_integer_corrections_version_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """Boolean, float, and string versions must not be treated as schema 1."""
    manager = manager_at(tmp_path, monkeypatch)
    path = tmp_path / CORRECTIONS_FILENAME
    cases = (
        '{"version": true, "corrections": [{"heard": "super base", "replacement": "Supabase"}]}\n',
        '{"version": 1.0, "corrections": [{"heard": "super base", "replacement": "Supabase"}]}\n',
        '{"version": "1", "corrections": [{"heard": "super base", "replacement": "Supabase"}]}\n',
        '{"version": 1e0, "corrections": [{"heard": "super base", "replacement": "Supabase"}]}\n',
    )
    for original in cases:
        path.write_text(original, encoding="utf-8")
        before = path.read_bytes()

        assert manager.get_corrections() == []
        assert manager.get_corrections_for_edit() is None
        assert path.read_bytes() == before


def test_invalid_terms_file_is_ignored_and_explained(tmp_path: Path, monkeypatch) -> None:
    """An invalid scanner file leaves prompt bias empty with a clear status."""
    manager = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    (tmp_path / TERMS_FILENAME).write_bytes(b"\xff\xfe")

    assert manager.build_initial_prompt() is None
    assert manager.terms_status() == "Terms file is not valid UTF-8."


def test_whisper_receives_the_live_custom_terms_prompt(tmp_path: Path, monkeypatch) -> None:
    """Whisper gets the current file contents as initial_prompt at transcription time."""
    dictionary = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    (tmp_path / TERMS_FILENAME).write_text("VocaLinux\n", encoding="utf-8")
    manager = recognition_manager("whisper", dictionary)
    manager.model = MagicMock()
    manager.model.transcribe.return_value = {"text": "ok"}
    manager.model.device = MagicMock()

    with patch.dict("sys.modules", {"numpy": mock_numpy(), "torch": MagicMock()}):
        assert manager._transcribe_with_whisper([b"\x00\x00"]) == "ok"

    assert manager.model.transcribe.call_args.kwargs["initial_prompt"] == "VocaLinux"


def test_faster_whisper_receives_the_live_custom_terms_prompt(tmp_path: Path, monkeypatch) -> None:
    """Faster Whisper receives the same live vocabulary bias as OpenAI Whisper."""
    dictionary = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    (tmp_path / TERMS_FILENAME).write_text("VocaLinux\n", encoding="utf-8")
    manager = object.__new__(SpeechRecognitionManager)
    manager.dictionary_manager = dictionary
    manager._faster_whisper_engine = MagicMock()
    manager._faster_whisper_engine.is_ready.return_value = True
    manager._faster_whisper_engine.transcribe.return_value = "ok"

    assert manager._transcribe_with_faster_whisper([b"\x00\x00"]) == "ok"
    manager._faster_whisper_engine.transcribe.assert_called_once_with(
        [b"\x00\x00"], initial_prompt="VocaLinux"
    )


def test_whispercpp_composes_and_clears_live_terms_prompt(tmp_path: Path, monkeypatch) -> None:
    """whisper.cpp keeps Advanced context and explicitly clears a stale prompt."""
    config = FakeConfig({"dictionary": {"enabled": True}})
    dictionary = manager_at(tmp_path, monkeypatch, config)
    terms_file = tmp_path / TERMS_FILENAME
    terms_file.write_text("VocaLinux\n", encoding="utf-8")
    manager = recognition_manager("whisper_cpp", dictionary, advanced_prompt="Explicit context")
    manager._model_lock = threading.Lock()
    manager.model = MagicMock()
    manager.model.transcribe.return_value = [MagicMock(text="ok")]

    with patch.dict("sys.modules", {"numpy": mock_numpy()}):
        assert manager._transcribe_with_whispercpp([b"\x00\x00"]) == "ok"
        config.values["dictionary"]["enabled"] = False
        assert manager._transcribe_with_whispercpp([b"\x00\x00"]) == "ok"
        manager.whispercpp_initial_prompt = ""
        assert manager._transcribe_with_whispercpp([b"\x00\x00"]) == "ok"

    prompts = [call.kwargs["initial_prompt"] for call in manager.model.transcribe.call_args_list]
    assert prompts == ["Explicit context VocaLinux", "Explicit context", ""]


def test_vosk_warns_once_for_bias_while_corrections_remain_available(
    tmp_path: Path, monkeypatch
) -> None:
    """VOSK rejects vocabulary bias only; its transcript can still be corrected."""
    dictionary = manager_at(tmp_path, monkeypatch, FakeConfig({"dictionary": {"enabled": True}}))
    (tmp_path / TERMS_FILENAME).write_text("VocaLinux\n", encoding="utf-8")
    manager = recognition_manager("vosk", dictionary)
    manager._get_vosk_model_path = MagicMock(return_value="/models/vosk")
    vosk = MagicMock()

    with patch.dict("sys.modules", {"vosk": vosk}):
        with patch(
            "vocalinux.speech_recognition.recognition_manager.os.path.exists", return_value=True
        ):
            with patch(
                "vocalinux.speech_recognition.recognition_manager.logger.warning"
            ) as warning:
                manager._init_vosk()
                manager._init_vosk()

    warning.assert_called_once_with(
        "Custom terms are ignored by VOSK; transcript corrections still apply."
    )


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


def test_correction_stage_is_shared_by_every_engine() -> None:
    """The common post-transcription stage is available to local and remote engines."""
    for engine in (
        "vosk",
        "whisper",
        "whisper_cpp",
        "faster_whisper",
        "parakeet",
        "remote_api",
    ):
        manager = object.__new__(SpeechRecognitionManager)
        manager.engine = engine
        manager.dictionary_manager = type(
            "Dictionary", (), {"apply_corrections": lambda self, text: "Supabase"}
        )()

        assert manager._apply_dictionary_corrections("super base") == "Supabase"

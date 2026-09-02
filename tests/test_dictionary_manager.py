"""Tests for live custom dictionary support."""

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from vocalinux.dictionary_manager import DEFAULT_DICTIONARY_FILE, DictionaryManager
from vocalinux.speech_recognition.recognition_manager import SpeechRecognitionManager


class MemoryConfig:
    """Small ConfigManager stand-in for dictionary tests."""

    def __init__(self, path: str, enabled: bool = True) -> None:
        self.values = {"dictionary": {"enabled": enabled, "file_path": path, "max_words": 200}}
        self.saved = False

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.values.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> bool:
        self.values.setdefault(section, {})[key] = value
        return True

    def save_config(self) -> None:
        self.saved = True


def _manager(
    engine: str, dictionary: DictionaryManager, advanced_prompt: str = ""
) -> SpeechRecognitionManager:
    """Create a recognition manager without loading a speech model."""
    with patch.object(SpeechRecognitionManager, "_init_vosk"):
        with patch.object(SpeechRecognitionManager, "_init_whisper"):
            with patch.object(SpeechRecognitionManager, "_init_whispercpp"):
                return SpeechRecognitionManager(
                    engine=engine,
                    dictionary_manager=dictionary,
                    whispercpp_initial_prompt=advanced_prompt,
                )


def _mock_numpy() -> MagicMock:
    numpy = MagicMock()
    numpy.frombuffer.return_value = MagicMock(__len__=lambda _: 16000)
    numpy.frombuffer.return_value.astype.return_value = numpy.frombuffer.return_value
    numpy.int16 = "int16"
    numpy.float32 = "float32"
    return numpy


def test_dictionary_uses_default_contract_for_empty_path() -> None:
    dictionary = DictionaryManager(MemoryConfig(""))
    assert str(dictionary.get_path()).endswith(DEFAULT_DICTIONARY_FILE.removeprefix("~/"))
    assert not dictionary.set_path("   ")


def test_transient_dictionary_never_changes_saved_settings(tmp_path: Path) -> None:
    """A CLI manager must not persist state even if the Settings page calls it."""
    config = MemoryConfig("/saved/dictionary.txt", enabled=False)
    dictionary = DictionaryManager(config, transient_path=str(tmp_path / "session.txt"))

    dictionary.set_enabled(False)
    assert not dictionary.set_path("/another/path.txt")
    config.save_config()  # Simulate a later Settings save in the same process.

    assert config.values["dictionary"] == {
        "enabled": False,
        "file_path": "/saved/dictionary.txt",
        "max_words": 200,
    }
    assert config.saved


def test_unresolvable_or_unreadable_paths_are_safe_and_not_persisted(
    tmp_path: Path,
) -> None:
    unreadable = tmp_path / "unreadable.txt"
    unreadable.write_text("term\n", encoding="utf-8")
    config = MemoryConfig(str(unreadable))
    dictionary = DictionaryManager(config)

    with patch("vocalinux.dictionary_manager.Path.expanduser", side_effect=RuntimeError("no user")):
        assert dictionary.get_path() is None
        assert dictionary.build_initial_prompt() is None
        assert "invalid" in dictionary.get_status().lower()
        assert not dictionary.set_path("~missing-user/dictionary.txt")

    with patch.object(DictionaryManager, "_is_readable", return_value=False):
        assert not dictionary.set_path(str(unreadable))
        assert "readable" in dictionary.get_status().lower()

    assert config.values["dictionary"]["file_path"] == str(unreadable)
    assert not config.saved


def test_dictionary_ignores_missing_file_and_reloads_live_file(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    dictionary = DictionaryManager(MemoryConfig(str(path)))
    assert dictionary.build_initial_prompt() is None

    path.write_text("# comment\nVocaLinux\nVocaLinux\npywhispercpp\n", encoding="utf-8")
    assert dictionary.build_initial_prompt() == "VocaLinux pywhispercpp"
    path.write_text("VocaHQ\n", encoding="utf-8")
    assert dictionary.build_initial_prompt() == "VocaHQ"


def test_invalid_utf8_has_safe_status_and_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_bytes(b"\xff\xfe\xfa")
    dictionary = DictionaryManager(MemoryConfig(str(path)))
    manager = _manager("whisper", dictionary)

    assert dictionary.get_status() == "Dictionary file is not valid UTF-8."
    assert manager._get_dictionary_prompt() is None


def test_dictionary_disabled_returns_no_prompt(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("VocaLinux\n", encoding="utf-8")
    assert DictionaryManager(MemoryConfig(str(path), enabled=False)).build_initial_prompt() is None


def test_dictionary_max_words_parses_and_caps_terms(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    config = MemoryConfig(str(path))
    dictionary = DictionaryManager(config)

    config.values["dictionary"]["max_words"] = "2"
    assert dictionary.build_initial_prompt() == "one two"
    config.values["dictionary"]["max_words"] = "invalid"
    assert dictionary.build_initial_prompt() == "one two three"
    config.values["dictionary"]["max_words"] = -1
    assert dictionary.build_initial_prompt() is None


def test_whisper_receives_live_dictionary_prompt(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("VocaLinux\n", encoding="utf-8")
    manager = _manager("whisper", DictionaryManager(MemoryConfig(str(path))))
    manager.model = MagicMock()
    manager.model.transcribe.return_value = {"text": "ok"}
    manager.model.device = MagicMock()

    with patch.dict("sys.modules", {"numpy": _mock_numpy(), "torch": MagicMock()}):
        assert manager._transcribe_with_whisper([b"\x00\x00"]) == "ok"
    assert manager.model.transcribe.call_args.kwargs["initial_prompt"] == "VocaLinux"


def test_whispercpp_composes_advanced_prompt_and_live_dictionary(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("pywhispercpp\n", encoding="utf-8")
    manager = _manager(
        "whisper_cpp",
        DictionaryManager(MemoryConfig(str(path))),
        advanced_prompt="Explicit context",
    )
    manager._model_lock = threading.Lock()
    segment = MagicMock(text="ok")
    manager.model = MagicMock()
    manager.model.transcribe.return_value = [segment]

    with patch.dict("sys.modules", {"numpy": _mock_numpy()}):
        assert manager._transcribe_with_whispercpp([b"\x00\x00"]) == "ok"
    assert (
        manager.model.transcribe.call_args.kwargs["initial_prompt"]
        == "Explicit context pywhispercpp"
    )


def test_whispercpp_clears_reused_prompt_after_dictionary_changes(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("VocaLinux\n", encoding="utf-8")
    config = MemoryConfig(str(path))
    manager = _manager("whisper_cpp", DictionaryManager(config))
    manager._model_lock = threading.Lock()
    manager.model = MagicMock()
    manager.model.transcribe.return_value = [MagicMock(text="ok")]

    with patch.dict("sys.modules", {"numpy": _mock_numpy()}):
        manager._transcribe_with_whispercpp([b"\x00\x00"])
        config.values["dictionary"]["enabled"] = False
        manager._transcribe_with_whispercpp([b"\x00\x00"])
        config.values["dictionary"]["enabled"] = True
        path.write_text("", encoding="utf-8")
        manager._transcribe_with_whispercpp([b"\x00\x00"])

    prompts = [call.kwargs["initial_prompt"] for call in manager.model.transcribe.call_args_list]
    assert prompts == ["VocaLinux", "", ""]


def test_vosk_dictionary_prompt_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("VocaLinux\n", encoding="utf-8")
    manager = _manager("vosk", DictionaryManager(MemoryConfig(str(path))))
    assert manager._get_dictionary_prompt() == "VocaLinux"


def test_vosk_logs_dictionary_noop_warning_once(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("VocaLinux\n", encoding="utf-8")
    manager = _manager("vosk", DictionaryManager(MemoryConfig(str(path))))
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
        "Custom dictionary is enabled, but VOSK does not support custom dictionaries; "
        "it is ignored."
    )

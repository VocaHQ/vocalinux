"""First run should start from the language the system points at (#777)."""

from unittest.mock import patch

import pytest

from vocalinux.ui import config_manager as cm
from vocalinux.utils import system_language as sl
from vocalinux.utils.vosk_model_info import SUPPORTED_LANGUAGES


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(cm, "_shared_instance", None)
    return tmp_path


@pytest.mark.parametrize(
    "layout,expected",
    [
        ("pl", "pl"),
        ("de", "de"),
        ("cz", "cs"),
        ("se", "sv"),
        ("us", "en-us"),
        ("gb", "en-us"),
        ("xyz", None),
    ],
)
def test_layouts_map_onto_catalogue_entries(layout, expected):
    assert sl._language_for_layout(layout, SUPPORTED_LANGUAGES) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("pl_PL.UTF-8", "pl"),
        ("de_DE@euro", "de"),
        ("en_US.UTF-8", "en-us"),
        ("en_GB", "en-us"),
        ("en_IN", "en-in"),
        ("cs", "cs"),
        ("cs_CZ.UTF-8", "cs"),
        ("ca", "ca"),
        ("ca_ES.UTF-8", "ca"),
        ("nb_NO", "no"),
        ("nb_NO.UTF-8", "no"),
        ("nn_NO", "no"),
        ("C", None),
        ("POSIX", None),
        ("C.UTF-8", None),
        ("xx_YY", None),
    ],
)
def test_locales_map_onto_catalogue_entries(value, expected):
    assert sl._language_for_locale(value, SUPPORTED_LANGUAGES) == expected


def test_a_non_english_layout_beats_an_english_locale():
    """The reported case: desktop in English, keyboard in Polish, speaks Polish."""
    with patch.object(sl, "detect_keyboard_layout", return_value="pl"):
        detected = sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "en_US.UTF-8"})

    assert detected == "pl"


def test_a_us_layout_defers_to_the_locale():
    """ "us" is the default layout on many installs, so it carries little signal."""
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "pl_PL.UTF-8"})

    assert detected == "pl"


def test_a_us_layout_is_used_when_the_locale_says_nothing():
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "C"})

    assert detected == "en-us"


def test_nothing_decisive_returns_none():
    with patch.object(sl, "detect_keyboard_layout", return_value=None):
        assert sl.detect_system_language(SUPPORTED_LANGUAGES, {}) is None


def test_a_missing_localectl_does_not_raise():
    with patch.object(sl.subprocess, "run", side_effect=FileNotFoundError):
        assert sl.detect_keyboard_layout() is None


def test_first_run_starts_from_the_detected_language(isolated_config):
    """Without this the fresh config keeps the packaged "auto"."""
    with patch.object(sl, "detect_keyboard_layout", return_value="pl"):
        with patch.dict("os.environ", {"LANG": "en_US.UTF-8"}, clear=False):
            manager = cm.ConfigManager()

    assert manager.get("speech_recognition", "language") == "pl"


def test_first_run_keeps_the_default_when_detection_finds_nothing(isolated_config):
    with patch.object(sl, "detect_keyboard_layout", return_value=None):
        with patch.dict("os.environ", {"LANG": "C", "LC_ALL": "C"}, clear=True):
            manager = cm.ConfigManager()

    assert manager.get("speech_recognition", "language") == "auto"


def test_a_saved_language_is_never_overwritten(isolated_config):
    """A returning user who chose auto-detect keeps it."""
    import json

    with open(cm.CONFIG_FILE, "w") as handle:
        json.dump({"speech_recognition": {"language": "auto"}}, handle)

    with patch.object(sl, "detect_keyboard_layout", return_value="pl"):
        manager = cm.ConfigManager()

    assert manager.get("speech_recognition", "language") == "auto"


def test_language_env_beats_lang_when_both_set():
    """LANGUAGE is the gettext preference list; LANG must not mask it (#796)."""
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(
            SUPPORTED_LANGUAGES,
            {"LANG": "en_US.UTF-8", "LANGUAGE": "pl:en"},
        )

    assert detected == "pl"


def test_language_env_skips_unsupported_preferences():
    """An unsupported first LANGUAGE pref must not hide a later supported one."""
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(
            SUPPORTED_LANGUAGES,
            {"LANG": "en_US.UTF-8", "LANGUAGE": "xx:pl:en"},
        )

    assert detected == "pl"


def test_language_env_czech_is_not_treated_as_c():
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(
            SUPPORTED_LANGUAGES,
            {"LANG": "en_US.UTF-8", "LANGUAGE": "cs"},
        )

    assert detected == "cs"


def test_nb_no_locale_maps_to_norwegian():
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(
            SUPPORTED_LANGUAGES,
            {"LANG": "nb_NO.UTF-8"},
        )

    assert detected == "no"

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


def test_unmapped_language_env_falls_through_to_lang():
    """An unsupported LANGUAGE list must not hide LANG (#796)."""
    with patch.object(sl, "detect_keyboard_layout", return_value="us"):
        detected = sl.detect_system_language(
            SUPPORTED_LANGUAGES,
            {"LANGUAGE": "xx:yy", "LANG": "pl_PL.UTF-8"},
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


# --- Follow the active keyboard layout (#821) -------------------------------


@pytest.mark.parametrize(
    "sources,current,expected",
    [
        # The bilingual case from the issue: same config, different active index.
        ("[('xkb', 'us'), ('xkb', 'fr')]", "uint32 0", "us"),
        ("[('xkb', 'us'), ('xkb', 'fr')]", "uint32 1", "fr"),
        # A variant is still that layout.
        ("[('xkb', 'fr+oss')]", "uint32 0", "fr"),
        # "uint32 1" must not read as index 32 via a bare \d+ search.
        ("[('xkb', 'us'), ('xkb', 'pl')]", "uint32 1", "pl"),
        # A stale index outlives a removed source; GNOME falls back to the first.
        ("[('xkb', 'us'), ('xkb', 'fr')]", "uint32 9", "us"),
        ("[('xkb', 'us')]", "", "us"),
        # An IBus engine is not an xkb layout and maps to nothing here.
        ("[('ibus', 'mozc-jp')]", "uint32 0", None),
        ("@a(ss) []", "uint32 0", None),
        ("", "uint32 0", None),
    ],
)
def test_active_source_parsing(sources, current, expected):
    assert sl._parse_active_source(sources, current) == expected


def test_active_layout_reads_gsettings():
    with patch.object(sl, "_gsettings_get", side_effect=["[('xkb', 'fr')]", "uint32 0"]):
        assert sl.detect_active_keyboard_layout() == "fr"


def test_active_layout_is_none_without_gsettings():
    with patch.object(sl, "_gsettings_get", return_value=None):
        assert sl.detect_active_keyboard_layout() is None


def test_active_layout_language_maps_onto_catalogue():
    with patch.object(sl, "_active_input_source", return_value=("xkb", "fr")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "fr"


def test_active_layout_falls_back_to_configured_layout():
    """Outside GNOME there is no readable active source; the configured one remains."""
    with patch.object(sl, "_active_input_source", return_value=None):
        with patch.object(sl, "detect_keyboard_layout", return_value="pl"):
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "pl"


def test_active_layout_language_is_none_when_unmappable():
    with patch.object(sl, "_active_input_source", return_value=("xkb", "xyz")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) is None


def test_active_layout_language_is_none_without_any_layout():
    with patch.object(sl, "_active_input_source", return_value=None):
        with patch.object(sl, "detect_keyboard_layout", return_value=None):
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) is None


def test_an_active_ibus_engine_does_not_borrow_the_configured_layout():
    """Typing Japanese through mozc-jp must not resolve to the us layout's English."""
    with patch.object(sl, "_active_input_source", return_value=("ibus", "mozc-jp")):
        with patch.object(sl, "detect_keyboard_layout", return_value="us") as configured:
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "ja"
        configured.assert_not_called()


def test_an_unmapped_ibus_engine_does_not_borrow_the_configured_layout():
    """An unknown IBus engine is still a real answer; leave it to auto-detect."""
    with patch.object(sl, "_active_input_source", return_value=("ibus", "foo-engine")):
        with patch.object(sl, "detect_keyboard_layout", return_value="us") as configured:
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) is None
        configured.assert_not_called()


@pytest.mark.parametrize("engine_id", ["foo-us", "foo-gb", "foo-fr", "foo-de"])
def test_hyphen_suffix_does_not_false_map_layout_tokens(engine_id):
    """rsplit last token is not a language code: mozc-us is Japanese, not xkb us."""
    with patch.object(sl, "_active_input_source", return_value=("ibus", engine_id)):
        with patch.object(sl, "detect_keyboard_layout", return_value="us") as configured:
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) is None
        configured.assert_not_called()


def test_ibus_mozc_us_maps_to_japanese():
    """Mozc's documented US-layout engine is still a Japanese IME."""
    with patch.object(sl, "_active_input_source", return_value=("ibus", "mozc-us")):
        with patch.object(sl, "detect_keyboard_layout", return_value="us") as configured:
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "ja"
        configured.assert_not_called()


def test_ibus_hyphen_jp_and_kr_suffixes_still_map():
    with patch.object(sl, "_active_input_source", return_value=("ibus", "foo-jp")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "ja"
    with patch.object(sl, "_active_input_source", return_value=("ibus", "foo-kr")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "ko"


def test_ibus_m17n_hi_itrans_maps_to_hindi():
    with patch.object(sl, "_active_input_source", return_value=("ibus", "m17n:hi:itrans")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "hi"


def test_ibus_libpinyin_maps_to_chinese():
    with patch.object(sl, "_active_input_source", return_value=("ibus", "libpinyin")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "zh"


def test_active_source_prefers_mru_and_falls_back_to_the_index():
    values = {
        "mru-sources": "[('ibus', 'mozc-jp'), ('xkb', 'us')]",
        "sources": "[('xkb', 'us')]",
        "current": "uint32 0",
    }
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values[key]):
        # The MRU answer wins even though it is unmappable.
        assert tuple(sl._active_input_source()) == ("ibus", "mozc-jp")

    values["mru-sources"] = "@a(ss) []"
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values[key]):
        assert tuple(sl._active_input_source()) == ("xkb", "us")


def test_no_active_source_without_gsettings():
    with patch.object(sl, "_gsettings_get", return_value=None):
        assert sl._active_input_source() is None


def test_active_layout_prefers_mru_over_stale_current_index():
    """GNOME's "current" index goes stale; the MRU list is what tracks a switch.

    Observed live: after switching to the second layout, mru-sources led with
    ('xkb', 'fr') while current still read 0, which points at 'us' (#497, #738).
    """
    values = {
        "mru-sources": "[('xkb', 'fr'), ('xkb', 'us')]",
        "sources": "[('xkb', 'us'), ('xkb', 'fr')]",
        "current": "uint32 0",
    }
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values[key]):
        assert sl.detect_active_keyboard_layout() == "fr"


def test_active_layout_falls_back_to_index_when_mru_is_empty():
    """A session that has never switched has no MRU list to go on."""
    values = {
        "mru-sources": "@a(ss) []",
        "sources": "[('xkb', 'us'), ('xkb', 'pl')]",
        "current": "uint32 1",
    }
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values[key]):
        assert sl.detect_active_keyboard_layout() == "pl"


def test_active_layout_reports_nothing_for_an_ibus_mru_entry():
    """An IBus engine at the front of the MRU list must not fall through."""
    values = {
        "mru-sources": "[('ibus', 'mozc-jp'), ('xkb', 'us')]",
        "sources": "[('xkb', 'us')]",
        "current": "uint32 0",
    }
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values[key]):
        assert sl.detect_active_keyboard_layout() is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("[('xkb', 'us'), ('xkb', 'fr')]", [("xkb", "us"), ("xkb", "fr")]),
        ("@a(ss) [('xkb', 'us')]", [("xkb", "us")]),
        ("@a(ss) []", []),
        ("not a list", []),
        ("", []),
        (None, []),
    ],
)
def test_source_list_parsing(value, expected):
    assert sl._parse_sources(value) == expected

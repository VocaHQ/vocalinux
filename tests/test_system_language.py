"""First run should start from the language the system points at (#777)."""

from typing import Optional
from unittest.mock import MagicMock, patch

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
        ("si", "sl"),
        ("sk", None),
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
        ("sl_SI.UTF-8", "sl"),
        ("sk_SK.UTF-8", None),
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


# --- Variant-aware layout mapping and country-code collisions (#1070) -------


@pytest.mark.parametrize(
    "layout,expected",
    [
        # Canadian French layouts must map to French, never Catalan ("ca").
        ("ca", "fr"),
        ("ca+fr", "fr"),
        ("ca+fr-legacy", "fr"),
        ("ca+fr_legacy", "fr"),
        ("ca+fr-dvorak", "fr"),
        ("ca+multix", "fr"),
        ("ca+multi", "fr"),
        ("ca+multi-2gr", "fr"),
        ("ca(multix)", "fr"),
        ("ca(fr-legacy)", "fr"),
        # Canadian English and Indigenous variants.
        ("ca+eng", "en-us"),
        ("ca(eng)", "en-us"),
        ("ca+ike", None),
        ("ca+kut", None),
        ("ca+shs", None),
        # Catalan is an explicit variant of Spanish, not the Canada layout.
        ("es", "es"),
        ("es+winkeys", "es"),
        ("es+cat", "ca"),
        ("es(cat)", "ca"),
        ("es+ast", None),
        ("latam", "es"),
        ("latam+dvorak", "es"),
        # Switzerland: German default, French and Italian variants.
        ("ch", "de"),
        ("ch+legacy", "de"),
        ("ch+de", "de"),
        ("ch+de_nodeadkeys", "de"),
        ("ch+de_mac", "de"),
        ("ch+fr", "fr"),
        ("ch+fr_nodeadkeys", "fr"),
        ("ch+fr-nodeadkeys", "fr"),
        ("ch+fr_mac", "fr"),
        ("ch(fr)", "fr"),
        ("ch+it", "it"),
        # Single-language country layouts.
        ("ara", "ar"),
        ("ara+qwerty", "ar"),
        ("at", "de"),
        ("at+nodeadkeys", "de"),
        ("au", "en-us"),
        ("bd", "bn"),
        ("cd", "fr"),
        ("ie", "en-us"),
        ("ie+ogam", None),
        ("ie+CloGaelach", None),
        ("md", "ro"),
        ("md+gag", None),
        ("za", "en-us"),
        # Multilingual India layout: supported scripts vs unsupported variants.
        ("in", "hi"),
        ("in+bolnagri", "hi"),
        ("in+hin-wx", "hi"),
        ("in+hin-kagapa", "hi"),
        ("in+eng", "en-in"),
        ("in+iipa", "en-in"),
        ("in+ben", "bn"),
        ("in+ben_inscript", "bn"),
        ("in+tam", "ta"),
        ("in+tam_tamilnet", "ta"),
        ("in+guj", None),
        ("in+tel", None),
        ("in+kan", None),
        ("in+mal", None),
        ("in+marathi", None),
        # Multilingual Arabic / other country layouts.
        ("ma", "ar"),
        ("ma+french", "fr"),
        ("ma+tifinagh", None),
        ("dz", None),
        ("dz+ar", "ar"),
        ("iq", "ar"),
        ("iq+ku", None),
        ("sy", "ar"),
        ("sy+syc", None),
        ("pk", None),
        ("pk+ara", "ar"),
        ("lk", None),
        ("lk+tam_unicode", "ta"),
        ("cm", "en-us"),
        ("cm+french", "fr"),
        ("cm+azerty", "fr"),
        ("ml+fr-oss", "fr"),
        ("ml+us-intl", "en-us"),
        # Cross-language variants on single-language layouts.
        ("us+rus", "ru"),
        ("us+chr", None),
        ("us+haw", None),
        ("gb+pl", "pl"),
        ("de+ro", "ro"),
        ("de+ro_nodeadkeys", "ro"),
        ("de+tr", "tr"),
        ("de+ru", "ru"),
        ("de+ru-translit", "ru"),
        ("de+dsb", None),
        ("fr+oci", None),
        ("fr+geo", None),
        ("cz+rus", "ru"),
        ("se+rus", "ru"),
        ("pl+ru_phonetic_dvorak", "ru"),
        ("ge+ru", "ru"),
        # Case, whitespace, and malformed specs.
        (" CA + Multix ", "fr"),
        ("ES(CAT)", "ca"),
        ("ca+", "fr"),
        ("ca()", "fr"),
        ("+", None),
        ("()", None),
        ("+eng", None),
        ("(eng)", None),
        ("", None),
    ],
)
def test_layout_and_variant_mapping(layout: str, expected: Optional[str]) -> None:
    """Layout+variant specs resolve cleanly without country/language collisions."""
    assert sl._language_for_layout(layout, SUPPORTED_LANGUAGES) == expected


@pytest.mark.parametrize(
    "layout,variant,expected",
    [
        ("ca", "multix", "fr"),
        ("ca", "fr-legacy", "fr"),
        ("ca", "eng", "en-us"),
        ("ca", "ike", None),
        ("ch", "fr", "fr"),
        ("ch", "de_nodeadkeys", "de"),
        ("es", "cat", "ca"),
        ("in", "eng", "en-in"),
        ("in", "guj", None),
        # Explicit variant argument takes precedence over an inline variant.
        ("ca+fr", "eng", "en-us"),
    ],
)
def test_language_for_layout_accepts_explicit_variant_parameter(
    layout: str, variant: str, expected: Optional[str]
) -> None:
    """Callers can pass layout and variant separately while preserving 2-arg compatibility."""
    assert sl._language_for_layout(layout, SUPPORTED_LANGUAGES, variant=variant) == expected


def test_belgian_layout_never_collides_with_belarusian() -> None:
    """Belgian ('be') is multilingual and must never map to Belarusian ('be')."""
    supported_with_belarusian = {"be", "fr", "nl", "de"}
    assert sl._language_for_layout("be", supported_with_belarusian) is None
    assert sl._language_for_layout("be+oss", supported_with_belarusian) is None


def test_catalan_ibus_m17n_engine_still_maps_to_catalan() -> None:
    """Mapping XKB 'ca' to French must not break Catalan m17n IBus engines."""
    with patch.object(sl, "_active_input_source", return_value=("ibus", "m17n:ca:post")):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "ca"


@pytest.mark.parametrize(
    "source_id,expected",
    [
        ("ca", "fr"),
        ("ca+fr", "fr"),
        ("ca+fr-legacy", "fr"),
        ("ca+fr-dvorak", "fr"),
        ("ca+multix", "fr"),
        ("ca+eng", "en-us"),
        ("ca+ike", None),
        ("ch", "de"),
        ("ch+fr", "fr"),
        ("es+cat", "ca"),
        ("in+eng", "en-in"),
        ("in+guj", None),
    ],
)
def test_gnome_active_source_preserves_variant_for_language_resolution(
    source_id: str, expected: Optional[str]
) -> None:
    """Follow-keyboard-layout must read the GNOME xkb variant instead of dropping it."""
    with patch.object(sl, "_active_input_source", return_value=("xkb", source_id)):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == expected


def test_gnome_mru_switching_between_english_and_canadian_french() -> None:
    """Swiping between US English and French Canada in GNOME switches en-us <-> fr (#1070)."""
    for ca_source in ("ca", "ca+fr-legacy", "ca+fr-dvorak", "ca+multix"):
        values = {
            "mru-sources": f"[('xkb', '{ca_source}'), ('xkb', 'us')]",
            "sources": f"[('xkb', 'us'), ('xkb', '{ca_source}')]",
            "current": "uint32 0",
        }
        with patch.object(sl, "_gsettings_get", side_effect=lambda key, v=values: v[key]):
            assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "fr"

    values_en = {
        "mru-sources": "[('xkb', 'us'), ('xkb', 'ca+multix')]",
        "sources": "[('xkb', 'us'), ('xkb', 'ca+multix')]",
        "current": "uint32 0",
    }
    with patch.object(sl, "_gsettings_get", side_effect=lambda key: values_en[key]):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "en-us"


@pytest.mark.parametrize(
    "stdout,expected_layout,expected_language",
    [
        (
            "   System Locale: LANG=fr_CA.UTF-8\n"
            "       VC Keymap: cf\n"
            "      X11 Layout: ca\n"
            "     X11 Variant: multix\n",
            "ca+multix",
            "fr",
        ),
        (
            "      X11 Layout: ca,us\n" "     X11 Variant: eng,\n",
            "ca+eng",
            "en-us",
        ),
        (
            "      X11 Layout: us,ca\n" "     X11 Variant: ,fr-legacy\n",
            "us",
            "en-us",
        ),
        (
            "      X11 Layout: ch,us\n" "     X11 Variant: fr,\n",
            "ch+fr",
            "fr",
        ),
        (
            "      X11 Layout: es\n" "     X11 Variant: cat\n",
            "es+cat",
            "ca",
        ),
        (
            "      X11 Layout: ca\n" "     X11 Variant: (unset)\n",
            "ca",
            "fr",
        ),
        (
            "       VC Keymap: pl\n" "      X11 Layout: (unset)\n" "     X11 Variant: eng\n",
            "pl",
            "pl",
        ),
    ],
)
def test_localectl_parses_layout_and_variant(
    stdout: str, expected_layout: str, expected_language: Optional[str]
) -> None:
    """detect_keyboard_layout preserves the primary X11 Variant from localectl."""
    completed = MagicMock(returncode=0, stdout=stdout)
    with patch.object(sl.subprocess, "run", return_value=completed):
        detected = sl.detect_keyboard_layout()
    assert detected == expected_layout
    assert sl._language_for_layout(detected or "", SUPPORTED_LANGUAGES) == expected_language


def test_first_run_detection_with_canadian_french_and_english_variants() -> None:
    """First-run detection picks French for ca+multix and defers to locale for ca+eng."""
    with patch.object(sl, "detect_keyboard_layout", return_value="ca+multix"):
        assert sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "en_US.UTF-8"}) == "fr"

    with patch.object(sl, "detect_keyboard_layout", return_value="ca+eng"):
        assert sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "fr_CA.UTF-8"}) == "fr"
        assert sl.detect_system_language(SUPPORTED_LANGUAGES, {"LANG": "C"}) == "en-us"


def test_configured_fallback_uses_localectl_variant() -> None:
    """Outside GNOME, language_for_active_layout resolves variants from localectl."""
    stdout = "      X11 Layout: ch,us\n     X11 Variant: fr,\n"
    completed = MagicMock(returncode=0, stdout=stdout)
    with (
        patch.object(sl, "_active_input_source", return_value=None),
        patch.object(sl.subprocess, "run", return_value=completed),
    ):
        assert sl.language_for_active_layout(SUPPORTED_LANGUAGES) == "fr"

"""Work out which language the user probably speaks (#777).

Nothing used to ask the system this, so whisper.cpp always started on auto-detect
and VOSK on a hardcoded ``en-us``. Both are wrong for anyone who does not speak
English, and neither ever improves on its own.

The keyboard layout is consulted before the locale on purpose. Plenty of people
run their desktop in English and speak something else — among the people who
install a Linux dictation tool that is closer to the rule than the exception —
so the interface language is a weak signal for *spoken* language. What someone
types in tracks what they say far more closely.
"""

import ast
import logging
import os
import re
import subprocess
from typing import Any, Optional, cast

from .host_process import host_env

logger = logging.getLogger(__name__)

# xkb layout names are country/region codes, not ISO 639-1 language codes.
# Layouts whose code collides with a different language (like "ca" for Canada
# vs Catalan) or does not match the catalogue id must be mapped explicitly;
# a value of None explicitly opts a multilingual country layout out of any
# direct fallback (e.g. Belgian "be" must never fall through to Belarusian).
_LAYOUT_TO_LANGUAGE: dict[str, Optional[str]] = {
    "us": "en-us",
    "gb": "en-us",
    "au": "en-us",
    "ie": "en-us",
    "za": "en-us",
    "ara": "ar",
    "at": "de",
    "bd": "bn",
    "be": None,
    "br": "pt",
    "ca": "fr",
    "cd": "fr",
    "ch": "de",
    "cn": "zh",
    "cz": "cs",
    "dk": "da",
    "gr": "el",
    "il": "he",
    "ir": "fa",
    "jp": "ja",
    "kr": "ko",
    "latam": "es",
    "md": "ro",
    "nb": "no",
    "nn": "no",
    "se": "sv",
    "si": "sl",
    "ua": "uk",
    "vn": "vi",
}

# Variant-specific overrides keyed by normalised ``(layout, variant)`` (where
# hyphens become underscores). Checked before ``_LAYOUT_TO_LANGUAGE``.
# - A string maps that specific layout+variant to a catalogue language id.
# - None opts a minority/other-language variant out of its base layout's
#   language so it degrades cleanly to auto-detect.
# - An empty variant key ``(layout, "")`` maps only the bare default layout on
#   multilingual country layouts (like ``in``, ``ma``, ``iq``, ``sy``) so
#   unlisted regional variants fall back to auto-detect instead of misidentifying.
_LAYOUT_VARIANT_TO_LANGUAGE: dict[tuple[str, str], Optional[str]] = {
    # Canada: default "ca" and French variants (fr, fr-legacy, fr-dvorak,
    # multix, multi, multi-2gr) inherit "fr" from _LAYOUT_TO_LANGUAGE.
    ("ca", "eng"): "en-us",
    ("ca", "ike"): None,
    ("ca", "kut"): None,
    ("ca", "shs"): None,
    # Switzerland: default "ch" and German variants inherit "de".
    ("ch", "fr"): "fr",
    ("ch", "fr_nodeadkeys"): "fr",
    ("ch", "fr_mac"): "fr",
    ("ch", "sun_type6_fr"): "fr",
    ("ch", "it"): "it",
    # Spain: Catalan is an explicit variant of "es", not layout "ca".
    ("es", "cat"): "ca",
    ("es", "ast"): None,
    # India: multilingual layout; map bare default (Hindi) and catalogue
    # variants explicitly so unsupported regional scripts return None.
    ("in", ""): "hi",
    ("in", "bolnagri"): "hi",
    ("in", "hin_wx"): "hi",
    ("in", "hin_kagapa"): "hi",
    ("in", "eng"): "en-in",
    ("in", "iipa"): "en-in",
    ("in", "ben"): "bn",
    ("in", "ben_probhat"): "bn",
    ("in", "ben_baishakhi"): "bn",
    ("in", "ben_bornona"): "bn",
    ("in", "ben_gitanjali"): "bn",
    ("in", "ben_inscript"): "bn",
    ("in", "tam"): "ta",
    ("in", "tam_tamilnet"): "ta",
    ("in", "tam_tamilnet_with_tam_nums"): "ta",
    ("in", "tam_tamilnet_tab"): "ta",
    ("in", "tam_tamilnet_tscii"): "ta",
    # Multilingual layouts with supported Arabic / French / Tamil / English variants.
    ("ma", ""): "ar",
    ("ma", "french"): "fr",
    ("dz", "ar"): "ar",
    ("iq", ""): "ar",
    ("sy", ""): "ar",
    ("pk", "ara"): "ar",
    ("lk", "tam_unicode"): "ta",
    ("lk", "tam_tab"): "ta",
    ("cm", ""): "en-us",
    ("cm", "french"): "fr",
    ("cm", "azerty"): "fr",
    ("ml", "fr_oss"): "fr",
    ("ml", "us_mac"): "en-us",
    ("ml", "us_intl"): "en-us",
    # Cross-language variants on single-language base layouts.
    ("us", "rus"): "ru",
    ("us", "chr"): None,
    ("us", "haw"): None,
    ("gb", "pl"): "pl",
    ("de", "ro"): "ro",
    ("de", "ro_nodeadkeys"): "ro",
    ("de", "tr"): "tr",
    ("de", "ru"): "ru",
    ("de", "ru_recom"): "ru",
    ("de", "ru_translit"): "ru",
    ("de", "dsb"): None,
    ("de", "dsb_qwertz"): None,
    ("fr", "oci"): None,
    ("fr", "geo"): None,
    ("cz", "rus"): "ru",
    ("se", "rus"): "ru",
    ("se", "rus_nodeadkeys"): "ru",
    ("pl", "ru_phonetic_dvorak"): "ru",
    ("ge", "ru"): "ru",
    ("ie", "clogaelach"): None,
    ("ie", "ogam"): None,
    ("ie", "ogam_is434"): None,
    ("md", "gag"): None,
}

# Common GNOME IBus engine ids. Looked up case-insensitively.
# Mozc ships mozc-jp by default; mozc-us / mozc-on / mozc-off are documented
# extra engine names for US-layout and composition-mode variants -- still Japanese.
_IBUS_ENGINE_TO_LANGUAGE = {
    "mozc-jp": "ja",
    "mozc-us": "ja",
    "mozc-on": "ja",
    "mozc-off": "ja",
    "anthy": "ja",
    "kkc": "ja",
    "skk": "ja",
    "libpinyin": "zh",
    "pinyin": "zh",
    "rime": "zh",
    "chewing": "zh",
    "hangul": "ko",
    "unikey": "vi",
    "bamboo": "vi",
}

# Locale territory codes that pick a specific catalogue entry.
_LOCALE_TO_LANGUAGE = {
    "en_in": "en-in",
    "nb": "no",
    "nn": "no",
    "zh_cn": "zh",
    "zh_tw": "zh",
}

_LOCALE_ENV_VARS = ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")

#: Stored in ``speech_recognition.language`` to mean "whatever the active
#: keyboard layout points at", resolved fresh at the start of every dictation
#: (#821). It is never handed to an engine; ``resolve_language_preference``
#: turns it into a real catalogue id or ``auto`` first.
LANGUAGE_FOLLOWS_LAYOUT = "layout"


def _normalise(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _parse_layout_spec(layout: str, variant: str = "") -> tuple[str, str]:
    """Split an XKB layout specification into ``(layout, variant)`` parts.

    Supports bare names (``"ca"``), GNOME ``layout+variant`` strings
    (``"ca+multix"``), KDE/XKB ``layout(variant)`` strings (``"ch(fr)"``), and
    an explicit ``variant`` argument (which takes precedence when non-empty).
    """
    raw_layout = layout.strip()
    raw_variant = variant.strip()
    if not raw_layout:
        return "", ""

    parsed_variant = ""
    if "+" in raw_layout:
        base, _, parsed_variant = raw_layout.partition("+")
    elif raw_layout.endswith(")") and "(" in raw_layout:
        base, _, rest = raw_layout.partition("(")
        parsed_variant = rest[:-1]
    else:
        base = raw_layout

    base = base.strip()
    if not base:
        return "", ""
    return base, raw_variant or parsed_variant.strip()


def _language_for_layout(
    layout: str, supported: set[str] | dict[str, Any], variant: str = ""
) -> Optional[str]:
    """Map an XKB layout (and optional variant) onto a catalogue language id."""
    raw_base, raw_variant = _parse_layout_spec(layout, variant)
    base = _normalise(raw_base)
    if not base:
        return None
    norm_variant = _normalise(raw_variant)

    key = (base, norm_variant)
    if key in _LAYOUT_VARIANT_TO_LANGUAGE:
        mapped = _LAYOUT_VARIANT_TO_LANGUAGE[key]
        return mapped if mapped and mapped in supported else None

    mapped = _LAYOUT_TO_LANGUAGE.get(base, base)
    return mapped if mapped and mapped in supported else None


def _language_for_locale(value: str, supported: set[str] | dict[str, Any]) -> Optional[str]:
    """Map a locale string such as ``pl_PL.UTF-8`` onto a catalogue entry."""
    value = _normalise(value)
    if not value:
        return None

    # Strip the encoding and any modifier: pl_pl.utf_8@euro -> pl_pl
    value = re.split(r"[.@]", value, maxsplit=1)[0]
    # Exact C/POSIX only — startswith("c") wrongly rejects cs/ca/cy.
    if value in ("c", "posix"):
        return None

    if value in _LOCALE_TO_LANGUAGE:
        candidate = _LOCALE_TO_LANGUAGE[value]
        return candidate if candidate in supported else None

    if value in supported:
        return value

    base = value.split("_", 1)[0]
    if base in _LOCALE_TO_LANGUAGE:
        candidate = _LOCALE_TO_LANGUAGE[base]
        return candidate if candidate in supported else None
    if base == "en":
        return "en-us" if "en-us" in supported else None
    return base if base in supported else None


def detect_keyboard_layout() -> Optional[str]:
    """Return the primary xkb layout (with variant if set), or None.

    When ``localectl`` reports a non-empty primary ``X11 Variant`` alongside
    ``X11 Layout``, the returned string carries it as ``layout+variant`` (for
    example ``ca+eng`` or ``ch+fr``) so variant-aware language mapping works
    outside GNOME as well.

    ``localectl`` is used rather than ``setxkbmap`` because the latter reports
    nothing useful on Wayland, where the compositor owns the keyboard.
    """
    try:
        result = subprocess.run(
            ["localectl", "status"],
            capture_output=True,
            text=True,
            timeout=2,
            env=host_env(),
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"Could not query localectl: {exc}")
        return None

    if result.returncode != 0:
        logger.debug(f"localectl exited with {result.returncode}")
        return None

    layout: Optional[str] = None
    variant: Optional[str] = None
    keymap: Optional[str] = None
    for line in result.stdout.splitlines():
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if not value or value.lower() == "(unset)":
            continue
        if key == "x11 layout":
            layout = value
        elif key == "x11 variant":
            variant = value
        elif key == "vc keymap":
            keymap = value

    # A multi-layout setup lists the primary one first: "pl,us" with matching
    # comma-separated variants such as "eng," or ",fr-legacy".
    if layout:
        primary_layout = layout.split(",")[0].strip()
        if primary_layout:
            primary_variant = variant.split(",")[0].strip() if variant else ""
            if primary_variant and "+" not in primary_layout and "(" not in primary_layout:
                return f"{primary_layout}+{primary_variant}"
            return primary_layout

    if keymap:
        return keymap.split(",")[0].strip() or None

    return None


def detect_locale_language(environ: Optional[dict[str, str]] = None) -> Optional[str]:
    """Return the first locale value the environment offers, or None.

    LANGUAGE is returned intact (a colon-separated preference list). Mapping
    that list onto a supported catalogue entry happens in
    ``_language_from_locale_env``.
    """
    environment = cast(dict[str, str], os.environ if environ is None else environ)
    for name in _LOCALE_ENV_VARS:
        value = environment.get(name)
        if value:
            return value
    return None


def _language_from_locale_env(
    environ: dict[str, str], supported: set[str] | dict[str, dict[str, str]]
) -> Optional[str]:
    """Map locale env vars onto a catalogue entry, first supported win.

    LANGUAGE is a colon-separated preference list: each entry is tried through
    ``_language_for_locale`` until one is supported. An env var whose values
    are all unmapped is skipped so a later var (typically LANG) can still
    win. LC_ALL, LC_MESSAGES, and LANG are single values and are not walked
    as lists.
    """
    for name in _LOCALE_ENV_VARS:
        value = environ.get(name)
        if not value:
            continue
        candidates = value.split(":") if name == "LANGUAGE" else (value,)
        for candidate in candidates:
            mapped = _language_for_locale(candidate, supported)
            if mapped:
                return mapped
        continue
    return None


def detect_system_language(
    supported: set[str] | dict[str, dict[str, str]], environ: Optional[dict[str, str]] = None
) -> Optional[str]:
    """Return the language id to start from, or None when nothing is decisive.

    A non-English keyboard layout is the strongest signal available and wins.
    "us" is the fallback layout on a great many installs and therefore says very
    little, so the locale gets a say before that layout is accepted.
    """
    layout_language = None
    layout = detect_keyboard_layout()
    if layout:
        layout_language = _language_for_layout(layout, supported)
        if layout_language and not layout_language.startswith("en"):
            logger.info(f"Language {layout_language} taken from keyboard layout {layout!r}")
            return layout_language

    environment = cast(dict[str, str], os.environ if environ is None else environ)
    locale_language = _language_from_locale_env(environment, supported)
    if locale_language:
        logger.info(f"Language {locale_language} taken from locale environment")
        return locale_language

    if layout_language:
        logger.info(f"Language {layout_language} taken from keyboard layout {layout!r}")
        return layout_language

    logger.info("Could not work out a language from the system")
    return None


# GNOME exposes the configured input sources as ``(type, id)`` pairs. The id
# carries an optional variant, so "fr+oss" is the oss variant of the fr layout.
_INPUT_SOURCES_SCHEMA = "org.gnome.desktop.input-sources"


def _gsettings_get(key: str) -> Optional[str]:
    """Return a raw gsettings value from the input-sources schema, or None."""
    try:
        result = subprocess.run(
            ["gsettings", "get", _INPUT_SOURCES_SCHEMA, key],
            capture_output=True,
            text=True,
            timeout=2,
            env=host_env(),
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"Could not query gsettings {key}: {exc}")
        return None

    if result.returncode != 0:
        logger.debug(f"gsettings {key} exited with {result.returncode}")
        return None

    return result.stdout.strip() or None


def _parse_sources(value: Optional[str]) -> list[tuple[str, str]]:
    """Parse a gsettings input-source list, tolerating the ``@a(ss)`` prefix."""
    text = (value or "").strip()
    if text.startswith("@a(ss) "):
        text = text[len("@a(ss) ") :]
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        logger.debug(f"Could not parse an input-source list: {value!r}")
        return []
    if not isinstance(parsed, (list, tuple)):
        return []
    return cast(list[tuple[str, str]], list(parsed))


def _xkb_layout_and_variant_from_source(source: object) -> Optional[tuple[str, str]]:
    """Return ``(layout, variant)`` from one ``(type, id)`` input-source pair."""
    if not isinstance(source, (list, tuple)) or len(source) != 2:
        return None
    source_type, source_id = source
    if not isinstance(source_type, str) or not isinstance(source_id, str) or not source_id:
        return None
    if source_type != "xkb":
        # An IBus engine (mozc-jp, pinyin) is not an xkb layout, and its id is
        # not something _LAYOUT_TO_LANGUAGE can map.
        logger.debug(f"Active input source {source_id!r} is {source_type}, not xkb")
        return None
    layout, variant = _parse_layout_spec(source_id)
    if not layout:
        return None
    return layout, variant


def _xkb_layout_from_source(source: object) -> Optional[str]:
    """Return the xkb layout id from one ``(type, id)`` input-source pair."""
    pair = _xkb_layout_and_variant_from_source(source)
    return pair[0] if pair is not None else None


def _source_at_index(parsed: list[tuple[str, str]], current: str) -> Optional[tuple[str, str]]:
    """Return the ``(type, id)`` pair the ``current`` index points at."""
    if not parsed:
        return None

    # "uint32 1" is what gsettings prints, so anchor on the trailing integer:
    # a bare \d+ search matches the 32 in "uint32" and every lookup reads as
    # index 32.
    match = re.search(r"(\d+)\s*$", (current or "").strip())
    index = int(match.group(1)) if match else 0
    if index >= len(parsed):
        # A stale index outlives a removed source. GNOME falls back to the first
        # entry in that case and so do we, rather than reporting nothing.
        logger.debug(f"Input source index {index} is out of range, using the first")
        index = 0

    return parsed[index]


def _parse_active_source(sources: str, current: str) -> Optional[str]:
    """Pick the active xkb layout out of the ``sources`` list and ``current`` index."""
    return _xkb_layout_from_source(_source_at_index(_parse_sources(sources), current))


def _active_input_source() -> Optional[tuple[str, str]]:
    """Return GNOME's active ``(type, id)`` input source, or None if unreadable.

    None means "no answer available" -- not GNOME, or the keys are missing. An
    answer that is an IBus engine rather than an xkb layout is still an answer,
    and callers must not treat it as absence.
    """
    mru = _parse_sources(_gsettings_get("mru-sources"))
    if mru:
        # Trust the MRU answer even when it is an unmappable IBus engine; the
        # index fallback would only supply a different, wronger layout.
        return mru[0]

    sources = _gsettings_get("sources")
    if not sources:
        return None
    return _source_at_index(_parse_sources(sources), _gsettings_get("current") or "")


def detect_active_keyboard_layout() -> Optional[str]:
    """Return the layout currently being typed with, or None (#821).

    ``detect_keyboard_layout`` answers a different question: it reports the
    *configured* primary layout, which never changes as the user switches
    between them. Someone who runs "fr,us" to work in two languages gets "fr"
    from it forever, so it cannot drive a follow-the-layout mode.

    ``mru-sources`` is read first because GNOME moves the source actually in use
    to the front of it. The ``current`` index is not equivalent and goes stale --
    it has been observed still reading 0 after a switch to the second layout --
    which is why the IBus injection path already trusts the MRU list for this
    same question (#497, #738). ``current`` is kept only for a session that has
    never switched and therefore has an empty MRU list.

    GNOME is the only desktop asked here: under Wayland the compositor owns the
    keyboard and exposes nothing standard, and the X11 XKB group is not readable
    through the python-xlib we already depend on. Elsewhere this returns None and
    ``language_for_active_layout`` falls back to the configured layout.
    """
    return _xkb_layout_from_source(_active_input_source())


def _language_for_ibus_source(
    source: object, supported: set[str] | dict[str, Any]
) -> Optional[str]:
    """Map a GNOME IBus ``(type, id)`` pair onto a catalogue language."""
    if not isinstance(source, (list, tuple)) or len(source) != 2:
        return None
    source_type, source_id = source
    if not isinstance(source_type, str) or source_type.lower() != "ibus":
        return None
    if not isinstance(source_id, str) or not source_id:
        return None

    engine = source_id.strip().lower()
    mapped = _IBUS_ENGINE_TO_LANGUAGE.get(engine)
    if mapped and mapped in supported:
        return mapped

    if engine.startswith("m17n:"):
        lang = engine.split(":", 2)[1]
        if lang:
            return _language_for_locale(lang, supported) or _language_for_layout(lang, supported)
        return None

    # Only *-jp / *-kr: a generic last-token lookup maps mozc-us and foo-us
    # onto English via the xkb "us" layout, which is the IBus fallback bug.
    if "-" in engine:
        suffix = engine.rsplit("-", 1)[-1]
        if suffix in ("jp", "kr"):
            return _language_for_layout(suffix, supported)
    return None


def language_for_active_layout(supported: set[str] | dict[str, Any]) -> Optional[str]:
    """Return the catalogue language for the active layout, or None (#821).

    Falls back to the configured primary layout where the active one cannot be
    read, which is what a single-layout install reports anyway. An active IBus
    engine is mapped when we know it; otherwise auto-detect is used rather than
    borrowing the configured xkb layout.
    """
    active = _active_input_source()
    if active is not None:
        xkb = _xkb_layout_and_variant_from_source(active)
        if xkb is not None:
            layout, variant = xkb
            return _language_for_layout_logged(
                layout, supported, "active keyboard layout", variant=variant
            )
        language = _language_for_ibus_source(active, supported)
        if language:
            logger.debug(f"Language {language} taken from IBus engine {active!r}")
            return language
        # An active IBus engine we cannot map is still a real answer. Falling
        # back to the configured xkb layout here would pin English for someone
        # typing Japanese, so say nothing and let the engine auto-detect.
        logger.debug(f"Active input source {active!r} is not an xkb layout; using auto-detect")
        return None

    # Nothing readable -- not GNOME. The configured primary layout is the only
    # signal left, and is what a single-layout install reports anyway.
    configured_layout = detect_keyboard_layout()
    if not configured_layout:
        return None
    return _language_for_layout_logged(configured_layout, supported, "configured keyboard layout")


def _language_for_layout_logged(
    layout: str, supported: set[str] | dict[str, Any], source: str, variant: str = ""
) -> Optional[str]:
    """Map a layout onto the catalogue, saying where it came from."""
    language = _language_for_layout(layout, supported, variant=variant)
    label = f"{layout}+{variant}" if variant and "+" not in layout and "(" not in layout else layout
    if not language:
        logger.debug(f"No catalogue language for {source} {label!r}")
        return None
    logger.debug(f"Language {language} taken from {source} {label!r}")
    return language

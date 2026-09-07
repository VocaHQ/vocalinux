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

import logging
import os
import re
import subprocess
from typing import Optional

from .host_process import host_env

logger = logging.getLogger(__name__)

# xkb layout names that do not match the language id we use. Layouts not listed
# here are looked up as-is, which covers pl, de, fr, it, es, ru and the rest.
_LAYOUT_TO_LANGUAGE = {
    "us": "en-us",
    "gb": "en-us",
    "cz": "cs",
    "se": "sv",
    "dk": "da",
    "gr": "el",
    "ua": "uk",
    "jp": "ja",
    "kr": "ko",
    "cn": "zh",
    "ir": "fa",
    "il": "he",
    "br": "pt",
    "nb": "no",
    "nn": "no",
    "vn": "vi",
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


def _normalise(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _language_for_layout(layout: str, supported: set[str] | dict) -> Optional[str]:
    layout = _normalise(layout)
    if not layout:
        return None
    mapped = _LAYOUT_TO_LANGUAGE.get(layout, layout)
    return mapped if mapped in supported else None


def _language_for_locale(value: str, supported: set[str] | dict) -> Optional[str]:
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
    """Return the primary xkb layout, or None when it cannot be read.

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

    layout = None
    keymap = None
    for line in result.stdout.splitlines():
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "x11 layout" and value:
            layout = value
        elif key == "vc keymap" and value:
            keymap = value

    # A multi-layout setup lists the primary one first: "pl,us".
    chosen = layout or keymap
    if not chosen:
        return None
    return chosen.split(",")[0].strip() or None


def detect_locale_language(environ: Optional[dict] = None) -> Optional[str]:
    """Return the first locale value the environment offers, or None.

    LANGUAGE is returned intact (a colon-separated preference list). Mapping
    that list onto a supported catalogue entry happens in
    ``_language_from_locale_env``.
    """
    environ = os.environ if environ is None else environ
    for name in _LOCALE_ENV_VARS:
        value = environ.get(name)
        if value:
            return value
    return None


def _language_from_locale_env(environ: dict, supported: set[str] | dict) -> Optional[str]:
    """Map the first locale env var onto a catalogue entry.

    LANGUAGE is a colon-separated preference list: each entry is tried through
    ``_language_for_locale`` until one is supported. LC_ALL, LC_MESSAGES, and
    LANG are single values and are not walked as lists.
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
        return None
    return None


def detect_system_language(
    supported: set[str] | dict, environ: Optional[dict] = None
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

    environ = os.environ if environ is None else environ
    locale_language = _language_from_locale_env(environ, supported)
    if locale_language:
        logger.info(f"Language {locale_language} taken from locale environment")
        return locale_language

    if layout_language:
        logger.info(f"Language {layout_language} taken from keyboard layout {layout!r}")
        return layout_language

    logger.info("Could not work out a language from the system")
    return None

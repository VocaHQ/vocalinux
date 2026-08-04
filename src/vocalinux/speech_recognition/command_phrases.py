"""Localized spoken phrase aliases for voice commands.

English phrases live in ``CommandProcessor``; this module supplies extra
punctuation / line-break aliases keyed by Whisper ISO language codes
(``it``, ``fr``, ``de``, …). English aliases are always merged on top.
"""

from __future__ import annotations

from typing import Optional

from vocalinux.utils.vosk_model_info import SUPPORTED_LANGUAGES

# Phrase → replacement. Longer phrases must be listed before shorter ones that
# share a prefix (e.g. "punto interrogativo" before "punto") so callers can
# rely on insertion order when sorting is skipped.
_TEXT_COMMAND_ALIASES: dict[str, dict[str, str]] = {
    "it": {
        "punto interrogativo": "?",
        "punto esclamativo": "!",
        "punto e virgola": ";",
        "nuovo paragrafo": "\n\n",
        "nuova riga": "\n",
        "a capo": "\n",
        "due punti": ":",
        "trattino basso": "_",
        "apri parentesi": "(",
        "chiudi parentesi": ")",
        "virgola": ",",
        "punto": ".",
        "trattino": "-",
    },
    "fr": {
        "point d'interrogation": "?",
        "point d interrogation": "?",
        "point d'exclamation": "!",
        "point d exclamation": "!",
        "nouveau paragraphe": "\n\n",
        "nouvelle ligne": "\n",
        "a la ligne": "\n",
        "à la ligne": "\n",
        "point virgule": ";",
        "point-virgule": ";",
        "deux points": ":",
        "parenthese ouvrante": "(",
        "parenthèse ouvrante": "(",
        "parenthese fermante": ")",
        "parenthèse fermante": ")",
        "virgule": ",",
        "point": ".",
        "tiret": "-",
        "underscore": "_",
    },
    "de": {
        "neuer absatz": "\n\n",
        "neue zeile": "\n",
        "fragezeichen": "?",
        "ausrufezeichen": "!",
        "strichpunkt": ";",
        "doppelpunkt": ":",
        "klammer auf": "(",
        "klammer zu": ")",
        "bindestrich": "-",
        "unterstrich": "_",
        "komma": ",",
        "punkt": ".",
        "absatz": "\n\n",
    },
    "es": {
        "signo de interrogacion": "?",
        "signo de interrogación": "?",
        "signo de exclamacion": "!",
        "signo de exclamación": "!",
        "punto y coma": ";",
        "nuevo parrafo": "\n\n",
        "nuevo párrafo": "\n\n",
        "nueva linea": "\n",
        "nueva línea": "\n",
        "dos puntos": ":",
        "abrir parentesis": "(",
        "abrir paréntesis": "(",
        "cerrar parentesis": ")",
        "cerrar paréntesis": ")",
        "guion bajo": "_",
        "guión bajo": "_",
        "coma": ",",
        "punto": ".",
        "guion": "-",
        "guión": "-",
    },
    "pt": {
        "ponto de interrogacao": "?",
        "ponto de interrogação": "?",
        "ponto de exclamacao": "!",
        "ponto de exclamação": "!",
        "ponto e virgula": ";",
        "ponto e vírgula": ";",
        "novo paragrafo": "\n\n",
        "nova linha": "\n",
        "dois pontos": ":",
        "abrir parenteses": "(",
        "abrir parênteses": "(",
        "fechar parenteses": ")",
        "fechar parênteses": ")",
        "traco baixo": "_",
        "traço baixo": "_",
        "virgula": ",",
        "vírgula": ",",
        "ponto": ".",
        "traco": "-",
        "traço": "-",
    },
    "nl": {
        "vraagteken": "?",
        "uitroepteken": "!",
        "puntkomma": ";",
        "dubbele punt": ":",
        "nieuwe regel": "\n",
        "nieuwe alinea": "\n\n",
        "komma": ",",
        "punt": ".",
        "streepje": "-",
        "underscore": "_",
    },
    "pl": {
        "znak zapytania": "?",
        "wykrzyknik": "!",
        "srednik": ";",
        "średnik": ";",
        "dwukropek": ":",
        "nowa linia": "\n",
        "nowy akapit": "\n\n",
        "przecinek": ",",
        "kropka": ".",
        "myslnik": "-",
        "myślnik": "-",
        "podkreslnik": "_",
        "podkreślnik": "_",
    },
    "ru": {
        "вопросительный знак": "?",
        "восклицательный знак": "!",
        "новая строка": "\n",
        "новый абзац": "\n\n",
        "точка с запятой": ";",
        "двоеточие": ":",
        "открыть скобку": "(",
        "закрыть скобку": ")",
        "запятая": ",",
        "точка": ".",
        "тире": "-",
        "подчёркивание": "_",
        "подчеркивание": "_",
    },
}

# Extra English aliases always available (beyond the base CommandProcessor map).
_ENGLISH_EXTRA: dict[str, str] = {
    "dot": ".",
}


def normalize_command_language(language: Optional[str]) -> str:
    """Map a catalog / Whisper language id to a phrase-alias key.

    ``auto`` and unknown values fall back to English (``en``). Catalog keys
    such as ``en-us`` resolve via ``SUPPORTED_LANGUAGES`` whisper codes.
    """
    if not language or language == "auto":
        return "en"
    info = SUPPORTED_LANGUAGES.get(language)
    if info is not None and info.get("whisper"):
        return info["whisper"]
    if language.startswith("en"):
        return "en"
    return language


def text_command_aliases_for(language: Optional[str]) -> dict[str, str]:
    """Return localized text-command aliases for ``language``.

    English extras are always included. Localized aliases are added when the
    recognition language is not English.
    """
    aliases = dict(_ENGLISH_EXTRA)
    code = normalize_command_language(language)
    if code != "en":
        aliases.update(_TEXT_COMMAND_ALIASES.get(code, {}))
    return aliases

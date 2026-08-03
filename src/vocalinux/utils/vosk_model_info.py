"""Language definitions and VOSK model metadata."""

import logging
import os
import shutil
from typing import Any, NamedTuple, Optional

from .paths import is_within_directory, models_dir

logger = logging.getLogger(__name__)

# Language definitions with display names and Whisper/VOSK codes
# Supported languages for speech recognition
#
# Whisper / whisper.cpp / remote_api use the catalog key (or the "whisper"
# code for English-only model checks). VOSK uses per-language model zips from
# VOSK_MODEL_INFO; set "vosk" to None when no official Alphacephei model exists.
# Medium/large must cover every language present in small (see issue #550).
SUPPORTED_LANGUAGES = {
    "auto": {
        "name": "Auto-detect",
        "whisper": None,
        "vosk": None,
        "warning": "Slower, may be less accurate",
    },
    "en-us": {
        "name": "English (US)",
        "whisper": "en",
        "vosk": "vosk-model-small-en-us-0.15",
    },
    "en-in": {
        "name": "English (India)",
        "whisper": "en",
        "vosk": "vosk-model-small-en-in-0.4",
    },
    "ar": {
        "name": "Arabic",
        "whisper": "ar",
        "vosk": "vosk-model-small-ar-0.3",
    },
    "bn": {
        "name": "Bengali",
        "whisper": "bn",
        "vosk": None,
    },
    "ca": {
        "name": "Catalan",
        "whisper": "ca",
        "vosk": "vosk-model-small-ca-0.4",
    },
    "zh": {
        "name": "Chinese",
        "whisper": "zh",
        "vosk": "vosk-model-small-cn-0.22",
    },
    "cs": {
        "name": "Czech",
        "whisper": "cs",
        "vosk": "vosk-model-small-cs-0.4-rhasspy",
    },
    "da": {
        "name": "Danish",
        "whisper": "da",
        "vosk": None,
    },
    "nl": {
        "name": "Dutch",
        "whisper": "nl",
        "vosk": "vosk-model-small-nl-0.22",
    },
    "fi": {
        "name": "Finnish",
        "whisper": "fi",
        "vosk": None,
    },
    "fr": {
        "name": "French",
        "whisper": "fr",
        "vosk": "vosk-model-small-fr-0.22",
    },
    "de": {
        "name": "German",
        "whisper": "de",
        "vosk": "vosk-model-small-de-0.15",
    },
    "el": {
        "name": "Greek",
        "whisper": "el",
        "vosk": None,
    },
    "he": {
        "name": "Hebrew",
        "whisper": "he",
        "vosk": None,
    },
    "hi": {
        "name": "Hindi",
        "whisper": "hi",
        "vosk": "vosk-model-small-hi-0.22",
    },
    "hu": {
        "name": "Hungarian",
        "whisper": "hu",
        "vosk": None,
    },
    "id": {
        "name": "Indonesian",
        "whisper": "id",
        "vosk": None,
    },
    "it": {
        "name": "Italian",
        "whisper": "it",
        "vosk": "vosk-model-small-it-0.22",
    },
    "ja": {
        "name": "Japanese",
        "whisper": "ja",
        "vosk": "vosk-model-small-ja-0.22",
    },
    "ko": {
        "name": "Korean",
        "whisper": "ko",
        "vosk": "vosk-model-small-ko-0.22",
    },
    "no": {
        "name": "Norwegian",
        "whisper": "no",
        "vosk": None,
    },
    "fa": {
        "name": "Persian",
        "whisper": "fa",
        "vosk": "vosk-model-small-fa-0.42",
    },
    "pl": {
        "name": "Polish",
        "whisper": "pl",
        "vosk": "vosk-model-small-pl-0.22",
    },
    "pt": {
        "name": "Portuguese",
        "whisper": "pt",
        "vosk": "vosk-model-small-pt-0.3",
    },
    "ro": {
        "name": "Romanian",
        "whisper": "ro",
        "vosk": None,
    },
    "ru": {
        "name": "Russian",
        "whisper": "ru",
        "vosk": "vosk-model-small-ru-0.22",
    },
    "es": {
        "name": "Spanish",
        "whisper": "es",
        "vosk": "vosk-model-small-es-0.42",
    },
    "sv": {
        "name": "Swedish",
        "whisper": "sv",
        "vosk": "vosk-model-small-sv-rhasspy-0.15",
    },
    "ta": {
        "name": "Tamil",
        "whisper": "ta",
        "vosk": None,
    },
    "th": {
        "name": "Thai",
        "whisper": "th",
        "vosk": None,
    },
    "tr": {
        "name": "Turkish",
        "whisper": "tr",
        "vosk": "vosk-model-small-tr-0.3",
    },
    "uk": {
        "name": "Ukrainian",
        "whisper": "uk",
        "vosk": "vosk-model-small-uk-v3-small",
    },
    "vi": {
        "name": "Vietnamese",
        "whisper": "vi",
        "vosk": "vosk-model-small-vn-0.4",
    },
}


# Alphacephei serves every model as "<base>/<model name>.zip".
VOSK_MODEL_BASE_URL = "https://alphacephei.com/vosk/models"


def vosk_model_url(model_name: str) -> str:
    """Build the Alphacephei download URL for a VOSK model."""
    return f"{VOSK_MODEL_BASE_URL}/{model_name}.zip"


# VOSK model metadata for display and download path resolution.
# When Alphacephei only ships a small model, medium/large point at that same
# zip so size selection never resolves to None (issue #550).
VOSK_MODEL_INFO = {
    "small": {
        "size_mb": 40,
        "desc": "Lightweight, fast",
        "languages": {
            "en-us": "vosk-model-small-en-us-0.15",
            "en-in": "vosk-model-small-en-in-0.4",
            "ar": "vosk-model-small-ar-0.3",
            "ca": "vosk-model-small-ca-0.4",
            "zh": "vosk-model-small-cn-0.22",
            "cs": "vosk-model-small-cs-0.4-rhasspy",
            "nl": "vosk-model-small-nl-0.22",
            "fr": "vosk-model-small-fr-0.22",
            "de": "vosk-model-small-de-0.15",
            "hi": "vosk-model-small-hi-0.22",
            "it": "vosk-model-small-it-0.22",
            "ja": "vosk-model-small-ja-0.22",
            "ko": "vosk-model-small-ko-0.22",
            "fa": "vosk-model-small-fa-0.42",
            "pl": "vosk-model-small-pl-0.22",
            "pt": "vosk-model-small-pt-0.3",
            "ru": "vosk-model-small-ru-0.22",
            "es": "vosk-model-small-es-0.42",
            "sv": "vosk-model-small-sv-rhasspy-0.15",
            "tr": "vosk-model-small-tr-0.3",
            "uk": "vosk-model-small-uk-v3-small",
            "vi": "vosk-model-small-vn-0.4",
        },
    },
    "medium": {
        "size_mb": 1500,
        "desc": "Balanced accuracy/speed",
        "languages": {
            "en-us": "vosk-model-en-us-0.22",
            "en-in": "vosk-model-en-in-0.5",
            "ar": "vosk-model-ar-0.22-linto-1.1.0",
            "ca": "vosk-model-small-ca-0.4",
            "zh": "vosk-model-cn-0.22",
            "cs": "vosk-model-small-cs-0.4-rhasspy",
            "nl": "vosk-model-nl-spraakherkenning-0.6",
            "fr": "vosk-model-fr-0.22",
            "de": "vosk-model-de-0.21",
            "hi": "vosk-model-hi-0.22",
            "it": "vosk-model-it-0.22",
            "ja": "vosk-model-ja-0.22",
            "ko": "vosk-model-small-ko-0.22",
            "fa": "vosk-model-fa-0.42",
            "pl": "vosk-model-small-pl-0.22",
            "pt": "vosk-model-pt-0.4",
            "ru": "vosk-model-ru-0.22",
            "es": "vosk-model-es-0.42",
            "sv": "vosk-model-small-sv-rhasspy-0.15",
            "tr": "vosk-model-small-tr-0.3",
            "uk": "vosk-model-uk-v3",
            "vi": "vosk-model-vn-0.4",
        },
    },
    "large": {
        "size_mb": 1500,
        "desc": "Same as medium (best available)",
        "languages": {
            "en-us": "vosk-model-en-us-0.22",
            "en-in": "vosk-model-en-in-0.5",
            "ar": "vosk-model-ar-0.22-linto-1.1.0",
            "ca": "vosk-model-small-ca-0.4",
            "zh": "vosk-model-cn-0.22",
            "cs": "vosk-model-small-cs-0.4-rhasspy",
            "nl": "vosk-model-nl-spraakherkenning-0.6",
            "fr": "vosk-model-fr-0.22",
            "de": "vosk-model-de-0.21",
            "hi": "vosk-model-hi-0.22",
            "it": "vosk-model-it-0.22",
            "ja": "vosk-model-ja-0.22",
            "ko": "vosk-model-small-ko-0.22",
            "fa": "vosk-model-fa-0.42",
            "pl": "vosk-model-small-pl-0.22",
            "pt": "vosk-model-pt-0.4",
            "ru": "vosk-model-ru-0.22",
            "es": "vosk-model-es-0.42",
            "sv": "vosk-model-small-sv-rhasspy-0.15",
            "tr": "vosk-model-small-tr-0.3",
            "uk": "vosk-model-uk-v3",
            "vi": "vosk-model-vn-0.4",
        },
    },
}


class DownloadedVoskModel(NamedTuple):
    """A VOSK model directory present in the user models folder."""

    dirname: str
    language: str
    size: str
    size_mb: int
    path: str


def _vosk_catalog_entry(size: str) -> Optional[dict[str, Any]]:
    info = VOSK_MODEL_INFO.get(size)
    return info if isinstance(info, dict) else None


def _vosk_language_map(info: dict[str, Any]) -> dict[str, str]:
    languages = info.get("languages")
    if not isinstance(languages, dict):
        return {}
    return {str(key): str(value) for key, value in languages.items()}


def vosk_model_dirname(size: str, language: str) -> Optional[str]:
    """Return the on-disk directory name for a VOSK size and language."""
    info = _vosk_catalog_entry(size)
    if info is None:
        return None
    languages = _vosk_language_map(info)
    if language == "auto" or language not in languages:
        language = "en-us"
    return languages.get(language)


def _known_vosk_dirnames() -> set[str]:
    names: set[str] = set()
    for info in VOSK_MODEL_INFO.values():
        if isinstance(info, dict):
            names.update(_vosk_language_map(info).values())
    return names


def list_downloaded_vosk_models() -> list[DownloadedVoskModel]:
    """Return unique user-installed VOSK model directories.

    System-wide preinstalled models are ignored; only ``models_dir()`` is
    scanned so Settings can offer deletion without touching package files.
    """
    seen: set[str] = set()
    found: list[DownloadedVoskModel] = []
    models_root = models_dir()
    for size, info in VOSK_MODEL_INFO.items():
        if not isinstance(info, dict):
            continue
        size_mb_raw = info.get("size_mb", 0)
        size_mb = int(size_mb_raw) if isinstance(size_mb_raw, (int, float)) else 0
        for language, dirname in _vosk_language_map(info).items():
            if dirname in seen:
                continue
            path = os.path.join(models_root, dirname)
            if os.path.isdir(path):
                seen.add(dirname)
                found.append(
                    DownloadedVoskModel(
                        dirname=dirname,
                        language=language,
                        size=size,
                        size_mb=size_mb,
                        path=path,
                    )
                )
    return found


def delete_vosk_model(dirname: str) -> str:
    """Delete a user-installed VOSK model directory.

    Returns:
        The removed filesystem path.

    Raises:
        ValueError: Unknown model name, or path outside the models directory.
        FileNotFoundError: The model directory is not present.
        OSError: The directory could not be removed.
    """
    if dirname not in _known_vosk_dirnames() or os.path.basename(dirname) != dirname:
        raise ValueError(f"Unknown VOSK model: {dirname}")

    path = os.path.join(models_dir(), dirname)
    if not is_within_directory(path, models_dir()):
        raise ValueError("Refusing to delete a path outside the models directory")
    if not os.path.isdir(path):
        raise FileNotFoundError(path)

    shutil.rmtree(path)
    logger.info("Deleted VOSK model %s (%s)", dirname, path)
    return path

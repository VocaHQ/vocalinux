"""Faster-Whisper model information for Vocalinux.

Metadata and checksum-gated download URLs for the optional faster-whisper
backend (CTranslate2). Bundles are stored under ``models_dir()/faster_whisper/``
and each file is verified against ``model_checksums.txt`` before the engine
loads it, the same way Parakeet and whisper.cpp models are.
"""

import logging
import os
import shutil
from functools import lru_cache
from typing import Any, Dict, Optional

from .paths import is_within_directory, models_dir

logger = logging.getLogger(__name__)

_HF_BASE_URL = "https://huggingface.co"

# Each bundle is pinned to a Hugging Face commit rather than tracking main, so
# a file replaced upstream cannot change what an install downloads.
FASTER_WHISPER_MODEL_INFO: Dict[str, Dict[str, Any]] = {
    "tiny": {
        "repo": "Systran/faster-whisper-tiny",
        "revision": "d90ca5fe260221311c53c58e660288d3deb8d356",
        "size_mb": 39,
        "params": "39M",
        "desc": "Fastest, lowest accuracy",
    },
    "tiny.en": {
        "repo": "Systran/faster-whisper-tiny.en",
        "revision": "0d3d19a32d3338f10357c0889762bd8d64bbdeba",
        "size_mb": 39,
        "params": "39M",
        "desc": "English-only tiny model",
    },
    "base": {
        "repo": "Systran/faster-whisper-base",
        "revision": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
        "size_mb": 74,
        "params": "74M",
        "desc": "Fast, good for basic use",
    },
    "base.en": {
        "repo": "Systran/faster-whisper-base.en",
        "revision": "3d3d5dee26484f91867d81cb899cfcf72b96be6c",
        "size_mb": 74,
        "params": "74M",
        "desc": "English-only base model",
    },
    "small": {
        "repo": "Systran/faster-whisper-small",
        "revision": "536b0662742c02347bc0e980a01041f333bce120",
        "size_mb": 244,
        "params": "244M",
        "desc": "Balanced speed/accuracy",
    },
    "small.en": {
        "repo": "Systran/faster-whisper-small.en",
        "revision": "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
        "size_mb": 244,
        "params": "244M",
        "desc": "English-only small model",
    },
    "medium": {
        "repo": "Systran/faster-whisper-medium",
        "revision": "08e178d48790749d25932bbc082711ddcfdfbc4f",
        "size_mb": 769,
        "params": "769M",
        "desc": "High accuracy, slower",
    },
    "medium.en": {
        "repo": "Systran/faster-whisper-medium.en",
        "revision": "a29b04bd15381511a9af671baec01072039215e3",
        "size_mb": 769,
        "params": "769M",
        "desc": "English-only medium model",
    },
    "large-v1": {
        "repo": "Systran/faster-whisper-large-v1",
        "revision": "b07c8d4be0be90092aa01a29c975077acb8d15c9",
        "size_mb": 1550,
        "params": "1550M",
        "desc": "Legacy large v1 model",
    },
    "large-v2": {
        "repo": "Systran/faster-whisper-large-v2",
        "revision": "f0fe81560cb8b68660e564f55dd99207059c092e",
        "size_mb": 1550,
        "params": "1550M",
        "desc": "Legacy large v2 model",
    },
    "large-v3": {
        "repo": "Systran/faster-whisper-large-v3",
        "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
        "size_mb": 1550,
        "params": "1550M",
        "desc": "Highest accuracy, slower",
    },
}

_DEFAULT_MODEL_FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
_LARGE_V3_MODEL_FILES = [
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
]


def model_files(model_name: str) -> list[str]:
    """Return the files that make up a faster-whisper CTranslate2 bundle."""
    if model_name not in FASTER_WHISPER_MODEL_INFO:
        raise ValueError(f"Unknown faster-whisper model: {model_name}")
    if model_name == "large-v3":
        return list(_LARGE_V3_MODEL_FILES)
    return list(_DEFAULT_MODEL_FILES)


def get_model_path(model_name: str) -> str:
    """
    Get the path where a model should be stored.

    Args:
        model_name: Name of the model (for example tiny)

    Returns:
        Path to the model directory
    """
    faster_whisper_dir = os.path.join(models_dir(), "faster_whisper")
    os.makedirs(faster_whisper_dir, exist_ok=True)

    return os.path.join(faster_whisper_dir, model_name)


def is_model_downloaded(model_name: str) -> bool:
    """
    Check if a faster-whisper model is downloaded.

    Args:
        model_name: Name of the model

    Returns:
        True if every bundle file exists under MODELS_DIR, False otherwise
    """
    if model_name not in FASTER_WHISPER_MODEL_INFO:
        return False

    model_path = get_model_path(model_name)
    return all(
        os.path.exists(os.path.join(model_path, filename)) for filename in model_files(model_name)
    )


def list_downloaded_models() -> list[str]:
    """Return faster-whisper models occupying disk, complete or partially downloaded.

    Mirrors the Parakeet helper in listing anything present so Settings can offer
    deletion; a cancelled download leaves files behind that must be reclaimable.
    """
    return [name for name in FASTER_WHISPER_MODEL_INFO if os.path.isdir(get_model_path(name))]


def delete_model(model_name: str) -> str:
    """Delete a downloaded faster-whisper model directory.

    Returns:
        The removed filesystem path.

    Raises:
        ValueError: Unknown model name, or path outside the models directory.
        FileNotFoundError: The model directory is not present.
        OSError: The directory could not be removed.
    """
    if model_name not in FASTER_WHISPER_MODEL_INFO or os.path.basename(model_name) != model_name:
        raise ValueError(f"Unknown faster-whisper model: {model_name}")

    path = get_model_path(model_name)
    if not is_within_directory(path, models_dir()):
        raise ValueError("Refusing to delete a path outside the models directory")
    if not os.path.isdir(path):
        raise FileNotFoundError(path)

    shutil.rmtree(path)
    logger.info("Deleted faster-whisper model %s (%s)", model_name, path)
    return path


def manifest_key(model_name: str, filename: str) -> str:
    """Key this bundle file is pinned under in model_checksums.txt.

    Several bundles ship the same file names, so the model name is part of the
    key rather than the bare filename other engines use.
    """
    return f"faster-whisper-{model_name}-{filename}"


def get_model_file_url(model_name: str, filename: str) -> str:
    """
    Get the download URL for one file of a faster-whisper model.

    Args:
        model_name: Name of the model
        filename: File within the model bundle

    Returns:
        Hugging Face download URL
    """
    model_info = FASTER_WHISPER_MODEL_INFO.get(model_name)
    if not model_info:
        raise ValueError(f"Unknown faster-whisper model: {model_name}")

    return (
        f"{_HF_BASE_URL}/{model_info['repo']}/resolve/{model_info['revision']}"
        f"/{filename}?download=true"
    )


@lru_cache(maxsize=1)
def _has_torch_cuda() -> bool:
    """Return True if PyTorch reports CUDA available."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def get_recommended_model() -> tuple[str, str]:
    """Get the recommended faster-whisper model based on system configuration.

    Returns:
        Tuple of (model_name, reason)
    """
    try:
        import psutil

        ram_gb = int(psutil.virtual_memory().total) // (1024**3)
    except Exception:
        ram_gb = 4

    has_cuda = _has_torch_cuda()

    if has_cuda:
        if ram_gb >= 8:
            return "small", f"CUDA GPU with {ram_gb}GB RAM"
        return "base", f"CUDA GPU with {ram_gb}GB RAM"

    if ram_gb >= 16:
        return "base", f"{ram_gb}GB RAM - CPU inference"
    if ram_gb >= 8:
        return "tiny", f"{ram_gb}GB RAM - optimized for speed"
    return "tiny", f"Limited RAM ({ram_gb}GB) - fastest model"


def get_compute_type(device: str) -> str:
    """Return the recommended compute type for the given device.

    Args:
        device: "cpu" or "cuda"

    Returns:
        A faster-whisper compute_type value.
    """
    if device == "cpu":
        return "int8"
    return "float16"


def is_english_only_model(model_name: str) -> bool:
    """Return whether a faster-whisper model variant is English-only."""
    return ".en" in model_name.lower()

"""Faster-Whisper model information for Vocalinux.

This module provides model metadata for the faster-whisper backend. Models are
downloaded automatically by faster-whisper on first use and cached in the
HuggingFace cache directory.
"""

import logging
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)

# Model size -> metadata (size_mb, params, description)
_FASTER_WHISPER_MODEL_SPECS = [
    ("tiny", 39, "39M", "Fastest, lowest accuracy"),
    ("tiny.en", 39, "39M", "English-only tiny model"),
    ("base", 74, "74M", "Fast, good for basic use"),
    ("base.en", 74, "74M", "English-only base model"),
    ("small", 244, "244M", "Balanced speed/accuracy"),
    ("small.en", 244, "244M", "English-only small model"),
    ("medium", 769, "769M", "High accuracy, slower"),
    ("medium.en", 769, "769M", "English-only medium model"),
    ("large-v1", 1550, "1550M", "Legacy large v1 model"),
    ("large-v2", 1550, "1550M", "Legacy large v2 model"),
    ("large-v3", 1550, "1550M", "Highest accuracy, slower"),
]

FASTER_WHISPER_MODEL_INFO = {
    spec[0]: {
        "size_mb": spec[1],
        "params": spec[2],
        "desc": spec[3],
    }
    for spec in _FASTER_WHISPER_MODEL_SPECS
}

AVAILABLE_MODELS = list(FASTER_WHISPER_MODEL_INFO.keys())

MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


def _repo_id(model_name: str) -> str:
    """Return the HuggingFace repo ID for a faster-whisper model size."""
    return f"Systran/faster-whisper-{model_name}"


def _hf_hub_cache() -> Optional[str]:
    """Return the HuggingFace cache directory, if available."""
    try:
        from huggingface_hub import constants

        cache_dir = constants.HF_HUB_CACHE
        if cache_dir is None:
            return None
        return str(cache_dir)
    except Exception:
        return None


def is_model_downloaded(model_name: str) -> bool:
    """Check whether a faster-whisper model is present in the HuggingFace cache.

    Args:
        model_name: The faster-whisper model name (e.g. "tiny", "base")

    Returns:
        True if the model appears to be cached locally.
    """
    if model_name not in FASTER_WHISPER_MODEL_INFO:
        return False

    try:
        from huggingface_hub import try_to_load_from_cache
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE

        repo_id = _repo_id(model_name)
        cache_path = try_to_load_from_cache(repo_id, "model.bin", cache_dir=HUGGINGFACE_HUB_CACHE)
        return cache_path is not None and not str(cache_path).endswith(".lock")
    except Exception:
        pass

    # Fallback: check the expected cache directory structure.
    cache_dir = _hf_hub_cache()
    if cache_dir is None:
        return False

    try:
        import os

        repo_id = _repo_id(model_name)
        repo_dir = repo_id.replace("/", "--")
        model_cache = os.path.join(cache_dir, f"models--{repo_dir}")
        if not os.path.isdir(model_cache):
            return False

        # Look for any snapshot directory containing a model.bin file.
        snapshots_dir = os.path.join(model_cache, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return False

        for snapshot in os.listdir(snapshots_dir):
            snapshot_path = os.path.join(snapshots_dir, snapshot)
            if os.path.isdir(snapshot_path) and os.path.exists(
                os.path.join(snapshot_path, "model.bin")
            ):
                return True

        return False
    except Exception as e:
        logger.debug(f"Could not check faster-whisper model cache: {e}")
        return False


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

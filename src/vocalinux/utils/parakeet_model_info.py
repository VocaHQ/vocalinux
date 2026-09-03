"""
Parakeet model information for Vocalinux.

This module provides model metadata and download URLs for the Parakeet
engine, which runs NVIDIA NeMo ASR models through sherpa-onnx.
"""

import logging
import os
import shutil

from .paths import is_within_directory, models_dir

logger = logging.getLogger(__name__)

# Parakeet model information
# Models are downloaded from Hugging Face as sherpa-onnx ONNX bundles.
_PARAKEET_REPO = "https://huggingface.co"

PARAKEET_MODEL_INFO = {
    "v3-european": {
        "repo": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "size_mb": 639,
        "desc": "Parakeet TDT 0.6B v3 (int8), 25 European languages",
    },
    "v2-english": {
        "repo": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        "size_mb": 630,
        "desc": "Parakeet TDT 0.6B v2 (int8), English",
    },
}

MODEL_SIZES = ["v3-european", "v2-english"]

# Model offered when the engine has nothing downloaded yet.
RECOMMENDED_MODEL = "v3-european"
RECOMMENDED_REASON = "25 European languages"

# Files that make up a sherpa-onnx transducer bundle.
MODEL_FILES = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]


def get_model_path(model_name: str) -> str:
    """
    Get the path where a model should be stored.

    Args:
        model_name: Name of the model (for example v3-european)

    Returns:
        Path to the model directory
    """
    parakeet_dir = os.path.join(models_dir(), "parakeet")
    os.makedirs(parakeet_dir, exist_ok=True)

    return os.path.join(parakeet_dir, model_name)


def is_model_downloaded(model_name: str) -> bool:
    """
    Check if a Parakeet model is downloaded.

    Args:
        model_name: Name of the model

    Returns:
        True if model exists, False otherwise
    """
    model_path = get_model_path(model_name)
    return all(os.path.exists(os.path.join(model_path, f)) for f in MODEL_FILES)


def list_downloaded_models() -> list[str]:
    """Return Parakeet models occupying disk, complete or partially downloaded.

    Mirrors the VOSK helper in listing anything present so Settings can offer
    deletion; a cancelled download leaves files behind that must be reclaimable.
    """
    return [name for name in MODEL_SIZES if os.path.isdir(get_model_path(name))]


def delete_model(model_name: str) -> str:
    """Delete a downloaded Parakeet model directory.

    Returns:
        The removed filesystem path.

    Raises:
        ValueError: Unknown model name, or path outside the models directory.
        FileNotFoundError: The model directory is not present.
        OSError: The directory could not be removed.
    """
    if model_name not in PARAKEET_MODEL_INFO or os.path.basename(model_name) != model_name:
        raise ValueError(f"Unknown Parakeet model: {model_name}")

    path = get_model_path(model_name)
    if not is_within_directory(path, models_dir()):
        raise ValueError("Refusing to delete a path outside the models directory")
    if not os.path.isdir(path):
        raise FileNotFoundError(path)

    shutil.rmtree(path)
    logger.info("Deleted Parakeet model %s (%s)", model_name, path)
    return path


def get_model_file_url(model_name: str, filename: str) -> str:
    """
    Get the download URL for one file of a Parakeet model.

    Args:
        model_name: Name of the model
        filename: File within the model bundle

    Returns:
        Hugging Face download URL
    """
    model_info = PARAKEET_MODEL_INFO.get(model_name)
    if not model_info:
        raise ValueError(f"Unknown Parakeet model: {model_name}")

    return f"{_PARAKEET_REPO}/{model_info['repo']}/resolve/main/{filename}?download=true"

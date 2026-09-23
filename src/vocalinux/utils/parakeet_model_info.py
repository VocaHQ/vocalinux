"""
Parakeet model information for Vocalinux.

This module provides model metadata and download URLs for the Parakeet
engine, which runs NVIDIA NeMo ASR models through sherpa-onnx.
"""

import json
import logging
import os
import shutil
from typing import Any, Dict

from .paths import is_within_directory, models_dir

logger = logging.getLogger(__name__)

# Parakeet model information
# Models are downloaded from Hugging Face as sherpa-onnx ONNX bundles.
#
# Each bundle is pinned to a Hugging Face commit rather than tracking main, so
# a file replaced upstream cannot change what an install downloads.
_HF_BASE_URL = "https://huggingface.co"

PARAKEET_MODEL_INFO: Dict[str, Dict[str, Any]] = {
    "orukeet-v0.1.0": {
        "repo": "oruk/orukeet",
        "revision": "eac739d754bb171287930e6e63386f5b88f8179e",
        "subdir": "onnx/sherpa-v0.1.0-int8",
        "manifest": "manifest.json",
        "files": [
            "manifest.json",
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
            "bpe.vocab",
            "LICENSE-WEIGHTS",
            "NOTICE.md",
        ],
        "size_mb": 641,
        "desc": "Orukeet v0.1.0 (int8), 25 European languages; CC BY-SA 4.0",
    },
    "v3-european": {
        "repo": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
        "revision": "2bda32ec70b097a55adaa07d9a7173915b43cc78",
        "size_mb": 639,
        "desc": "Parakeet TDT 0.6B v3 (int8), 25 European languages",
    },
    "v2-english": {
        "repo": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        "revision": "1ab9323565ddb038682214b292f588070a538ce2",
        "size_mb": 630,
        "desc": "Parakeet TDT 0.6B v2 (int8), English",
    },
}

MODEL_SIZES = ["v3-european", "v2-english", "orukeet-v0.1.0"]

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
    return all(os.path.exists(os.path.join(model_path, f)) for f in model_files(model_name))


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


def manifest_key(model_name: str, filename: str) -> str:
    """Key this bundle file is pinned under in model_checksums.txt.

    Several bundles ship the same file names, so the model name is part of the
    key rather than the bare filename other engines use.
    """
    return f"parakeet-{model_name}-{filename}"


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

    relative = "/".join(part for part in (model_info.get("subdir", ""), filename) if part)
    return (
        f"{_HF_BASE_URL}/{model_info['repo']}/resolve/{model_info['revision']}"
        f"/{relative}?download=true"
    )


def model_files(model_name: str) -> list[str]:
    """Return this model's runtime files, release manifest, and license notices."""
    return list(PARAKEET_MODEL_INFO[model_name].get("files", MODEL_FILES))


def validate_release_manifest(model_name: str, model_dir: str) -> None:
    """Check the downloaded publisher manifest against the app's pinned files."""
    from .model_checksums import ChecksumError, expected_for

    filename = PARAKEET_MODEL_INFO[model_name].get("manifest")
    if not filename:
        return
    try:
        with open(os.path.join(model_dir, filename), encoding="utf-8") as source:
            manifest = json.load(source)
        published = {record["path"]: record for record in manifest["files"]}
        for name in model_files(model_name):
            if name == filename:
                continue
            expected = expected_for(manifest_key(model_name, name))
            record = published.get(name)
            if (
                expected is None
                or record is None
                or expected.algo != "sha256"
                or expected.digest != record["sha256"]
                or expected.size != record["bytes"]
            ):
                raise ChecksumError(f"Release manifest disagrees with pinned Parakeet file: {name}")
    except (KeyError, TypeError, ValueError) as error:
        raise ChecksumError(f"Malformed Parakeet release manifest: {filename}") from error

"""Download URLs and file names for OpenAI Whisper checkpoints.

The file name is derived from the URL rather than from the catalog name, because
that is what `openai-whisper` does. Deriving it as f"{size}.pt" instead is what
made "large" (stored as large-v3.pt) download twice and never show as present.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_BASE = "https://openaipublic.azureedge.net/main/whisper/models"

#: Catalog name -> upstream URL. The path segment before the file name is the
#: checkpoint's sha256; openai-whisper verifies against it on load.
WHISPER_MODEL_URLS = {
    "tiny": f"{_BASE}/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
    "base": f"{_BASE}/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
    "small": f"{_BASE}/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
    "medium": f"{_BASE}/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
    "large": f"{_BASE}/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt",
}

#: Catalog names the UI offers for the OpenAI Whisper engine.
WHISPER_MODEL_SIZES = list(WHISPER_MODEL_URLS)


def whisper_model_url(model_size: str) -> str:
    """Return the upstream URL for ``model_size``."""
    try:
        return WHISPER_MODEL_URLS[model_size]
    except KeyError:
        raise ValueError(f"Unknown Whisper model size: {model_size}") from None


def whisper_model_file(model_size: str) -> str:
    """Return the file name ``openai-whisper`` stores for ``model_size``."""
    return os.path.basename(whisper_model_url(model_size))


def migrate_legacy_checkpoint_names(cache_dir: str) -> list[str]:
    """Rename checkpoints saved under the old f"{size}.pt" name. Returns the new names.

    Vocalinux's own downloader used to name every checkpoint after the catalog
    entry, which is wrong wherever upstream publishes a versioned file: "large"
    is stored as large-v3.pt. A file left under the old name is invisible three
    times over. load_model() looks for the upstream name and refetches 2.9GB,
    Settings does not list it, and because it is not listed it cannot be deleted
    from there either, so the disk stays occupied with no way to reclaim it from
    the UI.

    Renaming is safe rather than lucky: the old downloader fetched "large" from
    the same large-v3 URL it uses today, so the bytes already are that
    checkpoint. And ``openai-whisper`` verifies whatever it loads against the
    sha256 in the URL, so even a wrong guess here costs at most the refetch that
    would have happened anyway.
    """
    renamed = []
    for size in WHISPER_MODEL_URLS:
        upstream = whisper_model_file(size)
        legacy = f"{size}.pt"
        if legacy == upstream:
            continue
        legacy_path = os.path.join(cache_dir, legacy)
        upstream_path = os.path.join(cache_dir, upstream)
        if not os.path.isfile(legacy_path) or os.path.exists(upstream_path):
            continue
        try:
            os.rename(legacy_path, upstream_path)
        except OSError as error:
            # Not fatal: the only cost is the refetch this would have avoided.
            logger.warning("Could not rename %s to %s: %s", legacy_path, upstream, error)
            continue
        logger.info("Renamed legacy Whisper checkpoint %s to %s", legacy, upstream)
        renamed.append(upstream)
    return renamed

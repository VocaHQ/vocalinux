"""Download URLs and file names for OpenAI Whisper checkpoints.

The file name is derived from the URL rather than from the catalog name, because
that is what `openai-whisper` does. Deriving it as f"{size}.pt" instead is what
made "large" (stored as large-v3.pt) download twice and never show as present.
"""

from __future__ import annotations

import os

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

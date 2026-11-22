"""The optional English Fourier GGUF, served from its publisher's pinned revision."""

from pathlib import Path

from .paths import models_dir

MODEL_ID = "fourier-2b-q8"
FILENAME = "Fourier-2B-Q8_0.gguf"
REPO = "oruk/oruk-fourier-2b"
REVISION = "8bcce21695e4ba13569c48de6cedffcb8a7576f5"
URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{FILENAME}"
MODEL_INFO = {
    "size_mb": 2185,
    "desc": "English dictation on CPU. Model license: CC BY-NC 4.0 (noncommercial use).",
    "url": URL,
}


def model_path() -> Path:
    return Path(models_dir()) / "fourier" / FILENAME

"""Local, final-utterance English dictation with transcribe.cpp."""

from contextlib import ExitStack
from threading import Lock
from typing import Any

import numpy as np

from ...utils.fourier_model_info import model_path
from ...utils.model_checksums import verify_model_file


class FourierEngine:
    """Hold one CPU model and inference session until Vocalinux unloads the engine."""

    def __init__(self) -> None:
        self._resources = ExitStack()
        self._session: Any = None
        self._lock = Lock()

    def init(self) -> None:
        from transcribe_cpp import Model

        with self._lock:
            if self._session is not None:
                return
            path = model_path()
            verify_model_file(str(path))
            with ExitStack() as stack:
                model = stack.enter_context(Model(str(path), backend="cpu"))
                session = stack.enter_context(model.session())
                self._resources = stack.pop_all()
                self._session = session

    def is_ready(self) -> bool:
        with self._lock:
            return self._session is not None

    def transcribe(self, audio_buffer: list[bytes]) -> str:
        raw = b"".join(audio_buffer)
        if not raw:
            return ""
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        with self._lock:
            if self._session is None:
                raise RuntimeError("Fourier is not loaded")
            return str(self._session.run(samples, language="en", timestamps="none").text).strip()

    def cleanup(self) -> None:
        with self._lock:
            self._session = None
            self._resources.close()

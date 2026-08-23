"""Integrity verification for downloaded speech models.

Vocalinux pulls 40MB-2GB model files from Hugging Face, Alphacephei and
openaipublic.azureedge.net, then feeds them to native code -- whisper.cpp maps
its ggml files through ``ctypes.cdll``. A tampered or truncated model is
therefore not merely a bad transcription, so every download is checked against a
digest pinned in this repository before it is moved into place.

One source of truth, consulted without a network lookup: ``model_checksums.txt``
next to this module pins a sha256 per file name, for whisper.cpp (the
``lfs.oid`` at the pinned Hugging Face revision) and for VOSK (the hash of the
bytes the generator downloaded; the md5 Alphacephei publishes beside a model
pins nothing they could not change alongside it). Regenerate it with
``scripts/generate-model-checksums.py``.

OpenAI Whisper ``.pt`` checkpoints are absent from it: ``openai-whisper``
downloads and verifies those itself, against the sha256 it reads out of the URL
path, so Vocalinux neither fetches nor hashes them. ``install.sh`` does preinstall
the tiny checkpoint, and verifies it there with its own bash implementation.

Verification fails closed: a file with no pinned digest is an error, not a
warning. ``tests/test_model_checksums.py`` asserts the manifest covers every
model the application can download, so that strictness is caught in CI rather
than on a user's machine.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from functools import lru_cache
from typing import Dict, NamedTuple, Optional

logger = logging.getLogger(__name__)

_MANIFEST_NAME = "model_checksums.txt"

# Written into an extracted model tree to record the digest of the archive it
# came out of. A directory has no hash of its own and the zip is deleted after
# unpacking, so this file is the only evidence the tree was ever verified.
# install.sh reads it under the same name; keep the two in step.
VERIFICATION_STAMP_NAME = ".vocalinux_verified"

# Hash of a 2GB model read in one go would sit in RAM; stream it instead.
_CHUNK_SIZE = 1024 * 1024

_REVISION_HEADER = re.compile(r"^#\s*whispercpp-revision:\s*([0-9a-f]{7,40})\s*$")


class ChecksumError(Exception):
    """A downloaded model did not match its pinned digest, or has no pin at all."""


class Expected(NamedTuple):
    """The pinned identity of one artifact."""

    algo: str
    digest: str
    size: int


def _manifest_text() -> str:
    """Read the manifest from the installed package, falling back to the source tree.

    A missing manifest yields an empty one rather than an import-time crash: the
    consequence is that every model then lacks a pin and is refused by
    :func:`verify_model_file`, which is the safe direction to fail.
    """
    try:
        from importlib.resources import files

        return files(__package__).joinpath(_MANIFEST_NAME).read_text(encoding="utf-8")
    except (ImportError, TypeError, ModuleNotFoundError):
        pass
    except (FileNotFoundError, OSError):
        return ""

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), _MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        logger.error("%s is missing; no model download can be verified", _MANIFEST_NAME)
        return ""


@lru_cache(maxsize=1)
def _parse_manifest() -> tuple[Dict[str, Expected], str]:
    entries: Dict[str, Expected] = {}
    revision = ""

    for line in _manifest_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            match = _REVISION_HEADER.match(stripped)
            if match:
                revision = match.group(1)
            continue

        fields = stripped.split()
        if len(fields) != 4:
            logger.warning("Ignoring malformed line in %s: %r", _MANIFEST_NAME, line)
            continue
        filename, algo, digest, size = fields
        entries[filename] = Expected(algo=algo, digest=digest.lower(), size=int(size))

    return entries, revision


#: Branch to build URLs from when the manifest pins no revision. Only reachable
#: with a missing or hand-damaged manifest, and deliberately not fatal: URL
#: construction runs at import time, whereas refusing an unverifiable file is
#: :func:`verify_model_file`'s job. A download made from this fallback still has
#: no pinned digest, so it is rejected before it is installed.
_UNPINNED_REVISION = "main"


def whispercpp_revision() -> str:
    """The pinned Hugging Face commit the whisper.cpp digests were taken at."""
    _, revision = _parse_manifest()
    if not revision:
        logger.warning(
            "%s pins no whisper.cpp revision; falling back to %r. Downloads will "
            "fail verification until it is regenerated with "
            "scripts/generate-model-checksums.py.",
            _MANIFEST_NAME,
            _UNPINNED_REVISION,
        )
        return _UNPINNED_REVISION
    return revision


def expected_for(filename: str) -> Optional[Expected]:
    """Return the pinned digest for a model file name, or None when unpinned."""
    entries, _ = _parse_manifest()
    return entries.get(os.path.basename(filename))


def write_verification_stamp(tree_path: str, archive_name: str) -> None:
    """Record inside ``tree_path`` the pinned digest of the archive it came from.

    Only archives get a digest, so an extracted tree is trustworthy later only if
    something writes down what was checked. ``install.sh`` re-downloads any VOSK
    model whose stamp does not match the digest pinned today, which means a tree
    left unstamped here — a first-run or Settings download — is refetched on the
    next ``./install.sh``. That makes a failed write an error, not a warning.
    """
    expected = expected_for(archive_name)
    if expected is None:
        raise ChecksumError(f"Cannot stamp {tree_path}: {archive_name} has no pinned digest")
    stamp = os.path.join(tree_path, VERIFICATION_STAMP_NAME)
    with open(stamp, "w", encoding="utf-8") as handle:
        handle.write(f"{expected.digest}\n")
    logger.debug("Recorded verified digest for %s in %s", archive_name, stamp)


def pinned_filenames() -> frozenset:
    """Every file name the manifest pins. Used by the coverage test."""
    entries, _ = _parse_manifest()
    return frozenset(entries)


def file_digest(path: str, algo: str) -> str:
    """Stream ``path`` through ``algo`` and return the lowercase hex digest."""
    try:
        digest = hashlib.new(algo)
    except ValueError as exc:
        raise ChecksumError(f"Unsupported checksum algorithm {algo!r}") from exc

    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str, expected: Expected, *, description: str = "") -> None:
    """Raise :class:`ChecksumError` unless ``path`` matches ``expected``.

    The size is checked first: it is free, and a truncated download (the common
    case) is then reported as a truncated download rather than as a hash
    mismatch that reads like tampering.
    """
    label = description or os.path.basename(path)

    if expected.size:
        actual_size = os.path.getsize(path)
        if actual_size != expected.size:
            raise ChecksumError(
                f"{label} is {actual_size} bytes, expected {expected.size}. "
                "The download was truncated or the file was replaced upstream."
            )

    actual = file_digest(path, expected.algo)
    if actual != expected.digest:
        raise ChecksumError(
            f"{label} failed {expected.algo} verification.\n"
            f"  expected: {expected.digest}\n"
            f"  actual:   {actual}\n"
            "The file does not match the digest pinned in this release. Delete it "
            "and retry; if it keeps failing, do not use it."
        )

    logger.info("%s verified (%s)", label, expected.algo)


def verify_model_file(path: str, filename: Optional[str] = None) -> None:
    """Verify a downloaded model against the manifest.

    ``filename`` overrides the lookup key when ``path`` is still a temporary
    name such as ``ggml-tiny.bin.tmp``.
    """
    key = filename or os.path.basename(path)
    expected = expected_for(key)
    if expected is None:
        raise ChecksumError(
            f"No checksum is pinned for {key}. Regenerate "
            f"{_MANIFEST_NAME} with scripts/generate-model-checksums.py."
        )
    verify_file(path, expected, description=key)

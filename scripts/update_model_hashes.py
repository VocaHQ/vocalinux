#!/usr/bin/env python3
"""
Regenerate the pinned model checksum registry (``model_hashes.json``).

Every model Vocalinux can download is listed in the registry with the SHA256
digest and byte size of the exact file we expect upstream to serve. The runtime
verifies downloads against those pins, so this script is how a maintainer
records or refreshes them.

Where each digest comes from:

- **whisper.cpp** — the Hugging Face repository API exposes the Git LFS SHA256
  of every blob, so digests are read from metadata without downloading gigabytes
  of weights.
- **Whisper** — OpenAI embeds the SHA256 of each checkpoint in its download URL
  (``.../models/<sha256>/tiny.pt``); the upstream client verifies against the
  same value, so the digest is taken from the URL and the size is read from a
  HEAD request.
- **VOSK** — Alphacephei publishes no SHA256, so each archive is streamed and
  hashed. The MD5 and size published in their ``model-list.json`` are used as an
  independent cross-check on the bytes we hashed.

Usage:
    python scripts/update_model_hashes.py                  # refresh everything
    python scripts/update_model_hashes.py --source vosk    # one source only
    python scripts/update_model_hashes.py --jobs 8         # parallel VOSK hashing

Digests are only ever added or replaced after being fetched successfully; a
source that fails to download leaves the existing pins untouched.
"""

import argparse
import concurrent.futures
import hashlib
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from vocalinux.utils.model_integrity import REGISTRY_PATH  # noqa: E402
from vocalinux.utils.vosk_model_info import VOSK_MODEL_BASE_URL, VOSK_MODEL_INFO  # noqa: E402
from vocalinux.utils.whisper_model_info import WHISPER_MODEL_URLS  # noqa: E402
from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("update_model_hashes")

HF_REPO_API = "https://huggingface.co/api/models/ggerganov/whisper.cpp?blobs=true"
VOSK_MODEL_LIST_URL = "https://alphacephei.com/vosk/models/model-list.json"
HTTP_TIMEOUT = (15, 300)


def _whispercpp_filenames() -> Dict[str, str]:
    """Map ``ggml-*.bin`` filename -> model name, for every downloadable model."""
    return {
        Path(urlparse(info["url"]).path).name: name for name, info in WHISPERCPP_MODEL_INFO.items()
    }


def collect_whispercpp() -> Dict[str, dict]:
    """Read SHA256 digests for ggml models from the Hugging Face LFS metadata."""
    logger.info("Fetching whisper.cpp blob metadata from Hugging Face")
    response = requests.get(HF_REPO_API, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    blobs = {
        sibling["rfilename"]: sibling["lfs"]
        for sibling in response.json().get("siblings", [])
        if sibling.get("lfs", {}).get("sha256")
    }

    digests: Dict[str, dict] = {}
    for filename in sorted(_whispercpp_filenames()):
        lfs = blobs.get(filename)
        if not lfs:
            logger.warning("No LFS metadata for %s — leaving it unpinned", filename)
            continue
        digests[filename] = {"sha256": lfs["sha256"], "size": int(lfs["size"])}
    logger.info("Pinned %d/%d whisper.cpp models", len(digests), len(_whispercpp_filenames()))
    return digests


def collect_whisper() -> Dict[str, dict]:
    """Take SHA256 digests from OpenAI's URLs and sizes from HEAD requests."""
    digests: Dict[str, dict] = {}
    for size, url in sorted(WHISPER_MODEL_URLS.items()):
        parts = urlparse(url).path.strip("/").split("/")
        sha256 = parts[-2]
        if len(sha256) != 64:
            logger.warning("Unexpected Whisper URL shape, skipping %s: %s", size, url)
            continue
        logger.info("HEAD %s", url)
        response = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if not content_length:
            logger.warning(
                "HEAD for Whisper %s omitted Content-Length; leaving any existing pin untouched",
                size,
            )
            continue
        try:
            size_bytes = int(content_length)
        except ValueError:
            logger.warning(
                "HEAD for Whisper %s had invalid Content-Length %r; leaving existing pin",
                size,
                content_length,
            )
            continue
        filename = Path(urlparse(url).path).name or f"{size}.pt"
        entry = {"sha256": sha256, "size": size_bytes}
        digests[filename] = entry
        alias = f"{size}.pt"
        if alias != filename:
            digests[alias] = dict(entry)
    logger.info("Pinned %d Whisper models", len(digests))
    return digests


def _vosk_model_names() -> set:
    names = set()
    for tier in VOSK_MODEL_INFO.values():
        names.update(name for name in tier["languages"].values() if name)
    return names


def _hash_vosk_archive(name: str) -> Tuple[str, Optional[dict], Optional[str]]:
    """Stream one VOSK archive and return its digest without touching disk."""
    url = f"{VOSK_MODEL_BASE_URL}/{name}.zip"
    sha256 = hashlib.sha256()
    md5 = hashlib.md5()  # cross-check only; Alphacephei publishes MD5, not SHA256
    size = 0
    try:
        with requests.get(url, stream=True, timeout=HTTP_TIMEOUT) as response:
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                sha256.update(chunk)
                md5.update(chunk)
                size += len(chunk)
    except requests.exceptions.RequestException as exc:
        return name, None, f"download failed: {exc}"
    if size == 0:
        return name, None, "downloaded 0 bytes"
    return name, {"sha256": sha256.hexdigest(), "size": size, "md5": md5.hexdigest()}, None


def collect_vosk(jobs: int) -> Dict[str, dict]:
    """Hash every VOSK archive the app can download, cross-checking upstream MD5."""
    logger.info("Fetching Alphacephei model list")
    published = {}
    try:
        response = requests.get(VOSK_MODEL_LIST_URL, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        published = {entry["name"]: entry for entry in response.json()}
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("Could not fetch model-list.json (%s); skipping MD5 cross-check", exc)

    names = sorted(_vosk_model_names())
    logger.info("Hashing %d VOSK archives with %d workers", len(names), jobs)

    digests: Dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for name, digest, error in pool.map(_hash_vosk_archive, names):
            if error:
                logger.warning("%s: %s — leaving it unpinned", name, error)
                continue
            expected = published.get(name)
            if expected:
                if expected.get("md5") != digest["md5"]:
                    logger.error(
                        "%s: MD5 %s does not match published %s — refusing to pin",
                        name,
                        digest["md5"],
                        expected.get("md5"),
                    )
                    continue
                if int(expected.get("size", digest["size"])) != digest["size"]:
                    logger.error("%s: size does not match published value", name)
                    continue
            else:
                logger.warning("%s: not in model-list.json, pinning without cross-check", name)
            digests[f"{name}.zip"] = {"sha256": digest["sha256"], "size": digest["size"]}
            logger.info("%s: %s (%d bytes)", name, digest["sha256"], digest["size"])
    logger.info("Pinned %d/%d VOSK models", len(digests), len(names))
    return digests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=["all", "whispercpp", "whisper", "vosk"],
        default="all",
        help="Which model source to refresh (default: all)",
    )
    parser.add_argument(
        "--jobs", type=int, default=4, help="Parallel downloads when hashing VOSK archives"
    )
    args = parser.parse_args()

    registry = json.loads(REGISTRY_PATH.read_text()) if REGISTRY_PATH.exists() else {}

    if args.source in ("all", "whispercpp"):
        registry.setdefault("whispercpp", {}).update(collect_whispercpp())
    if args.source in ("all", "whisper"):
        registry.setdefault("whisper", {}).update(collect_whisper())
    if args.source in ("all", "vosk"):
        registry.setdefault("vosk", {}).update(collect_vosk(args.jobs))

    registry["_comment"] = (
        "Pinned SHA256 digests for every model Vocalinux downloads. "
        "Regenerate with scripts/update_model_hashes.py; see SECURITY.md."
    )
    registry["_updated"] = date.today().isoformat()
    ordered = {key: registry[key] for key in sorted(registry, key=lambda k: (k[0] != "_", k))}
    for section in ("whispercpp", "whisper", "vosk"):
        if section in ordered:
            ordered[section] = dict(sorted(ordered[section].items()))

    REGISTRY_PATH.write_text(json.dumps(ordered, indent=2) + "\n")
    logger.info("Wrote %s", REGISTRY_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())

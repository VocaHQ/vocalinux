#!/usr/bin/env python3
"""Regenerate src/vocalinux/utils/model_checksums.txt from upstream metadata.

Vocalinux downloads 40MB-2GB speech models at install time and on first run,
then hands them to native code (whisper.cpp loads its ggml files through
``ctypes.cdll``). Nothing about that is safe unless we know what we received,
so every downloader checks the file against a hash pinned *in this repository*
rather than one fetched alongside the download.

Where that hash comes from differs by registry, and so does what generating it
costs:

* whisper.cpp ships on Hugging Face, whose API exposes the sha256 of every LFS
  blob (``lfs.oid``) plus the commit the listing was taken at, so nothing is
  downloaded for it. That commit is pinned too -- the download URLs use it
  instead of ``main``, so upstream retagging a file cannot turn every user's
  install into a checksum failure.
* VOSK is different: ``model-list.json`` carries an md5 per model, but that is a
  metadata field from the same host we are pinning against, so copying it pins
  nothing an attacker could not change alongside the file. Those models are
  downloaded here and pinned by the sha256 of the bytes we actually received;
  the published md5 is checked against them on the way through, so a listing
  that disagrees with its own file is caught at generation time. Downloading is
  incremental -- a model already pinned by sha256 is not fetched again, so only
  new models cost bandwidth. A first run, or any run with --refresh, therefore
  pulls every VOSK zip: ~21.9GB, roughly half an hour on a fast connection.

The model names come from the package itself, so a model added to
vosk_model_info.py or whispercpp_model_info.py is picked up on the next run and
a model that upstream never published fails the generation loudly.

Usage:  just model-checksums   (or: python scripts/generate-model-checksums.py)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Iterable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
MANIFEST = SRC / "vocalinux" / "utils" / "model_checksums.txt"

HF_REPO = "ggerganov/whisper.cpp"
HF_API = f"https://huggingface.co/api/models/{HF_REPO}?blobs=true"
VOSK_MODEL_LIST = "https://alphacephei.com/vosk/models/model-list.json"

TIMEOUT = 60


class Entry(NamedTuple):
    """One verifiable artifact: the file name is the manifest's lookup key."""

    filename: str
    algo: str
    digest: str
    size: int


def _fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "vocalinux-checksum-generator"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.load(response)


def _existing_sha256_entries() -> dict:
    """sha256 entries already in the manifest, so a rerun re-downloads nothing."""
    if not MANIFEST.exists():
        return {}

    entries = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        fields = line.split()
        if len(fields) == 4 and fields[1] == "sha256":
            entries[fields[0]] = Entry(fields[0], "sha256", fields[2], int(fields[3]))
    return entries


def _download_and_hash(url: str, expected_md5: str) -> tuple[str, int]:
    """Stream ``url``, returning the sha256 of the bytes and their length.

    The published md5 is verified on the way through: it is not what we pin, but
    a mismatch means the listing and the file disagree, which is worth stopping
    for rather than pinning either one.
    """
    sha256, md5, size = hashlib.sha256(), hashlib.md5(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "vocalinux-checksum-generator"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)

    if expected_md5 and md5.hexdigest() != expected_md5:
        raise SystemExit(
            f"{url}\n"
            f"  published md5: {expected_md5}\n"
            f"  actual md5:    {md5.hexdigest()}\n"
            "The listing does not describe the file it points at. Refusing to pin either."
        )
    return sha256.hexdigest(), size


def _model_names() -> tuple[list[str], list[str]]:
    """Model names the application can actually download, straight from the package."""
    sys.path.insert(0, str(SRC))
    from vocalinux.utils.vosk_model_info import VOSK_MODEL_INFO
    from vocalinux.utils.whispercpp_model_info import WHISPERCPP_MODEL_INFO, whispercpp_model_file

    vosk = {
        name for info in VOSK_MODEL_INFO.values() for name in info["languages"].values() if name
    }
    whispercpp = {whispercpp_model_file(name) for name in WHISPERCPP_MODEL_INFO}
    return sorted(whispercpp), sorted(vosk)


def _whispercpp_entries(wanted: Iterable[str]) -> tuple[list[Entry], str]:
    payload = _fetch_json(HF_API)
    revision = payload.get("sha")
    if not revision:
        raise SystemExit(f"{HF_API} returned no commit sha; refusing to pin an unknown revision")

    by_name = {}
    for sibling in payload.get("siblings", []):
        lfs = sibling.get("lfs") or {}
        digest = lfs.get("oid") or lfs.get("sha256")
        if digest:
            by_name[sibling["rfilename"]] = (digest, int(lfs.get("size", 0)))

    entries, missing = [], []
    for filename in wanted:
        if filename not in by_name:
            missing.append(filename)
            continue
        digest, size = by_name[filename]
        entries.append(Entry(filename, "sha256", digest, size))

    if missing:
        raise SystemExit(
            f"Hugging Face {HF_REPO}@{revision} publishes no sha256 for: {', '.join(missing)}.\n"
            "Either the model was renamed upstream or whispercpp_model_info.py lists "
            "a file that does not exist."
        )
    return entries, revision


def _vosk_entries(wanted: Iterable[str], refresh: bool) -> list[Entry]:
    payload = _fetch_json(VOSK_MODEL_LIST)
    by_name = {item["name"]: item for item in payload}
    existing = {} if refresh else _existing_sha256_entries()

    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise SystemExit(
            f"{VOSK_MODEL_LIST} does not list: {', '.join(missing)}.\n"
            "Either the model was withdrawn upstream or vosk_model_info.py names "
            "a model Alphacephei never shipped."
        )

    todo = [name for name in wanted if f"{name}.zip" not in existing]
    if todo:
        total = sum(int(by_name[name].get("size", 0)) for name in todo)
        print(f"  downloading {len(todo)} VOSK model(s), {total / 1e9:.1f} GB, to hash the bytes")

    entries = []
    for name in wanted:
        filename = f"{name}.zip"
        if filename in existing:
            entries.append(existing[filename])
            continue

        item = by_name[name]
        print(f"    {name} ({int(item.get('size', 0)) / 1e6:.0f} MB)...", flush=True)
        digest, size = _download_and_hash(item["url"], item.get("md5", ""))
        entries.append(Entry(filename, "sha256", digest, size))

    return entries


def _render(entries: list[Entry], revision: str) -> str:
    width = max(len(entry.filename) for entry in entries)
    lines = [
        "# Checksums for every speech model Vocalinux downloads.",
        "#",
        "# Generated by scripts/generate-model-checksums.py -- do not edit by hand.",
        "# Regenerate with `just model-checksums` after adding a model to",
        "# vosk_model_info.py or whispercpp_model_info.py.",
        "#",
        "# Read by src/vocalinux/utils/model_checksums.py and by install.sh; keep the",
        "# format (filename, algorithm, digest, size in bytes) parseable by awk.",
        "#",
        "# whisper.cpp models are pinned to this Hugging Face commit so upstream",
        "# replacing a file cannot invalidate the digests below.",
        f"# whispercpp-revision: {revision}",
        "#",
        "# OpenAI Whisper (.pt) models are absent on purpose: their download URLs embed",
        "# the sha256 as a path segment, so the expected digest travels with the URL.",
        "#",
        "# VOSK digests are the sha256 of bytes this script downloaded, not the md5",
        "# Alphacephei publishes; that md5 is only checked against them at that point.",
        "",
    ]
    for entry in entries:
        lines.append(
            f"{entry.filename.ljust(width)}  {entry.algo:<6}  {entry.digest}  {entry.size}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download every VOSK model instead of reusing pinned sha256 entries",
    )
    args = parser.parse_args()

    whispercpp_files, vosk_names = _model_names()
    print(f"Resolving {len(whispercpp_files)} whisper.cpp and {len(vosk_names)} VOSK models...")

    whispercpp_entries, revision = _whispercpp_entries(whispercpp_files)
    print(f"  whisper.cpp: {len(whispercpp_entries)} sha256 digests at {HF_REPO}@{revision[:12]}")

    vosk_entries = _vosk_entries(vosk_names, args.refresh)
    print(f"  VOSK: {len(vosk_entries)} sha256 digests")

    MANIFEST.write_text(_render(whispercpp_entries + vosk_entries, revision), encoding="utf-8")
    print(f"Wrote {MANIFEST.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

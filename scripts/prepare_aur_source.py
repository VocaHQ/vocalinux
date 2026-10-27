#!/usr/bin/env python3
"""Prepare the exact AUR source inputs, verifying published release provenance first.

Run with the locked release-build dependency group (provides packaging). Release
mode requires SHA256SUMS and the expected source commit. --local-unattested is
only for PR/local fixtures built by the reproducible-wheel gate, never publishing.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from email.parser import BytesParser
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging/aur/vocalinux/PKGBUILD"
REPOSITORY = "VocaHQ/vocalinux"


def digest(path: Path) -> str:
    """Hash the original archive bytes, without extracting or repacking them."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sdist_version(sdist: Path) -> str:
    """Require one canonical Vocalinux sdist with matching top-level metadata."""
    match = re.fullmatch(r"vocalinux-([0-9][A-Za-z0-9.+!]*)\.tar\.gz", sdist.name)
    if not match:
        raise ValueError("expected a canonical vocalinux-VERSION.tar.gz sdist")
    version = match[1]
    if str(Version(version)) != version:
        raise ValueError("sdist filename version is not canonical")
    root = f"vocalinux-{version}"
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        if any(
            member.name.split("/", 1)[0] != root or ".." in member.name.split("/")
            for member in members
        ):
            raise ValueError("sdist has an unexpected archive root or unsafe member path")
        metadata = [member for member in members if member.name == f"{root}/PKG-INFO"]
        if len(metadata) != 1 or not metadata[0].isfile():
            raise ValueError("sdist must contain exactly one regular top-level PKG-INFO")
        stream = archive.extractfile(metadata[0])
        assert stream is not None
        with stream:
            info = BytesParser().parse(stream)
        if info.get_all("Name") != ["vocalinux"] or info.get_all("Version") != [version]:
            raise ValueError("sdist metadata does not match its filename")
    return version


def verify_release(sdist: Path, manifest: Path, tag: str, commit: str) -> str:
    """Fail closed on missing/mismatched hashes or untrusted release provenance."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("release verification requires a full source commit SHA")
    entries = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
        if not match:
            raise ValueError("malformed SHA256SUMS entry")
        if match[2] == sdist.name:
            entries.append(match[1])
    if len(entries) != 1:
        raise ValueError("SHA256SUMS must pin the sdist exactly once")
    if digest(sdist) != entries[0]:
        raise ValueError("sdist checksum does not match SHA256SUMS")
    subprocess.run(
        [
            "gh",
            "attestation",
            "verify",
            str(sdist),
            "--repo",
            REPOSITORY,
            "--signer-workflow",
            f"{REPOSITORY}/.github/workflows/release.yml",
            "--source-ref",
            f"refs/tags/{tag}",
            "--source-digest",
            commit,
        ],
        check=True,
    )
    return entries[0]


def prepare(
    sdist: Path,
    output: Path,
    tag: str | None = None,
    manifest: Path | None = None,
    commit: str | None = None,
    local_unattested: bool = False,
) -> None:
    """Stage an unchanged sdist and its fully pinned PKGBUILD only after validation."""
    version = sdist_version(sdist)
    tag = tag or (f"v{version}" if local_unattested else "")
    if not re.fullmatch(r"v[0-9][A-Za-z0-9.+!-]*", tag) or Version(tag[1:]) != Version(version):
        raise ValueError("release tag and sdist version do not match")
    if local_unattested:
        if manifest is not None or commit is not None:
            raise ValueError("local-unattested mode cannot take release verification inputs")
        print("UNATTESTED local/PR fixture: not authorized for AUR publication")
        checksum = digest(sdist)
    else:
        if manifest is None or commit is None:
            raise ValueError("release mode requires --manifest and --source-commit")
        checksum = verify_release(sdist, manifest, tag, commit)

    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in {
        "pkgver": tag[1:].replace("-", ""),
        "_tag": tag[1:],
        "_version": version,
        "pkgrel": "1",
        "sha256sums": f"('{checksum}')",
    }.items():
        text, count = re.subn(rf"^{key}=.*$", f"{key}={value}", text, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"PKGBUILD template must assign {key} exactly once")
    if output.exists() or output.is_symlink():
        raise ValueError(f"output already exists; choose a fresh directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".aur-source-", dir=output.parent) as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        shutil.copyfile(sdist, staging / sdist.name)
        if digest(staging / sdist.name) != checksum:
            raise ValueError("sdist changed while staging")
        (staging / "PKGBUILD").write_text(text, encoding="utf-8")
        staging.rename(output)
    print(f"Prepared {tag}: {checksum}  {sdist.name} in {output}")


def main() -> int:
    """Prepare verified release inputs or an explicitly unattested local fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", help="exact v* tag; defaults to the sdist version in local mode")
    parser.add_argument("--manifest", type=Path, help="published SHA256SUMS")
    parser.add_argument("--source-commit", help="expected full commit SHA of the release tag")
    parser.add_argument("--local-unattested", action="store_true", help="PR/local fixture only")
    args = parser.parse_args()
    try:
        prepare(
            args.sdist,
            args.output,
            args.tag,
            args.manifest,
            args.source_commit,
            args.local_unattested,
        )
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

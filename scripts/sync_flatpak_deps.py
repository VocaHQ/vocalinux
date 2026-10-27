#!/usr/bin/env python3
"""Point the Flatpak's dependency manifest at the versions uv.lock resolved.

`packaging/flatpak/python3-dependencies.yaml` was produced once by
flatpak-pip-generator, from a package list typed out by hand on the command
line recorded in its first line, and then hand-edited. Nothing regenerated it
afterwards and no test compared it to anything, so it drifted: by 2026-09-10 ten
of its fifteen shared packages were behind `requirements/runtime.txt`, including
pywhispercpp, which sat at 1.4.1 under the project's own `>=1.5.0` floor. The
Flatpak installs the project with `pip3 install --no-deps`, so that constraint
is never evaluated and nothing there could notice. It now reads
`requirements/vad.txt`, the runtime dependencies plus the `[vad]` extra, so
Silero VAD's onnxruntime ships too (#969).

This script closes the loop the other way round: it reads the hash-pinned export
that `just lock` produces and rewrites every source in the manifest to the
artifact whose digest uv already recorded. The bytes the Flatpak downloads are
then the bytes in `uv.lock`, verified by hash rather than by convention. The
`onnxruntime` sources are selected as CPython-ABI wheels for each Flatpak
architecture because PyPI publishes no sdist for it.

It edits in place rather than regenerating, because two things in that file are
hand-written and no generator produces them: pywhispercpp's Vulkan build with
its version injection, and the symlinking of whisper.cpp's shared libraries onto
the loader path. Keeping the structure keeps the diff to versions and digests.

Usage:
    python scripts/sync_flatpak_deps.py            # rewrite the manifest
    python scripts/sync_flatpak_deps.py --check    # report drift, change nothing

`tests/test_flatpak_packaging.py` asserts the same invariant offline, so CI
catches drift without reaching PyPI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from packaging.markers import Marker
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT = REPO_ROOT / "requirements" / "vad.txt"
DEPS_YAML = REPO_ROOT / "packaging" / "flatpak" / "python3-dependencies.yaml"
MANIFEST = REPO_ROOT / "packaging" / "flatpak" / "com.vocalinux.Vocalinux.yml"

#: The environment the Flatpak build resolves for. GNOME 50 ships Python 3.13.
#: numpy's lock entry splits at `python_full_version >= '3.12'`; onnxruntime's
#: CPython wheel tag also uses this Python version. Bump it when the manifest's
#: runtime-version moves.
TARGET_ENV = {
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "extra": "",
}

#: org.gnome.Platform//50 ships these; a second copy under /app would shadow the
#: runtime's own GI stack. PyGObject is already absent from the export, which
#: `just lock` builds with --no-emit-package pygobject for the same reason.
RUNTIME_PROVIDED = {"pycairo"}

#: onnxruntime has no sdist on PyPI, and building it from source is out of reach
#: in the sandbox. These come as CPython-ABI wheels, one per Flatpak arch, tagged
#: for TARGET_ENV's python_version; a runtime Python bump makes pip --no-index
#: fail loudly at build time rather than silently.
BINARY_ONLY = {"onnxruntime"}
FLATPAK_ARCHES = ("x86_64", "aarch64")

#: Build backends for the sdists the manifest builds offline under
#: --no-build-isolation. They are not runtime dependencies, so they never appear
#: in requirements/vad.txt and stay pinned here by hand.
BUILD_BACKENDS = {"meson-python", "pyproject-metadata"}

PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"


def parse_export(path: Path) -> dict[str, tuple[str, set[str]]]:
    """Map every package the Flatpak target selects to its version and digests.

    uv writes one `name==version [; marker]` line followed by indented
    `--hash=sha256:` lines, continued with backslashes. A package can appear
    more than once under mutually exclusive markers, which is how numpy is
    split across Python versions, so the marker decides rather than the order.
    """
    selected: dict[str, tuple[str, set[str]]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        head = re.match(r"^([A-Za-z0-9._-]+)==([^ ;]+)\s*(?:;\s*(.*))?$", line)
        if head:
            name, version, marker = head.group(1), head.group(2), head.group(3)
            current = None
            if marker and not Marker(marker).evaluate(TARGET_ENV):
                continue
            key = canonicalize_name(name)
            if key in selected:
                raise SystemExit(
                    f"{path.name}: {key} resolves twice for the Flatpak target "
                    f"({selected[key][0]} and {version}); the markers overlap"
                )
            selected[key] = (version, set())
            current = key
            continue
        digest = re.match(r"^--hash=sha256:([0-9a-f]{64})$", line)
        if digest and current:
            selected[current][1].add(digest.group(1))
    return selected


def pypi_artifacts(name: str, version: str) -> list[dict]:
    url = PYPI_JSON.format(name=name, version=version)
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return json.load(response)["urls"]


def choose_artifact(
    name: str, version: str, digests: set[str], arch: str | None = None
) -> tuple[str, str]:
    """The one file the Flatpak should download, as (url, sha256).

    Binary-only packages use an architecture-specific CPython wheel. For every
    other package, prefer a universal wheel and fall back to the sdist so the
    sandbox builds compiled dependencies against the SDK's interpreter.
    """
    artifacts = pypi_artifacts(name, version)
    if name in BINARY_ONLY:
        if arch not in FLATPAK_ARCHES:
            raise SystemExit(
                f"{name} {version}: expected one of the Flatpak architectures "
                f"{', '.join(FLATPAK_ARCHES)}, got {arch!r}"
            )
        python_tag = TARGET_ENV["python_version"].replace(".", "")
        wheel_pattern = re.compile(
            rf"-cp{python_tag}-cp{python_tag}-manylinux_.+_{re.escape(arch)}\.whl$"
        )
        candidates = [
            artifact
            for artifact in artifacts
            if artifact["packagetype"] == "bdist_wheel"
            and wheel_pattern.search(artifact["filename"])
        ]
        if not candidates:
            raise SystemExit(
                f"{name} {version} publishes no CPython cp{python_tag} manylinux "
                f"wheel for {arch}; update the Flatpak Python runtime or package"
            )
    else:
        wheels = [
            artifact
            for artifact in artifacts
            if artifact["packagetype"] == "bdist_wheel"
            and artifact["filename"].endswith("-none-any.whl")
        ]
        sdists = [artifact for artifact in artifacts if artifact["packagetype"] == "sdist"]
        candidates = wheels or sdists
    if not candidates:
        raise SystemExit(
            f"{name} {version} publishes neither a universal wheel nor an sdist; "
            "the Flatpak cannot build it without an ABI-tagged wheel"
        )
    # A release can publish more than one matching wheel; take the first whose
    # digest uv actually locked.
    picked = next((a for a in candidates if a["digests"]["sha256"] in digests), None)
    if picked is None:
        first = candidates[0]
        raise SystemExit(
            f"{name} {version}: PyPI serves {first['filename']} with digest "
            f"{first['digests']['sha256']}, which is not among the hashes uv "
            "locked. Re-run `just lock`."
        )
    return picked["url"], picked["digests"]["sha256"]


def artifact_name(filename: str) -> str:
    if filename.endswith(".whl"):
        return canonicalize_name(filename.split("-")[0])
    base = re.sub(r"\.(tar\.gz|zip|tar\.bz2)$", "", filename)
    return canonicalize_name(base.rpartition("-")[0])


def manifest_sources(text: str) -> list[tuple[int, str, str]]:
    """Every PyPI source in the manifest, as (line index, filename, sha256)."""
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        url = re.match(r"^\s*url: (https://files\.pythonhosted\.org/\S+/([^/\s]+))$", line)
        if not url:
            continue
        digest = re.match(r"^\s*sha256: ([0-9a-f]{64})\s*$", lines[index + 1])
        if not digest:
            raise SystemExit(
                f"{DEPS_YAML.name}:{index + 2}: a PyPI source with no sha256 beneath it"
            )
        found.append((index, url.group(2), digest.group(1)))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change and exit non-zero, without writing",
    )
    args = parser.parse_args()

    locked = parse_export(EXPORT)
    text = DEPS_YAML.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    sources = manifest_sources(text)
    in_manifest = {artifact_name(name) for _, name, _ in sources}
    stale = sorted(in_manifest - set(locked) - BUILD_BACKENDS)
    missing = sorted(set(locked) - in_manifest - RUNTIME_PROVIDED)
    binary_arches = {name: set() for name in BINARY_ONLY}
    for _, filename, _ in sources:
        name = artifact_name(filename)
        if name in BINARY_ONLY:
            arch_match = re.search(r"_(x86_64|aarch64)\.whl$", filename)
            if arch_match:
                binary_arches[name].add(arch_match.group(1))
    for name in BINARY_ONLY & set(locked):
        missing.extend(
            f"{name} ({arch})" for arch in FLATPAK_ARCHES if arch not in binary_arches[name]
        )
    missing.sort()
    if stale:
        print(
            f"{DEPS_YAML.name} builds packages the lock does not resolve: "
            f"{', '.join(stale)}\n"
            "Delete their modules and sources by hand: whether a package is a "
            "build backend the sandbox needs or a leftover this script cannot "
            "tell.",
            file=sys.stderr,
        )
    if missing:
        print(
            f"{DEPS_YAML.name} is missing packages the lock resolves: "
            f"{', '.join(missing)}\n"
            "The Flatpak installs with --no-deps, so a missing one fails at "
            "runtime rather than at build time. Add a module for each.",
            file=sys.stderr,
        )
    if stale or missing:
        return 1

    changes: list[str] = []
    for index, filename, old_sha in sources:
        name = artifact_name(filename)
        if name in BUILD_BACKENDS:
            # Absent from the lock by definition: nothing imports them at
            # runtime, they only let the sandbox build the sdists offline.
            continue
        version, digests = locked[name]
        arch = None
        if name in BINARY_ONLY:
            arch_match = re.search(r"_(x86_64|aarch64)\.whl$", filename)
            if not arch_match:
                raise SystemExit(f"{name}: cannot determine a Flatpak architecture from {filename}")
            arch = arch_match.group(1)
        url, sha = choose_artifact(name, version, digests, arch)
        if sha == old_sha:
            continue
        indent = re.match(r"^(\s*)", lines[index]).group(1)
        lines[index] = f"{indent}url: {url}\n"
        lines[index + 1] = f"{indent}sha256: {sha}\n"
        changes.append(f"  {name}: {filename} -> {url.rsplit('/', 1)[-1]}")

    updated = "".join(lines)

    # pywhispercpp's version is spelled out in its build commands: the sdist
    # carries no version.txt and setup() takes no version= argument, so the
    # module rewrites setup.py before building. setuptools-scm would otherwise
    # read a git tree that does not exist in the sandbox.
    pywhispercpp_version = locked["pywhispercpp"][0]
    updated, injected = re.subn(
        # The version appears as a tarball name, a directory name and a
        # literal inside the setup.py rewrite. Refuse to match rather than
        # match short: a partial match would leave the tail of the old version
        # glued to the new one and rename the directory tar just wrote.
        r"pywhispercpp-\d+(?:\.\d+)*(?![\d.]\d)",
        f"pywhispercpp-{pywhispercpp_version}",
        updated,
    )
    updated = re.sub(
        r"PYWHISPERCPP_VERSION=\d+(?:\.\d+)*",
        f"PYWHISPERCPP_VERSION={pywhispercpp_version}",
        updated,
    )
    updated = re.sub(
        r'(version=\\")\d+(?:\.\d+)*(\\")',
        rf"\g<1>{pywhispercpp_version}\g<2>",
        updated,
    )
    if injected and updated != text and not changes:
        changes.append(f"  pywhispercpp: build commands -> {pywhispercpp_version}")

    manifest_text = MANIFEST.read_text(encoding="utf-8")
    manifest_updated = re.sub(
        r'(PYWHISPERCPP_VERSION: ")\d+(?:\.\d+)*(")',
        rf"\g<1>{pywhispercpp_version}\g<2>",
        manifest_text,
    )

    if updated == text and manifest_updated == manifest_text:
        print(
            "Flatpak dependencies already match requirements/vad.txt "
            "(runtime dependencies plus the [vad] extra)"
        )
        return 0

    if args.check:
        print(
            "Flatpak dependencies are behind requirements/vad.txt "
            "(runtime dependencies plus the [vad] extra):",
            file=sys.stderr,
        )
        for change in changes:
            print(change, file=sys.stderr)
        if manifest_updated != manifest_text:
            print(
                f"  {MANIFEST.name}: PYWHISPERCPP_VERSION -> {pywhispercpp_version}",
                file=sys.stderr,
            )
        print("Run `just flatpak-deps` to update.", file=sys.stderr)
        return 1

    DEPS_YAML.write_text(updated, encoding="utf-8")
    MANIFEST.write_text(manifest_updated, encoding="utf-8")
    print(f"Updated {DEPS_YAML.relative_to(REPO_ROOT)}:")
    for change in changes:
        print(change)
    if manifest_updated != manifest_text:
        print(
            f"Updated {MANIFEST.relative_to(REPO_ROOT)}: "
            f"PYWHISPERCPP_VERSION={pywhispercpp_version}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

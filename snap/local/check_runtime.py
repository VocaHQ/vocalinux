#!/usr/bin/env python3
"""Record locked Python versions at build time and audit the installed Snap.

Only recording uses packaging, from the locked build toolchain. The packaged
audit needs only the standard library and the runtime it is checking.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import re
import runpy
import sys
from pathlib import Path

MANIFEST = Path("usr/share/vocalinux/python-inputs.json")


def normalize(name: str) -> str:
    """Normalize a Python distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(export: Path) -> dict[str, str]:
    """Evaluate the complete export for the build interpreter, rejecting GI."""
    from packaging.requirements import Requirement

    expected = {}
    blocks = re.split(r"(?=^[A-Za-z0-9_.-]+==)", export.read_text(), flags=re.MULTILINE)[1:]
    if not blocks:
        raise RuntimeError(f"No pinned requirements in {export}")
    for block in blocks:
        requirement = Requirement(re.split(r"\s+--hash=|\\", block, maxsplit=1)[0].strip())
        if not re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", block):
            raise RuntimeError(f"Missing SHA-256 for {requirement.name}")
        name = normalize(requirement.name)
        if name == "pygobject":
            raise RuntimeError("GI must come from the GNOME extension, not pip")
        if requirement.marker and not requirement.marker.evaluate():
            continue
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise RuntimeError(f"Not an exact pin: {requirement}")
        if name in expected:
            raise RuntimeError(f"Multiple active pins for {name}")
        expected[name] = pins[0].version
    if not expected:
        raise RuntimeError(f"No active requirements in {export}")
    return expected


def audit(root: Path, expected: dict[str, str]) -> Path:
    """Check every bundled distribution, including missing/extra/build packages."""
    site = root / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    actual = {}
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        name = normalize(distribution.metadata["Name"])
        if name in actual:
            raise RuntimeError(f"Duplicate installed distribution: {name}")
        actual[name] = distribution.version
    if actual != expected:
        differences = {
            name: {"expected": expected.get(name), "installed": actual.get(name)}
            for name in sorted(expected.keys() | actual.keys())
            if expected.get(name) != actual.get(name)
        }
        raise RuntimeError(f"Snap Python versions differ from the lock: {differences}")
    return site


def record(root: Path, source: Path) -> None:
    """Retain the expected versions and original export digests in the payload."""
    for name, expected_version in locked_versions(
        source / "requirements/installer-build.txt"
    ).items():
        if importlib.metadata.version(name) != expected_version:
            raise RuntimeError(f"Build tool {name} differs from its locked version")
    expected = locked_versions(source / "requirements/runtime.txt")
    expected["vocalinux"] = runpy.run_path(str(source / "src/vocalinux/version.py"))["__version__"]
    audit(root, expected)
    manifest = {
        "python": list(sys.version_info[:2]),
        "packages": expected,
        "exports": {
            name: hashlib.sha256((source / "requirements" / name).read_bytes()).hexdigest()
            for name in ("runtime.txt", "installer-build.txt")
        },
    }
    destination = root / MANIFEST
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def smoke(root: Path) -> None:
    """Audit a packaged runtime and import native/UI modules without a model."""
    manifest = json.loads((root / MANIFEST).read_text())
    if manifest["python"] != list(sys.version_info[:2]):
        raise RuntimeError("The Snap is running with a different Python ABI")
    site = audit(root, manifest["packages"])
    sys.path.insert(0, str(site))
    for name in ("numpy", "requests", "psutil", "pyaudio", "cairo", "evdev", "vocalinux"):
        module = importlib.import_module(name)
        if not module.__file__ or not Path(module.__file__).resolve().is_relative_to(
            site.resolve()
        ):
            raise RuntimeError(f"{name} is shadowed by a platform/host package")
    from vocalinux.utils.pywhispercpp_loader import preload_shared_libraries

    preload_shared_libraries()
    for name in (
        "pywhispercpp.model",
        "vocalinux.main",
        "vocalinux.ui.tray_indicator",
        "vocalinux.speech_recognition.recognition_manager",
        "vocalinux.text_injection.text_injector",
    ):
        importlib.import_module(name)
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: F401

    if Path(gi.__file__).resolve().is_relative_to(site.resolve()):
        raise RuntimeError("The Snap bundled GI instead of using the GNOME platform")
    print("PASS: locked Snap Python versions, native modules and GNOME GTK import")


def main() -> None:
    """Record build inputs or check the installed, confined artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    try:
        if args.record:
            record(args.root, args.record)
        else:
            smoke(args.root)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as error:
        parser.exit(1, f"Snap runtime verification failed: {error}\n")


if __name__ == "__main__":
    main()

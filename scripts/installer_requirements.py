#!/usr/bin/env python3
"""Select committed requirement blocks without changing pins, markers or hashes.

The installer uses complete exports for normal installs and just pywhispercpp's
block for backend rebuilds. Missing exports or packages are errors, never an
empty successful install. Only the standard library is needed before bootstrap.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def select_requirements(source: Path, package: str | None = None) -> str:
    """Return an export, optionally retaining only one distribution's blocks."""
    text = source.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^[A-Za-z0-9_.-]+==)", text, flags=re.MULTILINE)
    requirements = blocks[1:]
    if not requirements:
        raise ValueError(f"No pinned requirements in {source}")
    if package is not None:
        normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
        requirements = [
            block
            for block in requirements
            if normalize(block.split("==", 1)[0]) == normalize(package)
        ]
        if not requirements:
            raise ValueError(f"No pin for {package} in {source}")
    return blocks[0] + "".join(requirements)


def main() -> None:
    """Write the selected export to the installer's scratch directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--package")
    args = parser.parse_args()
    try:
        text = select_requirements(args.source, args.package)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot install pinned dependencies: {error}\n")
    args.destination.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

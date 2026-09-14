#!/usr/bin/env python3
"""Fail if any `requirements/*.txt` export is behind `uv.lock`.

`just lock` writes the exports and nothing ever re-ran it, so a committed export
stays whatever it was on the day it was written. `just lock-check` and
`just flatpak-deps-check` are both in the justfile and neither is wired to a
workflow, which is how three engine exports could be added with nothing
comparing them to the lock they came from. The lock itself is covered:
`uv sync --locked` and `uv run --locked` in the pipeline fail when it drifts
from pyproject.toml. Nothing covered the step after that one.

The export lines are read out of the `lock` recipe rather than listed here, so
an export added there is checked without this file changing.

`uv export` reads `uv.lock` and nothing else, so this runs under UV_OFFLINE=1
and reproduces every file byte for byte on a cold cache. The env var rather than
`--offline`: uv echoes its own argv into the header of the file it writes, and
the flag would change the bytes this exists to compare.

`uv pip compile` lines stay out of scope. requirements/whisper.txt and the
AppImage files resolve against live indexes on purpose (see
requirements/whisper.in), so they are neither reproducible offline nor derived
from the lock.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JUSTFILE = REPO_ROOT / "justfile"


def _lock_recipe() -> list[str]:
    """The body of the `lock` recipe, one command per entry.

    Continuations are joined. The recipe already wraps its `uv pip compile`
    lines, so a wrapped `uv export` is a matter of time, and without this it
    would reach `shlex.split` with a dangling backslash: that raises `ValueError:
    No escaped character` instead of naming a file, and the `-o` sitting on the
    next physical line would be invisible either way.
    """
    body: list[str] = []
    inside = False
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        if re.match(r"^lock:\s*$", line):
            inside = True
            continue
        if not inside:
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break
        command = line.strip()
        if body and body[-1].endswith("\\"):
            body[-1] = body[-1][:-1].rstrip() + " " + command
        else:
            body.append(command)
    return body


def export_commands() -> list[tuple[list[str], Path]]:
    """Every `uv export` line in `just lock`, with the file it writes.

    A line with no `-o` writes to stdout, which no export in the recipe does and
    which this could not compare: reported rather than skipped, because skipping
    it is the failure this whole script is for.
    """
    commands = []
    for line in _lock_recipe():
        if not line.startswith("uv export"):
            continue
        argv = shlex.split(line)
        if "-o" not in argv:
            raise SystemExit(f"`just lock` exports to stdout, so nothing can check it:\n  {line}")
        commands.append((argv, REPO_ROOT / argv[argv.index("-o") + 1]))
    return commands


def regenerate(argv: list[str], target: Path, scratch: Path) -> str:
    """Re-run one export into `scratch` and return what it would have written.

    uv records the command it ran in the file's header, so the scratch path is
    put back to the declared one before comparing: the header is part of the
    export and worth checking, just not the part that says where it went.
    """
    rerun = list(argv)
    rerun[rerun.index("-o") + 1] = str(scratch)
    result = subprocess.run(
        rerun,
        cwd=REPO_ROOT,
        env={**os.environ, "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"{shlex.join(rerun)}\n{result.stderr.strip()}")
    written = scratch.read_text(encoding="utf-8")
    return written.replace(str(scratch), target.relative_to(REPO_ROOT).as_posix())


def main() -> int:
    """Check every lock-generated export and report whether any are stale."""
    commands = export_commands()
    if not commands:
        print("no `uv export` lines in the lock recipe; nothing was checked", file=sys.stderr)
        return 1
    stale = []
    with tempfile.TemporaryDirectory() as tmp:
        for argv, target in commands:
            expected = regenerate(argv, target, Path(tmp) / target.name)
            name = target.relative_to(REPO_ROOT)
            if not target.is_file():
                stale.append(f"{name} is named in `just lock` but is not committed")
            elif target.read_text(encoding="utf-8") != expected:
                stale.append(f"{name} is behind uv.lock")
    if stale:
        print("\n".join(stale), file=sys.stderr)
        print("re-run `just lock` and commit the result", file=sys.stderr)
        return 1
    print(f"{len(commands)} exports match uv.lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build independent wheels with locked tooling and stage only verified distributions.

The source snapshot includes tracked working-tree edits and non-ignored new files,
so local review exercises uncommitted changes too. Each build gets a separate copy
and virtualenv; no build/ or egg-info from the developer's checkout is reused.
Reproducibility is checked for the same Python/platform/toolchain, not across OSes.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
    """Run a build step, retaining its output even when the step fails."""
    with log.open("a", encoding="utf-8") as stream:
        print(f"$ {' '.join(argv)}", file=stream, flush=True)
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream, stderr=stream)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(argv)}; see {log}")


def snapshot(source: Path, target: Path) -> None:
    """Copy Git-visible source files, excluding ignored build and venv state."""
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=source
    )
    for name in sorted(set(files.decode().split("\0")) - {""}):
        origin = source / name
        if not origin.exists() and not origin.is_symlink():
            continue  # A tracked file deleted in the working tree.
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination, follow_symlinks=False)


def one_file(directory: Path, pattern: str) -> Path:
    """Require one output, rather than accidentally comparing stale artifacts."""
    files = sorted(directory.glob(pattern))
    if len(files) != 1:
        raise RuntimeError(f"expected exactly one {pattern} in {directory}, found {len(files)}")
    return files[0]


def digest(path: Path) -> str:
    """Return the SHA-256 of the original archive bytes."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_wheels(first: Path, second: Path, report: Path) -> None:
    """Reject any byte difference, including ZIP metadata, and explain the mismatch."""
    lines = [f"{digest(path)}  {path}" for path in (first, second)]
    # Compare bytes, not re-packed/normalized ZIPs: metadata is part of the wheel.
    equal = first.name == second.name and first.read_bytes() == second.read_bytes()
    if not equal:
        lines.append("FAIL: wheel filenames or bytes differ")
        if first.name != second.name:
            lines.append(f"filenames: {first.name} != {second.name}")
        try:
            with zipfile.ZipFile(first) as left, zipfile.ZipFile(second) as right:
                if left.namelist() != right.namelist():
                    lines.append("ZIP member names/order differ")
                for name in sorted(set(left.namelist()) | set(right.namelist())):
                    if name not in left.namelist() or name not in right.namelist():
                        lines.append(f"member present in only one wheel: {name}")
                    elif left.read(name) != right.read(name):
                        lines.append(f"member content differs: {name}")
                lines.append("Inspect ZIP timestamps, permissions, compression and headers too.")
        except zipfile.BadZipFile as error:
            lines.append(f"invalid wheel archive: {error}")
    else:
        lines.append("PASS: independently built wheels are byte-for-byte identical")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report.read_text(encoding="utf-8"), end="")
    if not equal:
        raise RuntimeError(f"wheel reproducibility failed; see {report}")


def prepare_outputs(output: Path, diagnostics: Path) -> None:
    """Remove only recognizable gate outputs, validating everything before deletion.

    The retained canonical archives identify staged files by name AND digest.
    Never recursively wipe build/ or dist/: unrelated/modified files require the
    user to move them aside. Failed builds can be retried even with partial logs
    and archives, provided no unexpected files are present.
    """
    diagnostic_files: list[Path] = []
    staged_files: list[Path] = []
    directories: list[Path] = []
    archives: dict[str, Path] = {}
    resolved_output = output.resolve()
    resolved_diagnostics = diagnostics.resolve()
    if (
        resolved_output == resolved_diagnostics
        or resolved_output in resolved_diagnostics.parents
        or resolved_diagnostics in resolved_output.parents
    ):
        raise RuntimeError("output and diagnostics directories must not overlap")
    for directory in (output, diagnostics):
        for component in (directory, *directory.parents):
            if component.is_symlink():
                raise RuntimeError(f"refusing to clean through symlink: {component}")
        if directory.exists() and not directory.is_dir():
            raise RuntimeError(f"refusing to clean non-directory: {directory}")
    if diagnostics.exists():
        for entry in diagnostics.iterdir():
            if entry.is_symlink():
                raise RuntimeError(f"refusing to clean symlink: {entry}")
            if entry.name in {"canonical", "independent"} and entry.is_dir():
                for artifact in entry.iterdir():
                    if (
                        artifact.is_symlink()
                        or not artifact.is_file()
                        or not artifact.name.endswith((".whl", ".tar.gz"))
                    ):
                        raise RuntimeError(
                            f"unrecognized diagnostic output; move aside: {artifact}"
                        )
                    diagnostic_files.append(artifact)
                    if entry.name == "canonical":
                        archives[artifact.name] = artifact
                directories.append(entry)
            elif entry.is_file() and entry.name in {
                "inputs.log",
                "canonical.log",
                "independent.log",
                "comparison.txt",
            }:
                diagnostic_files.append(entry)
            else:
                raise RuntimeError(f"unrecognized diagnostic output; move aside: {entry}")
    if output.exists():
        for artifact in output.iterdir():
            canonical = archives.get(artifact.name)
            if (
                artifact.is_symlink()
                or not artifact.is_file()
                or canonical is None
                or digest(artifact) != digest(canonical)
            ):
                raise RuntimeError(f"unrecognized or modified output; move aside: {artifact}")
            staged_files.append(artifact)
    # Delete staged copies first. Their canonical originals are the ownership
    # evidence needed by the next run if cleanup is interrupted midway through.
    files = staged_files + diagnostic_files
    if files:
        print(f"Cleaning {len(files)} previous reproducible-wheel output files")
    for path in files:
        path.unlink()
    for directory in directories:
        directory.rmdir()
    diagnostics.mkdir(parents=True, exist_ok=True)


@contextmanager
def checkout_lock() -> Iterator[None]:
    """Reject overlapping builds in this checkout before touching their outputs."""
    # Keep the inode after releasing the lock: unlinking it could let another
    # process lock a new inode while a contender still holds the original one.
    with (ROOT / ".reproducible-wheel.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "another reproducible-wheel build is active in this checkout"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def stage_distributions(artifacts: tuple[Path, ...], output: Path) -> None:
    """Copy outside dist/, then atomically publish each complete archive."""
    output.mkdir(parents=True, exist_ok=True)
    # A sibling stays on the output filesystem for atomic renames. If killed
    # during copying, only an ignored temporary directory can contain partials.
    with tempfile.TemporaryDirectory(
        prefix=".reproducible-wheel-stage-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        for artifact in artifacts:
            shutil.copy2(artifact, staging / artifact.name)
        for artifact in artifacts:
            (staging / artifact.name).replace(output / artifact.name)


def build(python: str, output: Path, diagnostics: Path) -> None:
    """Build twice and expose the canonical wheel/sdist only after verification."""
    with checkout_lock():
        _build(python, output, diagnostics)


def _build(python: str, output: Path, diagnostics: Path) -> None:
    """Run the gate while holding the checkout lock through final staging."""
    prepare_outputs(output, diagnostics)
    # Always derive the timestamp from this commit, not an inherited shell value.
    epoch = subprocess.check_output(
        ["git", "log", "-1", "--format=%ct", "HEAD"], cwd=ROOT, text=True
    ).strip()
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(name, None)
    # Override .python-version (the dev interpreter) for the offline lock/export
    # checks too. A clean release runner only needs the selected build Python.
    env.update(
        SOURCE_DATE_EPOCH=epoch,
        PYTHONNOUSERSITE="1",
        UV_PYTHON=python,
        TZ="UTC",
        LC_ALL="C.UTF-8",
    )
    run(["uv", "lock", "--check", "--offline"], ROOT, env, diagnostics / "inputs.log")
    run(
        [sys.executable, str(ROOT / "scripts/check_exports.py")],
        ROOT,
        env,
        diagnostics / "inputs.log",
    )
    with tempfile.TemporaryDirectory(prefix="vocalinux-wheel-") as temporary:
        scratch = Path(temporary)
        source = scratch / "snapshot"
        source.mkdir()
        snapshot(ROOT, source)
        for label, seed in (("canonical", "1"), ("independent", "2")):
            tree = scratch / label / "source"
            shutil.copytree(source, tree, symlinks=True)
            venv = scratch / label / "venv"
            dist = diagnostics / label
            dist.mkdir()
            log = diagnostics / f"{label}.log"
            build_env = {**env, "PYTHONHASHSEED": seed}
            run(
                [
                    "uv",
                    "venv",
                    "--no-config",
                    "--python",
                    python,
                    str(venv),
                ],
                scratch,
                build_env,
                log,
            )
            interpreter = str(venv / "bin/python")
            # Force every exported tool into the venv, even if the system already
            # has that version. Only wheels, verified by the committed hashes.
            run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--no-config",
                    "--python",
                    interpreter,
                    "--require-hashes",
                    "--no-deps",
                    "--only-binary=:all:",
                    "--reinstall",
                    "-r",
                    str(source / "requirements/release-build.txt"),
                ],
                scratch,
                build_env,
                log,
            )
            run(
                [interpreter, "-I", "-m", "build", "--no-isolation", "--outdir", str(dist)],
                tree,
                build_env,
                log,
            )
            run(
                [
                    interpreter,
                    "-I",
                    "-m",
                    "twine",
                    "check",
                    "--strict",
                    str(one_file(dist, "*.whl")),
                    str(one_file(dist, "*.tar.gz")),
                ],
                tree,
                build_env,
                log,
            )
        canonical = one_file(diagnostics / "canonical", "*.whl")
        compare_wheels(
            canonical,
            one_file(diagnostics / "independent", "*.whl"),
            diagnostics / "comparison.txt",
        )
        stage_distributions((canonical, one_file(diagnostics / "canonical", "*.tar.gz")), output)


def main() -> int:
    """Run the local and CI release gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python", default=sys.executable, help="build interpreter (CI: Python 3.11)"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--diagnostics", type=Path, default=ROOT / "build/reproducible-wheel")
    args = parser.parse_args()
    try:
        build(args.python, args.output.absolute(), args.diagnostics.absolute())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

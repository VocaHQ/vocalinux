#!/usr/bin/env python3
"""Install locked Python inputs without changing the project's dependency metadata.

Snapcraft's default Python plugin resolves the project and its build environment
again. Use a separate, hash-pinned build virtualenv instead, and install only the
runtime export and the unchanged project into the snap's relocatable virtualenv.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def run(argv: list[str], source: Path, env: dict[str, str]) -> None:
    """Run a build command, preserving its output and failure status."""
    print(f"+ {' '.join(argv)}", flush=True)
    subprocess.run(argv, cwd=source, env=env, check=True)


def relocate_scripts(install: Path, tooling: Path) -> None:
    """Remove temporary interpreter paths, including pip's long-shebang shim."""
    prefix = str(tooling).encode()
    for script in (install / "bin").iterdir():
        if script.is_symlink() or not script.is_file():
            continue
        lines = script.read_bytes().splitlines(keepends=True)
        if lines and lines[0].startswith(b"#!" + prefix + b"/"):
            script.write_bytes(b"#!/usr/bin/env python3\n" + b"".join(lines[1:]))
        elif (
            len(lines) >= 3
            and lines[0] == b"#!/bin/sh\n"
            and lines[1].startswith(b"'''exec' ")
            and prefix in lines[1]
            and lines[2] == b"' '''\n"
        ):
            script.write_bytes(b"#!/usr/bin/env python3\n" + b"".join(lines[3:]))

    # GNOME's command chain adds platform Python paths. Our locked packages
    # must win over incidental copies in that platform, while GI stays there.
    python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    launcher = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "
        f"'lib/{python_version}/site-packages'))\n"
        "from vocalinux.main import main\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(main())\n"
    )
    for name in ("vocalinux", "vocalinux-gui"):
        path = install / "bin" / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Missing installed entry point: {path}")
        path.write_text(launcher, encoding="utf-8")


def build(source: Path, install: Path, work: Path) -> None:
    """Build using committed exports; never stage the build tools or a new GI."""
    metadata = source / "pyproject.toml"
    original_metadata = metadata.read_bytes()
    for export in ("installer-build.txt", "runtime.txt"):
        if not (source / "requirements" / export).is_file():
            raise RuntimeError(f"Missing locked export: requirements/{export}")

    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PIP_") and key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    env["PIP_CONFIG_FILE"] = os.devnull
    env["PYTHONNOUSERSITE"] = "1"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snap-python-", dir=work) as temporary:
        tooling = Path(temporary)
        # Both environments are build outputs, not the contributor's dev venv.
        # ensurepip seeds pip from the distro; the first network operation
        # replaces it with the complete hash-pinned installer toolchain.
        venv.EnvBuilder(with_pip=True, symlinks=True).create(tooling)
        python = str(tooling / "bin" / "python3")
        env["PATH"] = f"{tooling / 'bin'}{os.pathsep}{env['PATH']}"
        pip = [
            python,
            "-m",
            "pip",
            "--isolated",
            "--disable-pip-version-check",
            "install",
            "--no-cache-dir",
        ]
        run(
            pip
            + [
                "--require-hashes",
                "--no-deps",
                "--only-binary=:all:",
                "--upgrade",
                "-r",
                str(source / "requirements/installer-build.txt"),
            ],
            source,
            env,
        )
        venv.EnvBuilder(with_pip=False, symlinks=True).create(install)
        target = ["--prefix", str(install), "--ignore-installed", "--no-compile"]
        run(
            pip
            + target
            + [
                "--require-hashes",
                "--no-deps",
                "--no-build-isolation",
                # A cached upstream wheel can require AVX2/FMA (#957).
                "--no-binary=pywhispercpp",
                "-r",
                str(source / "requirements/runtime.txt"),
            ],
            source,
            env,
        )
        run(
            pip + target + ["--no-deps", "--no-build-isolation", "--no-index", str(source)],
            source,
            env,
        )
        relocate_scripts(install, tooling)
        run(
            [
                python,
                str(source / "snap/local/check_runtime.py"),
                "--root",
                str(install),
                "--record",
                str(source),
            ],
            source,
            env,
        )
    if metadata.read_bytes() != original_metadata:
        raise RuntimeError("The Snap build modified pyproject.toml")


def main() -> None:
    """Build the Python payload inside Snapcraft's core24 environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        parser.error("Build this core24 snap with Linux's system Python 3.12")
    try:
        build(args.source.resolve(), args.install.resolve(), args.work.resolve())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Snap Python build failed: {error}\n")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Add behavioral witnesses to a disposable copy of the remote installer's tree.

The real exports are preserved, with one tiny, hashed local wheel added to each
of the two mandatory exports. Nothing in the contributor's checkout is changed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import shlex
import shutil
import zipfile
from pathlib import Path

MODULES = ("package_map.sh", "interactive.sh", "system_dependencies.sh", "models.sh", "desktop.sh")
LATEST_ENDPOINT = "https://api.github.com/repos/VocaHQ/vocalinux/releases/latest"
TRACE = '"$HOME/remote-gate.trace"'


def _replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError(f"Expected exactly one fixture anchor: {before!r}")
    return source.replace(before, after, 1)


def _witness(event: str) -> str:
    return f"printf '%s\\n' {shlex.quote(event)} >> {TRACE}\n"


def write_wheel(directory: Path, kind: str, version: str) -> Path:
    """Create a valid, dependency-free wheel which real pip can install offline."""
    name = f"vocalinux_remote_{kind}_fixture"
    dist_info = f"{name}-{version}.dist-info"
    files = {
        f"{name}.py": f'VERSION = "{version}"\n'.encode(),
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: {version}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: remote-install-gate\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n"
        ).encode(),
    }
    records = []
    for path, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        records.append(f"{path},sha256={digest},{len(data)}\n")
    files[f"{dist_info}/RECORD"] = ("".join(records) + f"{dist_info}/RECORD,,\n").encode()
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{name}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, data in files.items():
            archive.writestr(zipfile.ZipInfo(path, date_time=(2020, 1, 1, 0, 0, 0)), data)
    return wheel


def write_latest_shim(path: Path, real_curl: Path) -> None:
    """Intercept only the latest-release URL; delegate every other curl call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'for arg in "$@"; do\n'
        f'  if [ "$arg" = {shlex.quote(LATEST_ENDPOINT)} ]; then\n'
        '    printf "%s\\n" latest >> "$HOME/remote-gate.api"\n'
        '    if [ "$REMOTE_GATE_LATEST" = unavailable ]; then exit 22; fi\n'
        '    cat "$REMOTE_GATE_LATEST"\n'
        "    exit 0\n"
        "  fi\n"
        "done\n"
        f'exec {shlex.quote(str(real_curl))} "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)


def prepare_fixture(tree: Path, output: Path, role: str) -> None:
    """Instrument a disposable tree without replacing any installation actions."""
    revision = {"explicit": 1, "latest": 2}[role]
    version = f"{revision}.0"
    output.mkdir(parents=True, exist_ok=True)
    installer = tree / "install.sh"
    source = installer.read_text(encoding="utf-8")
    anchor = "set -Eeuo pipefail\n"
    bootstrap = _replace_once(source, anchor, anchor + _witness("bootstrap"))
    bootstrap = _replace_once(
        bootstrap,
        "# Change to install directory\n",
        'print_error "REMOTE_GATE: bootstrap continued past tagged handoff"\n'
        "exit 97\n\n# Change to install directory\n",
    )
    (output / "bootstrap.sh").write_text(bootstrap, encoding="utf-8")
    installer.write_text(
        _replace_once(source, anchor, anchor + _witness(f"installer:{role}")), encoding="utf-8"
    )
    # A skipped project reinstall must not pass an upgrade's version smoke.
    version_file = tree / "src/vocalinux/version.py"
    version_source, count = re.subn(
        r'^__version__ = "[^"]+"\n__version_info__ = \([^\n]+\)',
        f'__version__ = "0.0.{revision}"\n__version_info__ = (0, 0, {revision})',
        version_file.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("Expected exactly one fixture version declaration")
    version_file.write_text(version_source, encoding="utf-8")
    for module in MODULES:
        path = tree / "install.d" / module
        path.write_text(
            _witness(f"module:{role}:{module}") + path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    for kind, export in (("runtime", "runtime.txt"), ("build", "installer-build.txt")):
        wheel = write_wheel(output / "wheels", kind, version)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with (tree / "requirements" / export).open("a", encoding="utf-8") as requirements:
            requirements.write(
                f"\nvocalinux-remote-{kind}-fixture @ {wheel.resolve().as_uri()} "
                f"--hash=sha256:{digest}\n"
            )
    real_curl = shutil.which("curl")
    if real_curl is None:
        raise ValueError("curl is required for the latest-endpoint fixture")
    write_latest_shim(output / "bin/curl", Path(real_curl))


def main() -> None:
    """Prepare one release fixture; git publication is owned by the shell gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tree", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("role", choices=("explicit", "latest"))
    args = parser.parse_args()
    prepare_fixture(args.tree, args.output, args.role)


if __name__ == "__main__":
    main()

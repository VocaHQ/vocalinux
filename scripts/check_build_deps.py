#!/usr/bin/env python3
"""Fail fast when the native headers `just deps` needs are missing.

`uv sync` builds pyaudio, pycairo and PyGObject from source on Linux. Without
their development headers it fails deep inside a C compiler invocation, which
reads as a uv or dependency problem even though the fix is a distro package.
This check runs before the sync and names what is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

# pkg-config modules the source builds query. Labels explain the module to a
# contributor who does not know which package owns it.
BUILD_MODULES = (("portaudio-2.0", "PortAudio headers (pyaudio)"),)
# PyGObject and its pycairo dependency are selected only on Linux by the
# sys_platform marker in pyproject.toml. They must not gate macOS tooling.
PYGOBJECT_BUILD_MODULES = (
    ("cairo", "cairo headers (pycairo)"),
    ("cairo-gobject", "cairo-gobject headers (PyGObject)"),
    ("girepository-2.0", "GObject Introspection headers (glib 2.80+)"),
    ("libffi", "libffi headers (PyGObject)"),
)
MIN_GIREPOSITORY_VERSION = "2.80"

APT_HINT = [
    "Ubuntu 24.04+ / Debian 13+:",
    "  sudo apt install -y build-essential pkg-config libcairo2-dev portaudio19-dev \\",
    "      libgirepository-2.0-dev libffi-dev",
]

DEBIAN_12_NOTE = [
    "",
    "Debian 12 cannot build PyGObject 3.56 (glib is too old). Use ./install.sh --dev",
    "there and run the suite with venv/bin/pytest.",
]

DNF_HINT = [
    "Fedora 40+ / RHEL-based systems with glib 2.80+:",
    "  sudo dnf install -y gcc gcc-c++ make pkg-config cairo-devel \\",
    "      cairo-gobject-devel portaudio-devel glib2-devel \\",
    "      gobject-introspection-devel libffi-devel",
    "If your system's glib is older than 2.80, use ./install.sh --dev instead.",
]

FEDORA_OLD_NOTE = [
    "Fedora 39 and older cannot build PyGObject 3.56 (glib is too old).",
    "Use ./install.sh --dev there and run the suite with venv/bin/pytest.",
]

PACMAN_HINT = [
    "Arch / Manjaro:",
    "  sudo pacman -S --needed base-devel pkgconf cairo portaudio gobject-introspection",
]

ZYPPER_HINT = [
    "openSUSE:",
    "  sudo zypper install -y gcc gcc-c++ make pkg-config cairo-devel \\",
    "      portaudio-devel gobject-introspection-devel libffi-devel",
]

GENERIC_HINT = [
    "Install the development packages for PortAudio, cairo, GObject Introspection",
    "(glib 2.80+) and libffi, plus a C compiler and pkg-config.",
]

MACOS_HINT = [
    "macOS (Homebrew):",
    "  brew install portaudio pkg-config",
    "Install the Xcode Command Line Tools if a C compiler is missing:",
    "  xcode-select --install",
]


def read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    """Parse os-release without executing it as shell."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for line in lines:
        key, separator, value = line.partition("=")
        if not separator or not key or key.startswith("#"):
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def install_hint(release: dict[str, str]) -> list[str]:
    """Return distro-specific install commands for the missing build headers."""
    distro = release.get("ID", "").lower()
    like = release.get("ID_LIKE", "").lower()

    if distro == "ubuntu" or "ubuntu" in like:
        return APT_HINT

    if distro == "debian" or "debian" in like:
        return [*APT_HINT, *DEBIAN_12_NOTE]

    if distro in {"fedora", "rhel", "centos", "rocky", "almalinux"} or any(
        family in like for family in ("fedora", "rhel")
    ):
        if distro == "fedora" and release.get("VERSION_ID", "").isdigit():
            if int(release["VERSION_ID"]) < 40:
                return FEDORA_OLD_NOTE
        return DNF_HINT

    if distro in {"arch", "manjaro", "endeavouros"} or "arch" in like:
        return PACMAN_HINT

    if distro == "opensuse" or distro.startswith("opensuse-") or "suse" in like:
        return ZYPPER_HINT

    return GENERIC_HINT


def venv_has_compiled_packages() -> bool:
    """True when `.venv` has the native packages selected for this platform."""
    if not VENV_PYTHON.is_file():
        return False
    packages = ("pyaudio",)
    if sys.platform == "linux":
        packages += ("pycairo", "pygobject")
    check = "import importlib.metadata as metadata; " + "; ".join(
        f"metadata.version({package!r})" for package in packages
    )
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", check],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def missing_build_dependencies() -> list[str]:
    """Return the compiler or pkg-config modules uv cannot find, if any."""
    missing: list[str] = []

    if shutil.which("pkg-config") is None:
        missing.append("pkg-config")
    if not any(shutil.which(compiler) for compiler in ("cc", "gcc", "clang")):
        missing.append("a C compiler")

    # Module probes need pkg-config; report the missing tool instead of a list
    # of modules the user cannot check yet.
    if missing:
        return missing

    modules = BUILD_MODULES
    if sys.platform == "linux":
        modules += PYGOBJECT_BUILD_MODULES
    for module, description in modules:
        # PyGObject 3.56 requires girepository-2.0 >= 2.80; finding an older
        # .pc file is not enough to build it successfully.
        args = ["pkg-config", "--exists", module]
        if module == "girepository-2.0":
            args = ["pkg-config", f"--atleast-version={MIN_GIREPOSITORY_VERSION}", module]
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            missing.append(description)

    return missing


def main() -> int:
    """Print an actionable dependency report when the build cannot succeed."""
    if venv_has_compiled_packages():
        return 0

    missing = missing_build_dependencies()
    if not missing:
        return 0

    print("error: missing native build dependencies for .venv/", file=sys.stderr)
    print(file=sys.stderr)
    print(
        "`just deps` builds native Python packages from source, so uv needs their",
        file=sys.stderr,
    )
    print("development headers before it can create the environment.", file=sys.stderr)
    print(file=sys.stderr)
    print("Missing:", file=sys.stderr)
    for item in missing:
        print(f"  - {item}", file=sys.stderr)
    print(file=sys.stderr)
    print("Install them for your system:", file=sys.stderr)
    hints = MACOS_HINT if sys.platform == "darwin" else install_hint(read_os_release())
    for line in hints:
        print(line, file=sys.stderr)
    print(file=sys.stderr)
    print(
        "See the Manual setup section in CONTRIBUTING.md for the full package list.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# Install the built native package inside its distro container and prove the
# app it ships actually runs.
#
# Usage (mount the package dir at /out and this script's dir at /pk):
#   docker run --rm -v "$PWD/dist:/out:ro" -v "$PWD/packaging/native:/pk:ro" \
#     debian:12 bash /pk/smoke-test.sh
#   or: just native-smoke debian:12
#
# What this proves: the package manager accepts the package and resolves its
# declared dependencies, the /usr/bin launcher runs, and the import graph —
# gi, GTK, the app modules and the vendored wheels — resolves against the
# distro interpreter. It is the native-package counterpart of install-gate
# and the AppImage boot matrix: Debian and Ubuntu exercise the .deb, Fedora
# the .rpm.
#
# What it does not prove: dictation. No container here has audio or a
# display, and the point is the package, not the app — the app's own tests
# cover behaviour.
set -euo pipefail

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

[ -r /etc/os-release ] || fail "/etc/os-release missing — not a distro container?"
# shellcheck disable=SC1091
. /etc/os-release

export DEBIAN_FRONTEND=noninteractive
case "$ID" in
    debian|ubuntu)
        PKG="$(find /out -name '*.deb' -print -quit)"
        [ -n "$PKG" ] || fail "no .deb under /out"
        apt-get update
        apt-get install -y "$PKG"
        ;;
    fedora)
        PKG="$(find /out -name '*.rpm' -print -quit)"
        [ -n "$PKG" ] || fail "no .rpm under /out"
        dnf install -y "$PKG"
        ;;
    *)
        fail "no smoke recipe for distro ID '$ID' — add one alongside the dependency list it is meant to exercise"
        ;;
esac

echo "== installed: $PKG"

# The launcher must answer: --version is an argparse action that exits
# before check_dependencies() touches GTK, so it proves the wrapper, the
# PYTHONPATH layout and the entry module's import chain — the dependency
# typelibs are exercised by the import smoke below.
vocalinux --version
vocalinux-gui --version

# Import smoke in the shape of the AUR gate: the app modules, the vendored
# pywhispercpp wheel, and the distro gi/GTK typelibs, all through the same
# interpreter and environment the launcher sets up. pynput is only checked
# for presence: its __init__ selects a display backend and raises ImportError
# with no DISPLAY, which is why the app guards it with PYNPUT_AVAILABLE.
PYTHONPATH="/usr/lib/vocalinux/app:/usr/lib/vocalinux/vendor" \
PYTHONNOUSERSITE=1 \
LD_LIBRARY_PATH="/usr/lib/vocalinux/vendor/pywhispercpp.libs" \
/usr/bin/python3 - <<'PY'
import importlib
import importlib.util
import sys
from pathlib import Path

MODULES = (
    "vocalinux.main",
    "vocalinux.ui.tray_indicator",
    "vocalinux.speech_recognition.recognition_manager",
    "vocalinux.speech_recognition.command_processor",
    "vocalinux.text_injection.text_injector",
    "vocalinux.text_injection.ibus_engine",
    "vocalinux.ui.keyboard_backends",
    "pywhispercpp.model",
)
for module in MODULES:
    importlib.import_module(module)

spec = importlib.util.find_spec("pynput")
assert spec and spec.origin and spec.origin.startswith("/usr/lib/vocalinux/vendor/"), \
    f"vendored pynput not found on sys.path: {spec}"

tag = f"cpython-{sys.version_info.major}{sys.version_info.minor}-"
exts = [p.name for p in Path("/usr/lib/vocalinux/vendor").glob("_pywhispercpp.*.so")]
assert any(tag in name for name in exts), \
    f"no _pywhispercpp extension for {tag[:-1]} among {exts}"

print("import-smoke OK:", ", ".join(MODULES))
PY

echo "SMOKE-TEST PASSED"

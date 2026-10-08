#!/usr/bin/env bash
# Build vocalinux_<version>_<arch>.deb and vocalinux-<version>.<arch>.rpm.
#
# Usage: build.sh <path-to-vocalinux-wheel> <version> [output-dir]
#   version    release version, e.g. 0.18.0 or 0.19.0-beta
#
# CI and releases run this inside docker-build.sh's pinned Debian 12 image;
# it works on any host with bash, python3 + pip, curl and tar. The packages
# stay thin on purpose (#600): the interpreter, GTK, PyGObject and the gi
# typelibs come from the distribution, and so does every Python dependency
# the distros package. Only pywhispercpp and pynput are vendored — the first
# is unpackaged on both distros and the second is missing from Fedora.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
PINS="$REPO_ROOT/packaging/native/tool_checksums.txt"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

WHEEL="$(readlink -f "${1:?usage: build.sh <wheel> <version> [outdir]}")"
RAW_VERSION="${2:?usage: build.sh <wheel> <version> [outdir]}"
OUTDIR="$(mkdir -p "${3:-dist}" && cd "${3:-dist}" && pwd)"
[ -f "$WHEEL" ] || fail "wheel not found: $WHEEL"

# Split "0.19.0-beta" into version + prerelease; nfpm renders the prerelease
# as a "~beta" suffix, which orders before the stable release in both dpkg
# and rpm. An empty prerelease expands to nothing.
VERSION="${RAW_VERSION#v}"
PRERELEASE=""
case "$VERSION" in
    *-*)
        PRERELEASE="${VERSION#*-}"
        VERSION="${VERSION%%-*}"
        ;;
esac

case "$(uname -m)" in
    x86_64)        NFPM_PIN="nfpm-x86_64";  NFPM_ARCH="amd64" ;;
    aarch64|arm64) NFPM_PIN="nfpm-aarch64"; NFPM_ARCH="arm64" ;;
    *) fail "unsupported architecture $(uname -m)" ;;
esac

TOOLS="$(mktemp -d)"
trap 'rm -rf "$TOOLS"' EXIT

fetch_pinned() {
    local name="$1" dest="$2" url sum
    sum="$(awk -v n="$name" '$1==n && $2=="sha256" {print $3}' "$PINS")"
    url="$(awk -v n="$name" '$1==n && $2=="sha256" {print $4}' "$PINS")"
    [ -n "$sum" ] && [ -n "$url" ] || fail "no sha256 pin for $name in $PINS"
    curl -fSL --retry 3 -o "$dest" "$url"
    echo "$sum  $dest" | sha256sum -c - >/dev/null
}

# nfpm is a single static binary inside the release tarball; unpack just it.
fetch_pinned "$NFPM_PIN" "$TOOLS/nfpm.tar.gz"
tar -xzf "$TOOLS/nfpm.tar.gz" -C "$TOOLS" nfpm
NFPM="$TOOLS/nfpm"

PAYLOAD="$TOOLS/payload"
DOC="$TOOLS/pkg-doc"
install -d \
    "$PAYLOAD/usr/lib/vocalinux/app" \
    "$PAYLOAD/usr/lib/vocalinux/vendor" \
    "$PAYLOAD/usr/bin" \
    "$PAYLOAD/usr/share/applications" \
    "$PAYLOAD/usr/share/icons/hicolor/scalable/apps" \
    "$DOC"

# --- application payload ------------------------------------------------
# The wheel is a zip; -m zipfile lays out vocalinux/ and its dist-info
# exactly where pip --target would, without pip's EXTERNALLY-MANAGED refusal
# on Debian 12.
python3 -m zipfile -e "$WHEEL" "$PAYLOAD/usr/lib/vocalinux/app/"

# --- vendored wheels -----------------------------------------------------
# Download each supported CPython's pywhispercpp wheel — it has no abi3 tag,
# so there is one wheel per interpreter — plus the pure-Python pynput, per
# the hashes pinned in requirements/runtime.txt, and merge them flat into
# the vendor dir. The extension filenames carry their tag
# (_pywhispercpp.cpython-311-*.so next to .cpython-313-*.so) so all four
# coexist, and the flat layout reproduces what pip would place in
# site-packages, which is what utils/pywhispercpp_loader.py scans for.
#
# VENDOR_PYS tracks requires-python in pyproject.toml and the CI matrix.
VENDOR_PYS="3.11 3.12 3.13 3.14"
PINS_VENDOR="$TOOLS/vendor-requirements.txt"
awk '/^(pywhispercpp|pynput)==/{p=1} p{print; if ($0 !~ /\\$/) p=0}' \
    "$REPO_ROOT/requirements/runtime.txt" > "$PINS_VENDOR"
grep -q "^pywhispercpp==" "$PINS_VENDOR" || fail "pywhispercpp pin not found in requirements/runtime.txt"
grep -q "^pynput==" "$PINS_VENDOR" || fail "pynput pin not found in requirements/runtime.txt"

for PYV in $VENDOR_PYS; do
    mkdir -p "$TOOLS/wheels/$PYV"
    pip3 download --require-hashes --no-deps --only-binary=:all: \
        --python-version "$PYV" -r "$PINS_VENDOR" -d "$TOOLS/wheels/$PYV" >/dev/null
done
for VENDOR_WHEEL in "$TOOLS"/wheels/*/*.whl; do
    python3 -m zipfile -e "$VENDOR_WHEEL" "$PAYLOAD/usr/lib/vocalinux/vendor/"
done

# --- launchers -----------------------------------------------------------
# Same environment install.sh's wrapper establishes: the vendored
# pywhispercpp.libs on LD_LIBRARY_PATH, user site-packages off so they cannot
# shadow the distro modules, and sg input so evdev hotkeys work on Wayland
# when the user is already in the input group but the session has not picked
# up the membership yet. vocalinux-gui exists because the wheel declares a
# gui-script of that name; on Linux it runs the same entry.
write_launcher() {
    local path="$1"
    cat > "$path" <<'LAUNCHER_EOF'
#!/bin/sh
# Launcher for the distro-packaged Vocalinux. The vendored wheels (the
# pywhispercpp/pynput copies Debian and Fedora do not ship) live under
# /usr/lib/vocalinux/vendor with the app itself under .../app; the loader in
# utils/pywhispercpp_loader.py finds the bundled .so files from sys.path.
PYTHONNOUSERSITE=1
VOCALINUX_VENDOR="/usr/lib/vocalinux/vendor"
if [ -d "$VOCALINUX_VENDOR/pywhispercpp.libs" ]; then
    LD_LIBRARY_PATH="$VOCALINUX_VENDOR/pywhispercpp.libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export LD_LIBRARY_PATH
fi
export PYTHONNOUSERSITE PYTHONPATH="/usr/lib/vocalinux/app:$VOCALINUX_VENDOR${PYTHONPATH:+:$PYTHONPATH}"
if grep -q "^input:.*\b$(whoami)\b" /etc/group 2>/dev/null \
    && ! groups | grep -q "\binput\b" && command -v sg >/dev/null 2>&1; then
    # sg(1) takes a single command string, so each argument is re-quoted for
    # the inner shell; joining $* would re-split paths containing spaces.
    QUOTED_ARGS=""
    for arg in "$@"; do
        arg="$(printf %s "$arg" | sed "s/'/'\\\\''/g")"
        QUOTED_ARGS="$QUOTED_ARGS '$arg'"
    done
    exec sg input -c "/usr/bin/python3 -m vocalinux.main$QUOTED_ARGS"
fi
exec /usr/bin/python3 -m vocalinux.main "$@"
LAUNCHER_EOF
    chmod 755 "$path"
}
write_launcher "$PAYLOAD/usr/bin/vocalinux"
write_launcher "$PAYLOAD/usr/bin/vocalinux-gui"

# --- desktop entry, icon, license ----------------------------------------
install -Dm644 "$REPO_ROOT/vocalinux.desktop" \
    "$PAYLOAD/usr/share/applications/vocalinux.desktop"
install -Dm644 "$REPO_ROOT/resources/icons/scalable/vocalinux.svg" \
    "$PAYLOAD/usr/share/icons/hicolor/scalable/apps/vocalinux.svg"
install -Dm644 "$REPO_ROOT/LICENSE" "$DOC/LICENSE"

# --- package -------------------------------------------------------------
# nfpm resolves contents src paths relative to its working directory, so run
# it from $TOOLS where ./payload and ./pkg-doc live.
cd "$TOOLS"
VOCA_ARCH="$NFPM_ARCH" VOCA_VERSION="$VERSION" VOCA_PRERELEASE="$PRERELEASE" \
    "$NFPM" package --config "$REPO_ROOT/packaging/native/nfpm.yaml" \
    --packager deb --target "$OUTDIR/"
VOCA_ARCH="$NFPM_ARCH" VOCA_VERSION="$VERSION" VOCA_PRERELEASE="$PRERELEASE" \
    "$NFPM" package --config "$REPO_ROOT/packaging/native/nfpm.yaml" \
    --packager rpm --target "$OUTDIR/"

ls -la "$OUTDIR"/*.deb "$OUTDIR"/*.rpm

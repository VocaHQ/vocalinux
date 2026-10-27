#!/usr/bin/env bash
# Build a prepared, checksum-pinned AUR source package on current Arch.
#
# Usage (first prepare build/aur-source with scripts/prepare_aur_source.py):
#   docker run --rm -v "$PWD:/repo:ro" archlinux:latest \
#     bash /repo/packaging/aur/build-test.sh
#   or: just aur-gate
#
# This is the gate #757 needed: Arch extra moved to setuptools 84 while
# build-system.requires still capped it below 82, so the PKGBUILD's
# --no-isolation build broke for AUR users — and nothing ever ran makepkg on
# the PKGBUILD before a tag published it.
# Both PR and release gates consume the canonical sdist and fully prepared
# PKGBUILD without rewriting source=, versions or checksums. PR fixtures are
# explicitly unattested; the release job verifies published bytes and provenance
# before running this gate. AUR_SOURCE_ONLY=1 leaves the existing -bin smoke out;
# AUR_FETCH_SOURCE=1 makes makepkg download the real published source URL afresh.
#
# Not this gate's, despite reaching Arch users: #736 came through install.sh,
# not through this package. The AUR build of v0.16.0 was intact, because the
# tree it built carried neither model_checksums.txt nor the code reading it.
# Closing that one takes a build gate for install.sh, not for this package.
#
# Deliberately archlinux:latest, unpinned: the AUR is a rolling channel and
# #757 was Arch moving under us. A pinned image would test a world that no
# longer exists.
#
# Two depends cannot come from the repos: python-pywhispercpp is a virtual
# name that the AUR -cpu/-cuda/-rocm backends provide (#579), and
# python-pynput lives in the AUR itself. A stub package with provides=()
# satisfies them so makepkg verifies the full depends set; for the import
# smoke they are pip-installed from the hash-pinned requirements/runtime.txt,
# so the smoke runs the versions we pin, not whatever AUR ships — that drift
# (AUR -cpu is still 1.4.x) is a monitoring job, not this gate.
#
# What the smoke therefore does NOT prove: that depends=() is complete. This
# container carries base-devel and python-pip with their own closures, and the
# two names above arrive via pip --no-deps, so a missing *direct* dependency
# still passes. Transitive ones are the provider's to declare — the backend
# providing python-pywhispercpp declares python-platformdirs itself.
set -euo pipefail

REPO="${REPO:-/repo}"
PKGDIR="${AUR_SOURCE:-$REPO/build/aur-source}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Retry: a mirror going mid-transaction slow leaves half the cache and a
# clean database, so re-running the same transaction resumes rather than
# restarts.
pacman_retry() {
  local attempt
  for attempt in 1 2 3; do
    pacman "$@" && return 0
    echo "   pacman failed (attempt $attempt); retrying" >&2
    sleep 5
  done
  return 1
}

. /etc/os-release
[ "$ID" = "arch" ] || fail "this gate runs on Arch Linux (got '$ID')"

[ -f "$PKGDIR/PKGBUILD" ] || fail "$PKGDIR/PKGBUILD not found"

# Upgrade before installing anything. archlinux:latest lags the mirrors, so
# -Sy alone would put fresh packages on a stale base — the partial upgrade
# Arch warns about, and a breakage this gate would be causing rather than
# detecting. It is also what "Arch as it is today" has to mean here.
pacman_retry -Syu --noconfirm >/dev/null

# Sourcing gives us pkgname, _tag and the depends/makedepends arrays the same
# way makepkg itself reads them.
# shellcheck source=/dev/null
source "$PKGDIR/PKGBUILD"

echo "== Arch, $(date -u +%F) =="
echo "   building ${pkgname} ${pkgver}-${pkgrel} (tagged _tag=${_tag})"
pacman -Q python python-setuptools 2>/dev/null || true

echo "== Install depends and makedepends from the repos =="
# AUR-resolved depends (see header): satisfied by the stub below, not pacman.
AUR_RESOLVED="python-pywhispercpp python-pynput"
repo_deps=()
for dep in "${depends[@]}" "${makedepends[@]}"; do
  case " $AUR_RESOLVED " in
    *" $dep "*) ;;
    *) repo_deps+=("$dep") ;;
  esac
done
# --needed keeps this idempotent; an unknown name here is a gate failure in
# its own right: it means the PKGBUILD depends on something Arch does not
# package (how a python-pywhispercpp-cpu rename would go unnoticed again).
# base-devel is the documented prerequisite for building any AUR package
# (fakeroot, debugedit and friends); makepkg aborts without it.
pacman_retry -S --needed --noconfirm --asdeps base-devel namcap python-pip curl \
  "${repo_deps[@]}" >/dev/null

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "== Satisfy the AUR-resolved depends for dependency resolution =="
# makepkg verifies every depends entry against the local pacman database.
# Without this stub it would fail on the two names no repo can provide.
STUB="$WORKDIR/stub"
mkdir -p "$STUB"
cat >"$STUB/PKGBUILD" <<EOF
pkgname=vocalinux-gate-stub
pkgver=1
pkgrel=1
pkgdesc="Satisfies the AUR-resolved depends of the vocalinux build gate"
arch=('any')
provides=('python-pywhispercpp' 'python-pynput')
EOF

echo "== Copy the prepared PKGBUILD and original sdist without rewriting =="
BUILD="$WORKDIR/pkg"
mkdir -p "$BUILD"
# makepkg consumes the cached archive under the same filename as source= and
# still verifies its real checksum. No SKIP or --skipchecksums for source builds.
cp "$PKGDIR/PKGBUILD" "$BUILD/PKGBUILD"
if [ "${AUR_FETCH_SOURCE:-0}" = 1 ]; then
  echo "   release gate: makepkg must download the published source URL afresh"
else
  cp "$PKGDIR/${pkgname}-${_version}.tar.gz" "$BUILD/"
fi

# makepkg refuses to run as root; a build user is the container-standard fix.
useradd -m builder
chown -R builder "$WORKDIR"

(
  cd "$STUB"
  runuser -u builder -- makepkg -f --noconfirm >/dev/null
  pacman -U --noconfirm ./*.pkg.tar.* >/dev/null
)

echo "== makepkg =="
(
  cd "$BUILD"
  # No -s and no --nodeps: depends were installed above, the stub satisfies
  # the AUR-resolved two, so makepkg's own verification is part of the gate.
  runuser -u builder -- makepkg -f --noconfirm
)

echo "== namcap =="
check_namcap() {
  local target="$1" out
  out="$(namcap "$target" 2>&1 || true)"
  echo "$out" | sed 's/^/   /'
  if echo "$out" | grep -q ' E: '; then
    fail "namcap reports errors on $target"
  fi
}
check_namcap "$BUILD/PKGBUILD"
check_namcap "$BUILD"/*.pkg.tar.*

echo "== Install the package and smoke it =="
# The two AUR-resolved deps as importable modules, at the versions we pin.
awk '/^(pywhispercpp|pynput)==/{p=1} p{print; if ($0 !~ /\\$/) p=0}' \
  "$REPO/requirements/runtime.txt" >"$WORKDIR/pinned.txt"
pip install --no-deps --break-system-packages --require-hashes -r "$WORKDIR/pinned.txt" >/dev/null

pacman -U --noconfirm "$BUILD"/*.pkg.tar.* >/dev/null

# The console script proves the wheel's entry points landed; the imports walk
# every depends entry the package declares (gi/Gtk/AppIndicator, IBus, cairo,
# pyaudio, numpy, requests, tqdm, psutil, evdev, xlib, pynput).
vocalinux --version
python - "$_version" <<'PY' || fail "the installed package does not import or has the wrong version"
import sys
from importlib.metadata import version

assert version("vocalinux") == sys.argv[1], "installed distribution version differs from the sdist"

import vocalinux.main
import vocalinux.ui.tray_indicator
import vocalinux.speech_recognition.recognition_manager
import vocalinux.speech_recognition.command_processor
import vocalinux.text_injection.text_injector
import vocalinux.text_injection.ibus_engine
import vocalinux.ui.keyboard_backends
import pywhispercpp.model

print("   main, tray, recognition, injection and keyboard backends import")
PY

cmp -s "$PKGDIR/PKGBUILD" "$BUILD/PKGBUILD" || fail "the tested PKGBUILD was modified"
cmp -s "$PKGDIR/${pkgname}-${_version}.tar.gz" "$BUILD/${pkgname}-${_version}.tar.gz" \
  || fail "the tested source archive was modified"
echo "PASS: the exact prepared source PKGBUILD builds and installs on current Arch"
if [ "${AUR_SOURCE_ONLY:-0}" = 1 ]; then
  exit 0
fi

echo "== Build vocalinux-bin against a stub AppImage =="
# The -bin package's arch sources are the published release assets, which do
# not exist for an untagged HEAD. A placeholder exercises the same package()
# install path on this arch; the pinned sums still describe the real assets,
# so this stage skips checksum verification — release.yml's updpkgsums keeps
# the published PKGBUILD pinned to the actual files.
BINPKGDIR="$REPO/packaging/aur/vocalinux-bin"
[ -f "$BINPKGDIR/PKGBUILD" ] || fail "$BINPKGDIR/PKGBUILD not found"
# shellcheck source=/dev/null
source "$BINPKGDIR/PKGBUILD"
echo "   building ${pkgname} ${pkgver}-${pkgrel} (tagged _tag=${_tag})"

pacman_retry -S --needed --noconfirm --asdeps "${depends[@]}" >/dev/null

# WORKDIR was handed to `builder` before this stage, so create the bin
# directory as that user — makepkg writes into it as `builder`.
BINBUILD="$WORKDIR/binpkg"
runuser -u builder -- mkdir -p "$BINBUILD"
cp "$BINPKGDIR/PKGBUILD" "$BINPKGDIR/vocalinux.desktop" \
  "$BINPKGDIR/vocalinux.svg" "$BINPKGDIR/LICENSE" "$BINBUILD/"
CARCH="$(uname -m)"
printf 'aur gate stub\n' >"$BINBUILD/Vocalinux-${_tag}-${CARCH}.AppImage"

(
  cd "$BINBUILD"
  runuser -u builder -- makepkg -f --noconfirm --skipchecksums
)

check_namcap "$BINPKGDIR/PKGBUILD"
check_namcap "$BINBUILD"/*.pkg.tar.*

echo "PASS: both PKGBUILDs build on Arch (this commit, not the last tag)"

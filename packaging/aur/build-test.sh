#!/usr/bin/env bash
# Build the AUR package from this checkout, on Arch as it is today.
#
# Usage (the read-only repo mount is enough — the tree is taken via git archive):
#   docker run --rm -v "$PWD:/repo:ro" archlinux:latest \
#     bash /repo/packaging/aur/build-test.sh
#   or: just aur-gate
#
# This is the gate #736 and #757 needed: both breakages reached AUR users
# because nothing ever ran makepkg on the PKGBUILD before a tag published it.
# The published source= points at the tag tarball, which does not exist until
# the tag is pushed, so the gate replaces it with a git archive of HEAD under
# the same filename: build()/package() run unchanged, and the gate answers
# "does this commit build on Arch", not "did the last tag build".
#
# Deliberately archlinux:latest, unpinned: the AUR is a rolling channel and
# both known breakages were Arch moving under us (setuptools 84 in #757). A
# pinned image would test a world that no longer exists.
#
# Two depends cannot come from the repos: python-pywhispercpp is a virtual
# name that the AUR -cpu/-cuda/-rocm backends provide (#579), and
# python-pynput lives in the AUR itself. A stub package with provides=()
# satisfies them so makepkg verifies the full depends set; for the import
# smoke they are pip-installed from the hash-pinned requirements/runtime.txt,
# so the smoke runs the versions we pin, not whatever AUR ships — that drift
# (AUR -cpu is still 1.4.x) is a monitoring job, not this gate.
set -euo pipefail

REPO="${REPO:-/repo}"
PKGDIR="$REPO/packaging/aur/vocalinux"

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

# The base image ships no git; the tree for makepkg comes from git archive.
# safe.directory: the mount is owned by another uid than the container user.
pacman_retry -Sy --needed --noconfirm git >/dev/null
git config --global --add safe.directory '*'
git -C "$REPO" rev-parse --verify HEAD >/dev/null \
  || fail "$REPO is not a git checkout; git archive needs it"

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
pacman_retry -Sy --needed --noconfirm --asdeps base-devel namcap python-pip \
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

echo "== Replace source= with a git archive of this checkout =="
BUILD="$WORKDIR/pkg"
mkdir -p "$BUILD"
# Same filename the published source= uses, and the same directory prefix
# build()/package() cd into — only where the tarball comes from changes.
git -C "$REPO" archive --prefix="${pkgname}-${_tag}/" -o "$BUILD/${pkgname}-${_tag}.tar.gz" HEAD
cp "$PKGDIR/PKGBUILD" "$BUILD/PKGBUILD"
sed -i "s|^source=.*|source=(\"${pkgname}-${_tag}.tar.gz\")|" "$BUILD/PKGBUILD"
# sha256sums=('SKIP') stays: the real digest is computed at publish time by
# release.yml (updpkgsums), and the archive differs from the tag tarball by
# design.

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
# pyaudio, numpy, requests, tqdm, psutil, lxml, pydub, evdev, xlib, pynput).
vocalinux --version
python - <<'PY' || fail "the installed package does not import"
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

echo "PASS: the PKGBUILD builds on Arch (this commit, not the last tag)"

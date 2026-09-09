#!/usr/bin/env bash
# Run install.sh unattended in a distro container and check what it installed.
#
# Usage (a read-only mount is enough; the tree is taken via git archive):
#   docker run --rm -v "$PWD:/repo:ro" debian:12 bash /repo/scripts/install-test.sh
#   or: just install-gate debian:12
#
# Flags:
#   --auto          the only non-interactive mode; without it the script blocks
#                   on prompts that CI has no TTY to answer.
#   --skip-models   a model is 40-75 MB per container per run, and the download
#                   path is verified by checksum elsewhere.
# Not --skip-system-deps: the per-distro package installation is the point.
#
# install.sh refuses to run as root and calls sudo directly, so the container
# needs an unprivileged user with passwordless sudo. Running it as root would
# exercise a path no user takes.
#
# Local mode only: install.sh chooses it by finding a pyproject.toml naming
# vocalinux in the working directory, so extracting the tree and running from it
# tests this commit. Remote mode (curl | bash, which clones the latest tag) is
# not covered here.
#
# Failure mode to watch: the install pip-installs pywhispercpp against whatever
# CPython the distro ships. Wheels exist for manylinux_2_28, but when a rolling
# distro moves to a new interpreter before upstream publishes wheels for it, pip
# falls back to the sdist and this goes slow or red for an unrelated reason.
set -euo pipefail

REPO="${REPO:-/repo}"
INSTALL_USER="${INSTALL_USER:-installer}"
INSTALL_HOME="/home/$INSTALL_USER"
# Local mode puts the venv inside the tree, which is why the checkout is copied
# rather than written to: a bind-mounted host tree would come back owned by a
# container uid with a venv in it.
TREE="$INSTALL_HOME/vocalinux"

fail() {
  echo "FAIL: $*" >&2
  dump_install_log
  exit 1
}

# install.sh writes a full transcript under ~/.local/state/vocalinux/. It is the
# only place the per-distro package manager output survives.
dump_install_log() {
  local log
  log="$(ls -1t "$INSTALL_HOME"/.local/state/vocalinux/install-*.log 2>/dev/null | head -n1 || true)"
  if [ -n "$log" ]; then
    echo "== last 200 lines of $log ==" >&2
    tail -n 200 "$log" >&2
  else
    echo "== no install log was written ==" >&2
  fi
}

# A mirror going slow mid-transaction leaves a half-populated cache, so
# re-running the same transaction resumes rather than restarts.
retry() {
  local attempt
  for attempt in 1 2 3; do
    "$@" && return 0
    echo "   '$1' failed (attempt $attempt); retrying" >&2
    sleep 5
  done
  return 1
}

[ -f "$REPO/install.sh" ] || fail "$REPO/install.sh not found; mount the checkout at \$REPO"

. /etc/os-release
echo "== ${NAME:-unknown} ${VERSION_ID:-} =="

echo "== Bootstrap: sudo, git and an unprivileged user =="
# The minimum for install.sh to start, and nothing it should install itself.
# git is for the archive below; local mode never calls it.
case "$ID" in
  ubuntu | debian)
    export DEBIAN_FRONTEND=noninteractive
    retry apt-get update -qq
    retry apt-get install -y -qq sudo git ca-certificates >/dev/null
    ;;
  fedora | rhel | centos)
    retry dnf install -y -q sudo git shadow-utils >/dev/null
    ;;
  arch)
    # -Syu, never -Sy: archlinux:latest lags the mirrors, and a partial upgrade
    # would be this script's breakage rather than the installer's.
    retry pacman -Syu --noconfirm --needed sudo git >/dev/null
    ;;
  opensuse-tumbleweed | opensuse-leap | sles)
    retry zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
    retry zypper --non-interactive install -y sudo git >/dev/null
    ;;
  *)
    fail "no bootstrap arm for ID='$ID'; add one when adding the container"
    ;;
esac

id -u "$INSTALL_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$INSTALL_USER"
echo "$INSTALL_USER ALL=(ALL) NOPASSWD: ALL" >"/etc/sudoers.d/$INSTALL_USER"
chmod 0440 "/etc/sudoers.d/$INSTALL_USER"

echo "== Extract this commit into $TREE =="
# git archive, not cp: it takes exactly the tracked files a user gets from a
# clone, so a build artefact or stray venv in the working tree cannot make this
# pass. safe.directory because the mount is owned by another uid.
git config --global --add safe.directory '*'
git -C "$REPO" rev-parse --verify HEAD >/dev/null \
  || fail "$REPO is not a git checkout; git archive needs it"
install -d -o "$INSTALL_USER" -g "$INSTALL_USER" "$TREE"
git -C "$REPO" archive HEAD | tar -x -C "$TREE"
chown -R "$INSTALL_USER:$INSTALL_USER" "$TREE"

# --skip-models below means install.sh never reads this manifest, so nothing in
# this run would notice it leaving the tree. #736 was the release-tag half of
# that shape: an installer verifying models against a manifest the tree it had
# just cloned did not carry. This is the half a local-mode gate can see.
[ -f "$TREE/src/vocalinux/utils/model_checksums.txt" ] \
  || fail "the tree ships no src/vocalinux/utils/model_checksums.txt; install.sh pins model downloads against it"

echo "== Run install.sh --auto --skip-models as $INSTALL_USER =="
# su -, so HOME and PATH are the user's own: install.sh writes wrappers into
# $HOME/.local/bin and reads $HOME throughout, and a run with root's HOME would
# install into the wrong place and still succeed.
START=$(date +%s)
if ! su - "$INSTALL_USER" -c "cd '$TREE' && bash install.sh --auto --skip-models"; then
  fail "install.sh exited non-zero"
fi
echo "   install took $(( $(date +%s) - START ))s"

echo "== Smoke: is there an installation, and does it import =="
VENV="$TREE/venv"
[ -x "$VENV/bin/python" ] || fail "no venv interpreter at $VENV/bin/python"
[ -x "$INSTALL_HOME/.local/bin/vocalinux" ] || fail "no wrapper at ~/.local/bin/vocalinux"
[ -f "$INSTALL_HOME/.local/share/applications/vocalinux.desktop" ] \
  || fail "no desktop entry; install_desktop_entry did not run"

# The injection backends are reached through subprocess, not GI, so no typelib
# import can see one of these missing. These are the binaries every distro's
# package list promises.
for tool in xclip xsel wl-copy; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is not on PATH; install.sh lists it for every distro"
done

# ibus-daemon and the ibus CLI are what ibus_engine.py actually spawns, and only
# the arch and suse lists carry the package that provides them. Fedora's
# ibus-devel and Ubuntu's gir1.2-ibus-1.0 pull the library and the typelib
# alone, so this records the split rather than hiding it: on the two distros
# that do promise the runtime, a swap to a typelib-only package fails here
# instead of on a user's first dictation.
case "$ID" in
  arch | opensuse-tumbleweed | opensuse-leap | sles)
    command -v ibus-daemon >/dev/null 2>&1 \
      || fail "no ibus-daemon: the package list ships the IBus typelib without the runtime ibus_engine.py spawns"
    ;;
esac

# Through the wrapper rather than the venv directly: the wrapper is what the
# desktop entry and the user's PATH invoke, and it carries the GI_TYPELIB_PATH
# and pywhispercpp library-path resolution the bare console script does not.
su - "$INSTALL_USER" -c "'$INSTALL_HOME/.local/bin/vocalinux' --version" \
  || fail "the installed wrapper cannot report a version"

su - "$INSTALL_USER" -c "'$VENV/bin/python' - " <<'PY' || fail "the installation does not import"
import vocalinux.main
import vocalinux.ui.tray_indicator
import vocalinux.speech_recognition.recognition_manager
import vocalinux.text_injection.text_injector
from vocalinux.ui.keyboard_backends import EVDEV_AVAILABLE, PYNPUT_AVAILABLE
import gi

# keyboard_backends imports each backend under `except ImportError`, so the
# import above stays clean when evdev and pynput both failed to build. That is
# the openSUSE failure this gate was extended for, so assert the flags rather
# than the import.
assert EVDEV_AVAILABLE or PYNPUT_AVAILABLE, (
    "no keyboard backend is importable: evdev and pynput both failed to install"
)

# The typelibs the installer is responsible for putting on the system. Both are
# loaded lazily at runtime, so importing the modules above proves nothing about
# them: a missing one would surface on a user's first dictation instead.
gi.require_version("Gtk", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus  # noqa: F401

print(
    "   main, tray, recognition, injection, Gtk and IBus import;"
    f" keyboard backends: evdev={EVDEV_AVAILABLE} pynput={PYNPUT_AVAILABLE}"
)
PY

echo "PASS: install.sh installs on ${NAME:-this distro} (this commit, unattended)"

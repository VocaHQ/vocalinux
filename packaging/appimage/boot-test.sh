#!/usr/bin/env bash
# Start the finished AppImage in a distro container and check it comes up.
#
# Usage: boot-test.sh <path-to-appimage>
#
# The build host cannot catch what this catches: its libraries match what it
# bundled. Both #743 regressions reached a user for that reason — one when the
# bundle loaded a GI library the host also had (libibus), one when the app
# handed its own library path to a host binary (ibus). Old distros prove the
# glibc floor; new ones prove the bundle does not poison what it shells out to.
set -euo pipefail

APPIMAGE="$(readlink -f "${1:?usage: boot-test.sh <path-to-appimage>}")"
export APPIMAGE_EXTRACT_AND_RUN=1

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
export XDG_CONFIG_HOME="$WORKDIR/config" XDG_DATA_HOME="$WORKDIR/data" \
       XDG_CACHE_HOME="$WORKDIR/cache" HOME="$WORKDIR"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"

. /etc/os-release
DISTRO="$PRETTY_NAME"
echo "== $DISTRO (glibc $(ldd --version | head -1 | grep -oE '[0-9]+\.[0-9]+$')) =="

# Xvfb and a session bus for the tray, a GLib CLI to prove host binaries still
# run, the distro's GTK 3 runtime, and xdotool. The last two are not the AppImage
# failing
# to be self-contained: the AppImage excludelist deliberately leaves libX11,
# libharfbuzz and friends to the host, because bundling them breaks more than it
# fixes, and xdotool is a documented host prerequisite for every install path
# except the Flatpak. Any desktop has them; a bare container does not.
echo "== Installing test prerequisites =="
case "${ID}${ID_LIKE:+ $ID_LIKE}" in
  *debian*|ubuntu*)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends \
      xvfb xauth dbus-x11 libglib2.0-bin ca-certificates libgtk-3-0 xdotool >/dev/null
    ;;
  *fedora*|*rhel*)
    dnf install -y -q xorg-x11-server-Xvfb xorg-x11-xauth dbus-x11 glib2 gtk3 xdotool >/dev/null
    ;;
  *arch*)
    pacman -Sy --noconfirm --quiet xorg-server-xvfb xorg-xauth dbus glib2 gtk3 xdotool >/dev/null
    ;;
  *suse*)
    # openSUSE splits these differently: xvfb-run ships on its own, the session
    # bus is in dbus-1-daemon, and the GTK 3 runtime is libgtk-3-0.
    zypper -n -q in xorg-x11-server-Xvfb xvfb-run xauth dbus-1-daemon \
      glib2-tools libgtk-3-0 xdotool >/dev/null
    ;;
  *)
    echo "No package recipe for '$ID'; add one to boot-test.sh" >&2
    exit 1
    ;;
esac

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

echo "== It runs at all =="
"$APPIMAGE" --version || fail "the AppImage does not start on $DISTRO"

# Unpack once so the checks below can use the bundle's own interpreter.
cd "$WORKDIR"
"$APPIMAGE" --appimage-extract >/dev/null
BUNDLE="$WORKDIR/squashfs-root"
bundle_python() {
  APPDIR="$BUNDLE" \
  PYTHONHOME="$BUNDLE/usr" \
  PYTHONPATH="$BUNDLE/usr/lib/python3:$BUNDLE/usr/lib/python3/site-packages" \
  GI_TYPELIB_PATH="$BUNDLE/usr/lib/girepository-1.0" \
  LD_LIBRARY_PATH="$BUNDLE/usr/lib" \
  "$BUNDLE/usr/bin/python3" "$@"
}

echo "== Its GI stack is the bundled one =="
# A typelib whose library is missing loads the host's copy against the bundle's
# older GLib. That is how libibus turned IBus.Engine into a 'void' GType.
bundle_python - <<'PY' || fail "the bundled GI stack does not load"
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus  # noqa: F401

if IBus.Engine.__gtype__.name in ("void", "invalid"):
    raise SystemExit("IBus typelib loaded but its library did not")

from vocalinux.text_injection import text_injector  # noqa: F401

print("  Gtk 3.0, IBus and text_injection all import")
PY

echo "== Host binaries still run when the app spawns them =="
# The bundle's LD_LIBRARY_PATH reaches every child process, so a host tool built
# against a newer GLib dies before it does anything: `ibus` exited with
# `undefined symbol: g_free_sized` and dictated text reached no window.
bundle_python - <<'PY' || fail "a host binary cannot run from inside the bundle"
import subprocess

from vocalinux.utils.host_process import host_env

PROBE = ["gsettings", "--version"]
inherited = subprocess.run(PROBE, capture_output=True, text=True)
sanitized = subprocess.run(PROBE, capture_output=True, text=True, env=host_env())
if sanitized.returncode != 0:
    raise SystemExit(f"gsettings failed with a sanitized environment: {sanitized.stderr.strip()}")
if inherited.returncode != 0:
    print("  host GLib is newer than the bundle's; host_env() is what keeps it working")
print(f"  gsettings {sanitized.stdout.strip()} runs")
PY

echo "== It reaches the tray =="
LOG="$WORKDIR/boot.log"
set +e
timeout -s TERM 40 xvfb-run -a dbus-run-session -- \
  "$APPIMAGE" --debug --start-minimized >"$LOG" 2>&1
status=$?
set -e
# 124 is the timeout we asked for: the app is a tray application, so staying up
# until killed is the pass condition, not an early exit.
if [ "$status" -ne 124 ] && [ "$status" -ne 0 ] && [ "$status" -ne 143 ]; then
  echo "--- last 30 lines ---" >&2
  tail -n 30 "$LOG" >&2
  fail "the app exited with $status instead of running"
fi

grep -q "Initializing Vocalinux" "$LOG" || {
  tail -n 30 "$LOG" >&2
  fail "startup never reached component initialisation"
}
grep -q "Initializing system tray indicator" "$LOG" || {
  tail -n 30 "$LOG" >&2
  fail "startup never reached the tray indicator"
}
if grep -q "Failed to create AppIndicator" "$LOG"; then
  tail -n 30 "$LOG" >&2
  fail "the tray indicator could not be created"
fi
# A traceback before the tray is a failed startup. One after it is the noise
# pynput's X listener makes when we TERM the app under Xvfb, so it is reported
# rather than fatal — the process staying up to the timeout is the real signal.
startup="$WORKDIR/startup.log"
sed -n '1,/Initializing system tray indicator/p' "$LOG" > "$startup"
if grep -q "^Traceback" "$startup"; then
  grep -A 15 "^Traceback" "$startup" | head -n 20 >&2
  fail "startup raised an exception"
fi
if grep -q "^Traceback" "$LOG"; then
  echo "  note: traceback on the shutdown path, after the tray came up" >&2
fi

echo "PASS: $DISTRO"

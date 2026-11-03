#!/usr/bin/env bash
# Install the actual artifact on a disposable Ubuntu host with snapd. This is
# not desktop QA: no microphone, model download, hotkey or typing is exercised.
set -euo pipefail

if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Usage: bash snap/local/smoke-test.sh PATH.snap" >&2
  exit 1
fi
if snap list vocalinux >/dev/null 2>&1; then
  echo "Refusing to replace an existing Vocalinux snap; use a disposable host" >&2
  exit 1
fi

sudo snap install --dangerous "$1"
snap run vocalinux --version
# --shell does not run the application's command chain. Explicitly enter the
# same GNOME desktop-launch environment before checking the installed payload.
PYNPUT_BACKEND=dummy snap run --shell vocalinux -c '
  exec "$SNAP/snap/command-chain/desktop-launch" "$SNAP/bin/python3" \
    "$SNAP/usr/lib/vocalinux/check_runtime.py" --root "$SNAP"
'

#!/usr/bin/env bash
# Refresh the existing Snap Store listing for vocalinux (name already registered).
# Requires: snapcraft login as publisher jatinkrmalik, snapcraft + LXD/Multipass.
# Usage (from repo root, on feat/snap-packaging or a release tag):
#   ./scripts/snap-store-refresh.sh              # pack only
#   ./scripts/snap-store-refresh.sh upload-edge  # pack + upload + release edge
#   ./scripts/snap-store-refresh.sh promote N    # release revision N to candidate then print stable hint
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-pack}"

pack() {
  echo "==> snapcraft pack (version from src/vocalinux/version.py)"
  snapcraft pack
  ls -lh vocalinux_*.snap
}

case "$cmd" in
  pack)
    pack
    ;;
  upload-edge)
    pack
    shopt -s nullglob
    snaps=(vocalinux_*.snap)
    if [[ ${#snaps[@]} -ne 1 ]]; then
      echo "expected exactly one vocalinux_*.snap, found: ${snaps[*]-none}" >&2
      exit 1
    fi
    echo "==> snapcraft upload --release=edge ${snaps[0]}"
    snapcraft upload --release=edge "${snaps[0]}"
    echo "Installed refresh: sudo snap refresh vocalinux --edge || sudo snap install vocalinux --edge"
    ;;
  promote)
    rev="${2:?usage: $0 promote <revision>}"
    echo "==> release revision $rev to candidate"
    snapcraft release vocalinux "$rev" candidate
    echo "QA: sudo snap install vocalinux --candidate  (or refresh)"
    echo "When QA passes: snapcraft release vocalinux $rev stable"
    ;;
  *)
    echo "usage: $0 [pack|upload-edge|promote <rev>]" >&2
    exit 2
    ;;
esac

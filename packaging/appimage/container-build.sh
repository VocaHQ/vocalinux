#!/usr/bin/env bash
# Install what build.sh needs on a bare base image, then run it.
#
# The AppImage inherits the glibc and the GTK stack of whatever host builds it,
# so the host is a pinned input like any other: `base-image` in
# tool_checksums.txt. This script is the part that runs inside that image; the
# way in is docker-build.sh, which both CI and `just appimage` call:
#
#   bash packaging/appimage/docker-build.sh dist/vocalinux-0.16.0-py3-none-any.whl 0.16.0 dist
#
# Only the interpreter and the Python packages are pinned by digest; these apt
# packages are whatever the pinned image resolves to. That is the trade the base
# image makes: its archive is frozen enough for this to be stable, and pinning
# every .deb would cost more than it protects.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    ca-certificates curl git xz-utils file squashfs-tools desktop-file-utils \
    build-essential pkg-config python3 \
    libcairo2-dev libgirepository1.0-dev portaudio19-dev \
    libgtk-3-0 gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 libayatana-appindicator3-1 \
    gir1.2-notify-0.7 libnotify4 \
    gir1.2-dbusmenu-glib-0.4 libdbusmenu-gtk3-4 \
    gir1.2-ibus-1.0 gir1.2-rsvg-2.0 librsvg2-common \
    libvulkan-dev

bash "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/build.sh" "$@"

# A container builds as root, so everything it wrote is root-owned. Hand the
# results back to whoever started it (docker-build.sh passes its own ids).
if [ -n "${HOST_UID:-}" ]; then
    chown -R "${HOST_UID}:${HOST_GID:-$HOST_UID}" "${3:-dist}" \
        "${VOCALINUX_APPIMAGE_CACHE:-/cache}" 2>/dev/null || true
fi

#!/usr/bin/env bash
# Run the AppImage build inside the pinned base image.
#
# Usage: docker-build.sh <path-to-wheel> <version> [output-dir]
#
# This is what CI calls and what you should call locally, so that what you get
# is what CI gets: the base image decides the glibc floor and the GTK version
# the AppImage links against, and building on the host instead means shipping
# whatever that host happens to run.
#
# Honours VOCALINUX_APPIMAGE_REQUIRE_VULKAN / _SKIP_VULKAN like build.sh, and
# keeps the glslc it has to build in VOCALINUX_APPIMAGE_CACHE
# (~/.cache/vocalinux-appimage by default) so the next build reuses it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
IMAGE="$(awk '$1=="base-image" {print $3}' "$REPO_ROOT/packaging/appimage/tool_checksums.txt")"
if [ -z "$IMAGE" ]; then
    echo "No base-image pin in packaging/appimage/tool_checksums.txt" >&2
    exit 1
fi

CACHE="${VOCALINUX_APPIMAGE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/vocalinux-appimage}"
mkdir -p "$CACHE"

# The wheel and output dir are given as host paths; the repo is mounted at the
# same place it lives, so relative arguments keep working inside.
exec docker run --rm \
    -v "$REPO_ROOT:$REPO_ROOT" -w "$REPO_ROOT" \
    -v "$CACHE:/cache" \
    -e VOCALINUX_APPIMAGE_CACHE=/cache \
    -e VOCALINUX_APPIMAGE_REQUIRE_VULKAN \
    -e VOCALINUX_APPIMAGE_SKIP_VULKAN \
    -e CMAKE_BUILD_PARALLEL_LEVEL \
    -e HOST_UID="$(id -u)" \
    -e HOST_GID="$(id -g)" \
    "$IMAGE" bash packaging/appimage/container-build.sh "$@"

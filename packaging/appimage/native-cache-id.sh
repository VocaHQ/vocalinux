#!/usr/bin/env bash
# Id for the reusable pywhispercpp Vulkan build.
#
# That compile depends on the base image (glibc, and the toolchain apt installs
# from it), every pin in tool_checksums.txt, and the pywhispercpp sdist
# install.sh names. It does not depend on the Vocalinux sources, so this id
# ignores the git commit and the Actions run id on purpose: putting either in
# the cache key would rebuild on every push.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
pins="${VOCALINUX_PINS:-$repo/packaging/appimage/tool_checksums.txt}"
install_sh="${VOCALINUX_INSTALL_SH:-$repo/install.sh}"

base="$(awk '$1=="base-image" {print $3; exit}' "$pins")"
if [ -z "$base" ]; then
    echo "No base-image pin in $pins" >&2
    exit 1
fi
pywhispercpp="$(sed -n 's/^PYWHISPERCPP_VERSION="\([^"]*\)"/\1/p' "$install_sh" | head -n1)"
if [ -z "$pywhispercpp" ]; then
    echo "Could not read PYWHISPERCPP_VERSION from $install_sh" >&2
    exit 1
fi
pins_hash="$(sha256sum "$pins" | awk '{print $1}')"
printf '%s\n%s\n%s\n' "$base" "$pins_hash" "$pywhispercpp" | sha256sum | awk '{print $1}'

#!/usr/bin/env bash
# Reuse a pywhispercpp build that already contains libggml-vulkan.so.
#
# Sourced by build.sh. A tree without that library is a CPU wheel, and caching
# one would ship it to the next run that asked for Vulkan.
#
# The directory name is the id from native-cache-id.sh plus the architecture.
# The .so is not portable across either.

_NATIVE_CACHE_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pywhispercpp_native_cache_dir() {
    local arch="$1"
    local root id
    root="${VOCALINUX_APPIMAGE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/vocalinux-appimage}"
    id="$(bash "$_NATIVE_CACHE_HERE/native-cache-id.sh")"
    printf '%s\n' "$root/pywhispercpp-vulkan-${arch}-${id}"
}

pywhispercpp_cache_has_vulkan() {
    local dir="$1"
    local found
    [ -d "$dir" ] || return 1
    found="$(find "$dir" -name 'libggml-vulkan.so*' -print -quit)"
    [ -n "$found" ]
}

# Copy the pywhispercpp install out of a site-packages directory.
# Leaves the rest of the prefix (Vocalinux, numpy, …) where it is.
pywhispercpp_cache_publish() {
    local site="$1" dest="$2"
    local parent staging pattern backup
    parent="$(dirname "$dest")"
    mkdir -p "$parent"
    staging="$(mktemp -d "$parent/.pywhispercpp-staging-XXXXXX")"
    for pattern in \
        "$site/pywhispercpp" \
        "$site"/pywhispercpp-*.dist-info \
        "$site"/pywhispercpp.libs \
        "$site"/_pywhispercpp* \
        "$site"/libggml*.so* \
        "$site"/libwhisper.so*
    do
        [ -e "$pattern" ] || [ -L "$pattern" ] || continue
        cp -a "$pattern" "$staging/"
    done
    if ! pywhispercpp_cache_has_vulkan "$staging"; then
        rm -rf "$staging"
        echo "Refusing to cache a pywhispercpp build with no libggml-vulkan.so" >&2
        return 1
    fi
    backup="${dest}.replacing"
    rm -rf "$backup"
    if [ -e "$dest" ]; then
        mv "$dest" "$backup"
    fi
    mv "$staging" "$dest"
    rm -rf "$backup"
}

# Replace whatever pywhispercpp the prefix just installed (the CPU wheel) with
# the cached Vulkan build. Other packages in site-packages stay.
pywhispercpp_cache_restore() {
    local src="$1" site="$2"
    if ! pywhispercpp_cache_has_vulkan "$src"; then
        echo "Cached pywhispercpp tree has no libggml-vulkan.so" >&2
        return 1
    fi
    mkdir -p "$site"
    find "$site" -depth \( \
        -name 'pywhispercpp' -o \
        -name 'pywhispercpp.libs' -o \
        -name 'pywhispercpp-*.dist-info' -o \
        -name '_pywhispercpp*' -o \
        -name 'libggml*.so*' -o \
        -name 'libwhisper.so*' \
    \) -exec rm -rf {} + 2>/dev/null || true
    cp -a "$src"/. "$site/"
}

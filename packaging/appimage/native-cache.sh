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
    # Called from `if !`, which disables set -e for this whole function.
    # A failing cp has to return on its own, or a short write becomes the cache.
    parent="$(dirname "$dest")"
    mkdir -p "$parent" || return 1
    staging="$(mktemp -d "$parent/.pywhispercpp-staging-XXXXXX")" || return 1
    for pattern in \
        "$site/pywhispercpp" \
        "$site"/pywhispercpp-*.dist-info \
        "$site"/pywhispercpp.libs \
        "$site"/_pywhispercpp* \
        "$site"/libggml*.so* \
        "$site"/libwhisper.so*
    do
        [ -e "$pattern" ] || [ -L "$pattern" ] || continue
        if ! cp -a "$pattern" "$staging/"; then
            rm -rf "$staging"
            echo "Failed to copy $(basename "$pattern") into the pywhispercpp cache." >&2
            return 1
        fi
    done
    if ! pywhispercpp_cache_has_vulkan "$staging"; then
        rm -rf "$staging"
        echo "Refusing to cache a pywhispercpp build with no libggml-vulkan.so" >&2
        return 1
    fi
    backup="${dest}.replacing"
    rm -rf "$backup"
    if [ -e "$dest" ]; then
        if ! mv "$dest" "$backup"; then
            rm -rf "$staging"
            echo "Failed to move the previous pywhispercpp cache aside." >&2
            return 1
        fi
    fi
    if ! mv "$staging" "$dest"; then
        echo "Failed to publish the pywhispercpp cache." >&2
        if [ -e "$backup" ] && ! mv "$backup" "$dest"; then
            echo "Also failed to restore the previous pywhispercpp cache." >&2
        fi
        rm -rf "$staging"
        return 1
    fi
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
    mkdir -p "$site" || return 1
    find "$site" -depth \( \
        -name 'pywhispercpp' -o \
        -name 'pywhispercpp.libs' -o \
        -name 'pywhispercpp-*.dist-info' -o \
        -name '_pywhispercpp*' -o \
        -name 'libggml*.so*' -o \
        -name 'libwhisper.so*' \
    \) -exec rm -rf {} + 2>/dev/null || true
    if ! cp -a "$src"/. "$site/"; then
        echo "Restoring the cached pywhispercpp tree failed." >&2
        return 1
    fi
}

# 0 when the cached tree is in place. 1 when the caller has to compile.
pywhispercpp_try_restore() {
    local cache_dir="$1"
    local site="$2"
    local vk_lib
    if ! pywhispercpp_cache_has_vulkan "$cache_dir"; then
        return 1
    fi
    echo "== Reusing pywhispercpp Vulkan build (${cache_dir##*/}) =="
    if pywhispercpp_cache_restore "$cache_dir" "$site"; then
        vk_lib="$(find "$site" -name 'libggml-vulkan.so*' -print -quit 2>/dev/null || true)"
        if [ -n "$vk_lib" ]; then
            echo "  found $vk_lib"
            return 0
        fi
    fi
    echo "Cached Vulkan build could not be restored; compiling again." >&2
    return 1
}

# $1 cache dir, $2 site-packages, $3 command to run on a hit, then the compile
# command. A hit does not run the compile command.
pywhispercpp_restore_or_run() {
    local cache_dir="$1"
    local site="$2"
    local on_reuse="$3"
    shift 3
    if pywhispercpp_try_restore "$cache_dir" "$site"; then
        "$on_reuse"
        return $?
    fi
    if [ "$#" -eq 0 ]; then
        echo "No compile command given for the pywhispercpp Vulkan build." >&2
        return 1
    fi
    "$@"
}

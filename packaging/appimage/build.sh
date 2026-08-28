#!/usr/bin/env bash
# Build a relocatable AppImage for Vocalinux, natively for whichever
# architecture this script runs on (x86_64 or aarch64) - no cross-compiling.
#
# Usage: build.sh <path-to-wheel> <version> [output-dir]
#
# Bundles a managed CPython (python-build-standalone, fetched by uv, relocated
# via PYTHONHOME rather than a venv since venvs hard-code absolute paths) plus
# PyGObject/GTK3/AppIndicator/IBus GObject-Introspection typelibs, since
# those are needed by `gi.repository` at runtime and linuxdeploy-plugin-gtk
# does not bundle them (it targets native C GTK apps, which don't need
# introspection data).
#
# Every download is pinned and verified against
# packaging/appimage/tool_checksums.txt, and every Python package comes from the
# hash-pinned requirements/*.txt exports of uv.lock.
#
# Run this inside the base image that file pins - container-build.sh does - or
# the AppImage inherits the glibc and GTK of whatever built it. That is not a
# detail: an AppImage built on Ubuntu 24.04 (glibc 2.39) does not start on
# Debian 12, Ubuntu 22.04 or RHEL 9, which is what we shipped until now.
#
# ponytail: text-injection CLI tools (xdotool/wtype/ydotool) are not
# bundled, same runtime prerequisite as the PyPI install path documented
# in docs/INSTALL.md. Add bundling if users hit missing-binary complaints.
#
# GPU: pip wheels of pywhispercpp are CPU-only. This script rebuilds
# pywhispercpp from source with GGML_VULKAN=1 when Vulkan headers and a
# shader compiler are on the build host. The AppImage uses the host Vulkan
# loader/ICDs at runtime (do not bundle NVIDIA/AMD driver ICDs).
# Set VOCALINUX_APPIMAGE_REQUIRE_VULKAN=1 in CI so a failed rebuild fails
# the job instead of shipping a CPU-only image. Set
# VOCALINUX_APPIMAGE_SKIP_VULKAN=1 to force the CPU wheel.
set -euo pipefail

WHEEL="$1"
VERSION="$2"
OUTDIR="${3:-dist}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Same pywhispercpp release install.sh pins. Read from there rather than repeated
# here: unpinned, this build picks up whatever PyPI published today, which is how
# a 1.5.1 released mid-PR broke the Vulkan rebuild.
PYWHISPERCPP_VERSION="$(sed -n 's/^PYWHISPERCPP_VERSION="\([^"]*\)"/\1/p' "$REPO_ROOT/install.sh" | head -n1)"
if [ -z "$PYWHISPERCPP_VERSION" ]; then
    echo "Could not read PYWHISPERCPP_VERSION from install.sh" >&2
    exit 1
fi
# The bundle installs pywhispercpp from the lock export and the Vulkan rebuild
# reinstalls that same pinned sdist. Two sources of truth that disagree would
# ship one whisper build and link against another, so stop while it is cheap.
LOCKED_PYWHISPERCPP="$(awk -F'==' '/^pywhispercpp==/ {print $2; exit}' \
  "$REPO_ROOT/requirements/vad.txt" | tr -d ' \\')"
if [ "$LOCKED_PYWHISPERCPP" != "$PYWHISPERCPP_VERSION" ]; then
    echo "pywhispercpp is pinned twice and the pins disagree:" >&2
    echo "  install.sh:            $PYWHISPERCPP_VERSION" >&2
    echo "  requirements/vad.txt:  $LOCKED_PYWHISPERCPP" >&2
    echo "Change pyproject.toml and run 'just lock', or fix install.sh." >&2
    exit 1
fi
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|aarch64) ;;
  *) echo "Unsupported architecture: $ARCH (need x86_64 or aarch64)" >&2; exit 1 ;;
esac

# Every download below is looked up here first, so a moved upstream asset fails
# the build instead of quietly changing what ships.
PINS="$REPO_ROOT/packaging/appimage/tool_checksums.txt"

pin_field() {
  local name="$1" field="$2" value
  value="$(awk -v k="$name" -v f="$field" '$1==k {print $f; exit}' "$PINS")"
  if [ -z "$value" ]; then
    echo "No pin named '$name' in $PINS" >&2
    exit 1
  fi
  printf '%s\n' "$value"
}

# Default --retry skips TLS RST (curl 35). GitHub release assets flake that way.
curl_retry() {
  curl --retry 5 --retry-all-errors --retry-delay 2 --fail --silent --show-error --location "$@"
}

# Download the pin named $1 to $2, and refuse to go on unless it hashes right.
fetch_pinned() {
  local name="$1" dest="$2" url expected actual
  url="$(pin_field "$name" 4)"
  expected="$(pin_field "$name" 3)"
  curl_retry -o "$dest" "$url"
  actual="$(sha256sum "$dest" | cut -d' ' -f1)"
  if [ "$actual" != "$expected" ]; then
    echo "Checksum mismatch for $name" >&2
    echo "  url:      $url" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    exit 1
  fi
}

# Checkout of a pinned git tree, shared by the two things that need one.
checkout_pinned() {
  local name="$1" dest="$2" commit
  commit="$(pin_field "$name" 3)"
  mkdir -p "$dest"
  git -C "$dest" init -q
  git -C "$dest" remote add origin "$(pin_field "$name" 4)"
  git -C "$dest" fetch -q --depth 1 origin "$commit"
  git -C "$dest" checkout -q FETCH_HEAD
}

# Seed typelibs Vocalinux imports directly, plus transitive GIR deps that Gtk
# and AppIndicator require (xlib, Dbusmenu, …). Without those, GI falls back to
# the builder's baked-in path (/usr/lib/x86_64-linux-gnu/girepository-1.0), which
# does not exist on Fedora/openSUSE/Arch — startup then reports "missing GTK3".
TYPELIBS=(
  Gtk-3.0 Gdk-3.0 GdkX11-3.0 GdkPixbuf-2.0 GLib-2.0 GObject-2.0 Gio-2.0
  GModule-2.0 Pango-1.0 PangoCairo-1.0 cairo-1.0 HarfBuzz-0.0 Atk-1.0
  freetype2-2.0 fontconfig-2.0 xlib-2.0
  AyatanaAppIndicator3-0.1 AyatanaAppindicator3-0.1 AppIndicator3-0.1
  Dbusmenu-0.4 Notify-0.7 IBus-1.0 Rsvg-2.0
)

# Runtime only needs one tray stack (same order as tray_indicator.py). Prefer
# Ayatana; accept the rare lowercase typelib; legacy AppIndicator3 last.
INDICATOR_TYPELIBS=(
  AyatanaAppIndicator3-0.1 AyatanaAppindicator3-0.1 AppIndicator3-0.1
)

# Shared libs loaded via GI at runtime (not linked into python3), so
# linuxdeploy will not discover them from -e python3 alone.
GI_RUNTIME_LIBS=(
  libappindicator3.so.1
  libayatana-appindicator3.so.1
  libdbusmenu-glib.so.4
  libdbusmenu-gtk3.so.4
  libnotify.so.4
)

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
APPDIR="$WORKDIR/AppDir"
TOOLDIR="$WORKDIR/tools"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$TOOLDIR" "$OUTDIR"

# Nested AppImages need extract-and-run on hosts without usable FUSE.
export APPIMAGE_EXTRACT_AND_RUN="${APPIMAGE_EXTRACT_AND_RUN:-1}"

# Building outside the pinned image inherits that host's glibc and GTK, which is
# the whole bug this pinning exists to stop. Warn rather than refuse: the script
# still has to be runnable by hand when someone is debugging it.
expected_base="$(pin_field base-image 4)"
actual_base="$(. /etc/os-release 2>/dev/null && echo "$ID:$VERSION_ID")"
if [ "$actual_base" != "$expected_base" ]; then
  echo "Warning: building on ${actual_base:-an unknown host}, not the pinned $expected_base." >&2
  echo "         This AppImage will inherit this host's glibc and GTK. Use docker-build.sh." >&2
fi

echo "== Fetching pinned AppImage tooling ($ARCH) =="
fetch_pinned "linuxdeploy-$ARCH" "$TOOLDIR/linuxdeploy"
fetch_pinned "linuxdeploy-plugin-gtk" "$TOOLDIR/linuxdeploy-plugin-gtk.sh"
fetch_pinned "appimagetool-$ARCH" "$TOOLDIR/appimagetool"
chmod +x "$TOOLDIR/linuxdeploy" "$TOOLDIR/linuxdeploy-plugin-gtk.sh" "$TOOLDIR/appimagetool"

echo "== Fetching pinned uv =="
# Reuse the host's uv only when it is the pinned version: uv decides which
# python-build-standalone build the bundle gets and how the wheels resolve, so a
# different one is a different AppImage.
UV_VERSION="$(pin_field "uv-$ARCH" 4 | sed 's|.*/download/\([^/]*\)/.*|\1|')"
if command -v uv >/dev/null 2>&1 && [ "$(uv --version | awk '{print $2}')" = "$UV_VERSION" ]; then
  UV="$(command -v uv)"
else
  fetch_pinned "uv-$ARCH" "$TOOLDIR/uv.tar.gz"
  tar xzf "$TOOLDIR/uv.tar.gz" -C "$TOOLDIR"
  UV="$TOOLDIR/uv-${ARCH}-unknown-linux-gnu/uv"
fi
echo "  uv $UV_VERSION ($UV)"

echo "== Bundling managed CPython =="
# python-build-standalone rather than the build host's interpreter: the host's
# is whatever the image or the developer happens to have, and its stdlib layout
# varies by distro. These builds need glibc 2.17, well under the base image's
# floor, so the interpreter never decides which distros the AppImage runs on.
CPYTHON_VERSION="$(pin_field cpython 3)"
export UV_PYTHON_INSTALL_DIR="$WORKDIR/pyroot"
"$UV" python install "$CPYTHON_VERSION"
PY_BIN="$("$UV" python find "$CPYTHON_VERSION")"
PY_PREFIX="$(cd "$(dirname "$PY_BIN")/.." && pwd)"
PY_VER="${CPYTHON_VERSION%.*}"
echo "  CPython $CPYTHON_VERSION from $PY_PREFIX"
cp -a "$PY_PREFIX/bin" "$PY_PREFIX/lib" "$APPDIR/usr/"
# Drop what only a build or a desktop IDE would want. tkinter goes with its
# extension module and the whole Tcl/Tk runtime behind it: nothing imports it,
# and leaving _tkinter.so without its libraries stops linuxdeploy dead
# ("Could not find dependency: libtcl9.0.so") rather than being ignored.
rm -rf "$APPDIR/usr/lib/python${PY_VER}/test" \
       "$APPDIR/usr/lib/python${PY_VER}/idlelib" \
       "$APPDIR/usr/lib/python${PY_VER}/tkinter" \
       "$APPDIR/usr/lib/python${PY_VER}/lib2to3" \
       "$APPDIR/usr/lib/python${PY_VER}/lib-dynload/_tkinter"*.so \
       "$APPDIR/usr/lib/python${PY_VER}/config-${PY_VER}"*
rm -rf "$APPDIR/usr/lib"/libtcl*.so "$APPDIR/usr/lib"/tcl9* "$APPDIR/usr/lib"/tk9* \
       "$APPDIR/usr/lib"/itcl* "$APPDIR/usr/lib"/thread3*
rm -f "$APPDIR/usr/lib"/libpython*.a
find "$APPDIR/usr/lib/python${PY_VER}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "${APPDIR:?}/usr/lib/python${PY_VER}/site-packages"/*

# Everything lands in the bundle prefix, built against the managed interpreter
# so the extension modules match the one that will run them.
uv_install() {
  "$UV" pip install --python "$PY_BIN" --prefix "$APPDIR/usr" "$@"
}

echo "== Installing Vocalinux + runtime deps into the bundle =="
# From the lock rather than from whatever PyPI serves today. vad.txt is the
# hash-pinned export of the runtime set plus the VAD extra, and is a superset of
# runtime.txt (tests/test_appimage_packaging.py keeps it that way, so this stays
# one resolution instead of two that can disagree). appimage.txt adds the
# PyGObject the exports deliberately leave out. The wheel goes last with
# --no-deps: its dependencies are resolved above, and letting it re-resolve them
# would walk straight back out of the lock.
uv_install --require-hashes -r "$REPO_ROOT/requirements/vad.txt"
# --no-deps: PyGObject declares pycairo, which vad.txt already pinned and
# installed. Without it --require-hashes stops on a requirement appimage.txt
# deliberately does not carry.
uv_install --require-hashes --no-deps -r "$REPO_ROOT/requirements/appimage.txt"
uv_install --no-deps "$WHEEL"

echo "== Adding desktop entry + icon =="
install -Dm644 "$REPO_ROOT/vocalinux.desktop" "$APPDIR/usr/share/applications/vocalinux.desktop"
# AppImage desktop integration expects Exec=AppRun; set WM class for the tray app.
sed -i \
  -e 's|^Exec=.*|Exec=AppRun|' \
  -e '/^StartupWMClass=/d' \
  "$APPDIR/usr/share/applications/vocalinux.desktop"
printf 'StartupWMClass=vocalinux\n' >> "$APPDIR/usr/share/applications/vocalinux.desktop"
install -Dm644 "$REPO_ROOT/resources/icons/scalable/vocalinux.svg" \
  "$APPDIR/usr/share/icons/hicolor/scalable/apps/vocalinux.svg"

copy_typelibs() {
  local dest="$1"
  local require_all="${2:-0}"
  mkdir -p "$dest"
  local typelib found missing=() indicator_found=0
  for typelib in "${TYPELIBS[@]}"; do
    found="$(find /usr/lib /usr/lib64 -name "${typelib}.typelib" 2>/dev/null | head -1 || true)"
    if [ -n "$found" ]; then
      cp "$found" "$dest/"
      case " ${INDICATOR_TYPELIBS[*]} " in
        *" ${typelib} "*) indicator_found=1 ;;
      esac
    else
      missing+=("$typelib")
    fi
  done

  # Tray indicator typelibs are alternates; drop them from the hard-fail list
  # when at least one copied successfully.
  local hard_missing=()
  for typelib in "${missing[@]}"; do
    case " ${INDICATOR_TYPELIBS[*]} " in
      *" ${typelib} "*)
        if [ "$indicator_found" -eq 0 ]; then
          hard_missing+=("$typelib")
        fi
        ;;
      *)
        hard_missing+=("$typelib")
        ;;
    esac
  done

  if [ "$require_all" = "1" ] && [ "${#hard_missing[@]}" -gt 0 ]; then
    echo "Missing required typelibs on the build host:" >&2
    printf '  - %s\n' "${hard_missing[@]}" >&2
    if [ "$indicator_found" -eq 0 ]; then
      echo "Need at least one of: ${INDICATOR_TYPELIBS[*]}" >&2
    fi
    echo "Install the matching gir1.2-* packages and retry." >&2
    exit 1
  fi
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "Warning: typelibs not found on build host (optional/alternate): ${missing[*]}" >&2
  fi
}

copy_gi_runtime_libs() {
  local dest="$1"
  mkdir -p "$dest"
  local lib found
  for lib in "${GI_RUNTIME_LIBS[@]}"; do
    found="$(find /usr/lib /usr/lib64 -name "$lib" 2>/dev/null | head -1 || true)"
    if [ -n "$found" ]; then
      cp -aL "$found" "$dest/"
      # Prefer versioned real files so linuxdeploy can resolve the SONAME.
      if [ -L "$found" ]; then
        real="$(readlink -f "$found")"
        cp -aL "$real" "$dest/" 2>/dev/null || true
      fi
      echo "  bundled $lib from $found"
    else
      echo "Warning: $lib not found on build host (tray/notify may need host libs)" >&2
    fi
  done
}

has_vulkan_build_deps() {
  if [ -f /usr/include/vulkan/vulkan.h ] || pkg-config --exists vulkan 2>/dev/null; then
    :
  else
    return 1
  fi
  command -v g++ >/dev/null 2>&1 || command -v clang++ >/dev/null 2>&1 || return 1
  return 0
}

# cmake and ninja come from pinned wheels, not from the image: the base image
# ships cmake 3.22.1, which is exactly shaderc's floor and below what newer ggml
# releases ask for. Stay on cmake 3.x - 4.0 dropped support for the
# `cmake_minimum_required(VERSION 3.4...3.18)` pywhispercpp still declares.
ensure_build_tools() {
  if [ -n "${BUILD_TOOLS_READY:-}" ]; then
    return 0
  fi
  echo "== Installing pinned build tools (cmake, ninja) =="
  # In a venv, not a --prefix: the wheels ship console scripts that import their
  # own package, and a prefix install leaves them on no interpreter's path.
  "$UV" venv --python "$PY_BIN" "$TOOLDIR/buildtools" >/dev/null
  "$UV" pip install --python "$TOOLDIR/buildtools" \
    --require-hashes -r "$REPO_ROOT/requirements/appimage-tools.txt"
  export PATH="$TOOLDIR/buildtools/bin:$PATH"
  BUILD_TOOLS_READY=1
  echo "  $(cmake --version | head -1), ninja $(ninja --version)"
}

# ggml compiles its Vulkan shaders with glslc and accepts no substitute
# (`find_package(Vulkan COMPONENTS glslc REQUIRED)`), but Ubuntu 22.04 - old
# enough to give the AppImage a usable glibc floor - does not package it at all.
# So build it from the pinned shaderc commit. It takes ~4 minutes on a 4-core
# runner and its only input is that commit, so CI caches the result;
# VOCALINUX_APPIMAGE_CACHE points at the directory to keep it in.
ensure_glslc() {
  if command -v glslc >/dev/null 2>&1; then
    echo "  glslc: $(command -v glslc)"
    return 0
  fi
  local commit cache_dir src
  commit="$(pin_field shaderc 3)"
  cache_dir="${VOCALINUX_APPIMAGE_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/vocalinux-appimage}/glslc-${commit}-${ARCH}"
  if [ ! -x "$cache_dir/glslc" ]; then
    echo "== Building glslc from shaderc ${commit:0:12} (this image packages none) =="
    ensure_build_tools
    src="$WORKDIR/shaderc"
    checkout_pinned shaderc "$src"
    # DEPS pins glslang, SPIRV-Tools and SPIRV-Headers by commit; git-sync-deps
    # checks out exactly those, so the pinned commit fixes the whole tree.
    (cd "$src" && ./utils/git-sync-deps)
    cmake -S "$src" -B "$src/build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSHADERC_SKIP_TESTS=ON -DSHADERC_SKIP_EXAMPLES=ON \
      -DSHADERC_SKIP_COPYRIGHT_CHECK=ON -DSPIRV_SKIP_TESTS=ON \
      -DSPIRV_SKIP_EXECUTABLES=ON >"$WORKDIR/shaderc-cmake.log" 2>&1 || {
        tail -n 30 "$WORKDIR/shaderc-cmake.log" >&2; return 1; }
    cmake --build "$src/build" --target glslc_exe \
      -j"${CMAKE_BUILD_PARALLEL_LEVEL:-$(nproc)}" >"$WORKDIR/shaderc-build.log" 2>&1 || {
        tail -n 30 "$WORKDIR/shaderc-build.log" >&2; return 1; }
    mkdir -p "$cache_dir"
    install -m755 "$src/build/glslc/glslc" "$cache_dir/glslc"
  fi
  export PATH="$cache_dir:$PATH"
  echo "  glslc: $("$cache_dir/glslc" --version | head -1)"
}

# ggml needs Vulkan headers the base image is a decade of releases short of;
# see the pin. Only the compile sees these: the AppImage bundles no loader
# (linuxdeploy's excludelist keeps libvulkan.so.1 out) and uses the host's.
ensure_vulkan_headers() {
  VULKAN_INCLUDE_DIR="$WORKDIR/vulkan-headers/include"
  if [ ! -d "$VULKAN_INCLUDE_DIR" ]; then
    echo "== Fetching pinned Vulkan headers =="
    checkout_pinned vulkan-headers "$WORKDIR/vulkan-headers"
  fi
  echo "  $(sed -n 's/.*VK_HEADER_VERSION \([0-9]*\).*/vulkan headers 1.x.\1/p' \
    "$VULKAN_INCLUDE_DIR/vulkan/vulkan_core.h" | head -1)"
}

remove_appdir_pywhispercpp() {
  find "$APPDIR/usr" -depth \( \
    -name 'pywhispercpp' -o \
    -name 'pywhispercpp.libs' -o \
    -name 'pywhispercpp-*.dist-info' -o \
    -name '_pywhispercpp*' \
  \) -exec rm -rf {} + 2>/dev/null || true
}

copy_whisper_native_libs_to_usr_lib() {
  mkdir -p "$APPDIR/usr/lib"
  local lib
  while IFS= read -r lib; do
    [ -n "$lib" ] || continue
    cp -aL "$lib" "$APPDIR/usr/lib/" 2>/dev/null || cp -a "$lib" "$APPDIR/usr/lib/"
    echo "  staged $(basename "$lib") -> usr/lib"
  done < <(find "$APPDIR/usr" \( -name 'libggml*.so*' -o -name 'libwhisper.so*' \) ! -path '*/usr/lib/*' 2>/dev/null || true)
}

rebuild_pywhispercpp_vulkan() {
  local require_vulkan="${VOCALINUX_APPIMAGE_REQUIRE_VULKAN:-0}"
  if [ "${VOCALINUX_APPIMAGE_SKIP_VULKAN:-0}" = "1" ]; then
    echo "== Skipping pywhispercpp Vulkan rebuild (VOCALINUX_APPIMAGE_SKIP_VULKAN=1) =="
    return 0
  fi

  if ! has_vulkan_build_deps; then
    echo "Vulkan build deps missing (libvulkan-dev plus a C++ compiler)." >&2
    if [ "$require_vulkan" = "1" ]; then
      echo "VOCALINUX_APPIMAGE_REQUIRE_VULKAN=1: refusing to ship a CPU-only AppImage." >&2
      exit 1
    fi
    echo "Warning: AppImage will use the CPU-only pywhispercpp wheel." >&2
    return 0
  fi

  ensure_build_tools
  ensure_vulkan_headers
  if ! ensure_glslc; then
    echo "Could not provide glslc; ggml cannot compile its Vulkan shaders." >&2
    if [ "$require_vulkan" = "1" ]; then
      exit 1
    fi
    echo "Warning: continuing with the CPU-only pywhispercpp wheel." >&2
    return 0
  fi

  echo "== Rebuilding pywhispercpp with Vulkan =="
  remove_appdir_pywhispercpp
  local pip_log="$WORKDIR/pywhispercpp-vulkan.log"
  export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$(nproc)}"
  # Reinstall the same pinned sdist the bundle already carries, hashes and all:
  # a source build is still a download, and this one ends up in ctypes.cdll.
  awk '/^pywhispercpp==/ {found=1; print; next}
       found && /^[[:space:]]/ {print; next}
       found {exit}' "$REPO_ROOT/requirements/vad.txt" > "$WORKDIR/pywhispercpp.txt"
  # Hosts that default cc/c++ to clang (this Cloud Agent image) fail the
  # CMAKE C++ compiler test: clang does not search gcc's libstdc++ path.
  if ! CC="${CC:-gcc}" CXX="${CXX:-g++}" \
      GGML_VULKAN=1 \
      CMAKE_ARGS="-DCMAKE_INSTALL_RPATH=\$ORIGIN -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DVulkan_INCLUDE_DIR=$VULKAN_INCLUDE_DIR" \
      uv_install --verbose --require-hashes --no-deps \
        --reinstall-package pywhispercpp --no-binary pywhispercpp \
        -r "$WORKDIR/pywhispercpp.txt" >"$pip_log" 2>&1; then
    # The tail of this log is the Python traceback that wraps the build, which
    # says nothing about why the compile failed. Lead with the compiler's own
    # errors, then the tail for context.
    echo "pywhispercpp Vulkan rebuild failed." >&2
    grep -E "error:|FAILED:|CMake Error" "$pip_log" 2>/dev/null \
      | head -n 20 | sed 's/^/    /' >&2 || true
    echo "  --- last 40 log lines ---" >&2
    tail -n 40 "$pip_log" 2>/dev/null | sed 's/^/    /' >&2 || true
    if [ "$require_vulkan" = "1" ]; then
      exit 1
    fi
    echo "Warning: continuing with the CPU-only pywhispercpp wheel." >&2
    return 0
  fi

  local vk_lib
  vk_lib="$(find "$APPDIR/usr" -name 'libggml-vulkan.so*' 2>/dev/null | head -1 || true)"
  if [ -z "$vk_lib" ]; then
    echo "Vulkan rebuild did not produce libggml-vulkan.so." >&2
    if [ "$require_vulkan" = "1" ]; then
      tail -n 80 "$pip_log" 2>/dev/null | sed 's/^/    /' >&2 || true
      exit 1
    fi
    echo "Warning: AppImage will use CPU-only pywhispercpp." >&2
    return 0
  fi
  echo "  found $vk_lib"
  copy_whisper_native_libs_to_usr_lib
}

echo "== Copying GObject-Introspection typelibs (not handled by linuxdeploy-plugin-gtk) =="
copy_typelibs "$APPDIR/usr/lib/girepository-1.0" 0

echo "== Copying GI runtime shared libraries (AppIndicator/Notify) =="
copy_gi_runtime_libs "$APPDIR/usr/lib"

echo "== Writing AppRun =="
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONHOME="$HERE/usr"
export PYTHONPATH="$HERE/usr/lib/python3:$HERE/usr/lib/python3/site-packages"
export GI_TYPELIB_PATH="$HERE/usr/lib/girepository-1.0"
export LD_LIBRARY_PATH="$HERE/usr/lib:${LD_LIBRARY_PATH:-}"
export XDG_DATA_DIRS="$HERE/usr/share:${XDG_DATA_DIRS:-/usr/share}"
exec "$HERE/usr/bin/python3" -m vocalinux.main "$@"
APPRUN
# PYTHONPATH above uses a version-agnostic symlink so AppRun doesn't need
# to know the exact interpreter minor version at runtime.
ln -sfn "python${PY_VER}" "$APPDIR/usr/lib/python3"
chmod +x "$APPDIR/AppRun"

rebuild_pywhispercpp_vulkan

echo "== Running linuxdeploy (resolves the shared-library closure + GTK theming) =="
export DEPLOY_GTK_VERSION=3
"$TOOLDIR/linuxdeploy" --appdir "$APPDIR" \
  --plugin gtk \
  -e "$APPDIR/usr/bin/python3" \
  -d "$APPDIR/usr/share/applications/vocalinux.desktop" \
  -i "$APPDIR/usr/share/icons/hicolor/scalable/apps/vocalinux.svg"

# linuxdeploy copies the host's full typelib set; keep those extras (transitive
# GIR deps vary by distro) and re-assert our required seed on top.
echo "== Ensuring required typelibs are present (keeping linuxdeploy extras) =="
copy_typelibs "$APPDIR/usr/lib/girepository-1.0" 1

echo "== Patching linuxdeploy GTK AppRun hook (Wayland-friendly GDK backend) =="
GTK_HOOK="$APPDIR/apprun-hooks/linuxdeploy-plugin-gtk.sh"
if [ -f "$GTK_HOOK" ]; then
  # Upstream forces GDK_BACKEND=x11 even on Wayland, which breaks hover/focus
  # for GTK widgets under Plasma (XWayland). Prefer native Wayland unless the
  # user opts into X11 via VOCALINUX_FORCE_X11=1.
  "$APPDIR/usr/bin/python3" - "$GTK_HOOK" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
text = path.read_text()
replacement = (
    '# Prefer Wayland when available; force X11 only when requested.\n'
    'if [ "${VOCALINUX_FORCE_X11:-0}" = "1" ]; then\n'
    '    export GDK_BACKEND=x11\n'
    'elif [ -n "${WAYLAND_DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then\n'
    '    export GDK_BACKEND=wayland\n'
    'else\n'
    '    export GDK_BACKEND=x11\n'
    'fi'
)
new, n = re.subn(
    r'^[ \t]*export GDK_BACKEND=x11[^\n]*$',
    replacement,
    text,
    count=1,
    flags=re.M,
)
if n != 1:
    raise SystemExit(f"failed to patch GDK_BACKEND in {path} (matches={n})")
path.write_text(new)
print(f"Patched {path}")
PY
else
  echo "Warning: GTK AppRun hook not found at $GTK_HOOK" >&2
fi

echo "== Smoke-testing GI imports without host typelibs =="
# Catch the openSUSE/Fedora class of failure before packaging: Gtk needs xlib
# (and friends) from the bundle when the host GI search path is not Debian's.
smoke_gi_imports() {
  local appdir="$1"
  unshare --user --mount --map-root-user bash -c "
    set -euo pipefail
    mkdir -p /tmp/vocalinux-empty-gi
    for d in /usr/lib/x86_64-linux-gnu/girepository-1.0 \
             /usr/lib/aarch64-linux-gnu/girepository-1.0 \
             /usr/lib/girepository-1.0 \
             /usr/lib64/girepository-1.0; do
      if [ -d \"\$d\" ]; then
        mount --bind /tmp/vocalinux-empty-gi \"\$d\"
      fi
    done
    export PYTHONHOME='$appdir/usr'
    export PYTHONPATH='$appdir/usr/lib/python3:$appdir/usr/lib/python3/site-packages'
    export GI_TYPELIB_PATH='$appdir/usr/lib/girepository-1.0'
    export LD_LIBRARY_PATH='$appdir/usr/lib'
    '$appdir/usr/bin/python3' - <<'PY'
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk  # noqa: F401
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3  # noqa: F401
except (ImportError, ValueError):
    try:
        gi.require_version('AyatanaAppindicator3', '0.1')
        from gi.repository import AyatanaAppindicator3  # noqa: F401
    except (ImportError, ValueError):
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3  # noqa: F401
print('GI smoke OK')
PY
  "
}

if command -v unshare >/dev/null 2>&1 && unshare --user --mount --map-root-user true 2>/dev/null; then
  smoke_gi_imports "$APPDIR"
else
  echo "Warning: unshare unavailable; skipping isolated GI smoke test" >&2
fi

echo "== Packaging AppImage =="
OUTPUT="$OUTDIR/Vocalinux-${VERSION}-${ARCH}.AppImage"
ARCH="$ARCH" "$TOOLDIR/appimagetool" "$APPDIR" "$OUTPUT"
echo "Built $OUTPUT"

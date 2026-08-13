#!/usr/bin/env bash
# Build a relocatable AppImage for Vocalinux, natively for whichever
# architecture this script runs on (x86_64 or aarch64) - no cross-compiling.
#
# Usage: build.sh <path-to-wheel> <version> [output-dir]
#
# Bundles a full copy of the active Python interpreter (relocated via
# PYTHONHOME, not a venv, since venvs hard-code absolute paths) plus
# PyGObject/GTK3/AppIndicator/IBus GObject-Introspection typelibs, since
# those are needed by `gi.repository` at runtime and linuxdeploy-plugin-gtk
# does not bundle them (it targets native C GTK apps, which don't need
# introspection data).
#
# ponytail: text-injection CLI tools (xdotool/wtype/ydotool) are not
# bundled, same runtime prerequisite as the PyPI install path documented
# in docs/INSTALL.md. Add bundling if users hit missing-binary complaints.
#
# GPU note: the pip pywhispercpp wheel is CPU-only. Vulkan/CUDA rebuilds
# stay on install.sh for now; the AppImage logs when GPU libs are absent.
set -euo pipefail

WHEEL="$1"
VERSION="$2"
OUTDIR="${3:-dist}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCH="$(uname -m)"
PYTHON="${PYTHON:-python3}"

case "$ARCH" in
  x86_64|aarch64) ;;
  *) echo "Unsupported architecture: $ARCH (need x86_64 or aarch64)" >&2; exit 1 ;;
esac

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

echo "== Fetching AppImage tooling ($ARCH) =="
curl -fsSL -o "$TOOLDIR/linuxdeploy" \
  "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-${ARCH}.AppImage"
curl -fsSL -o "$TOOLDIR/linuxdeploy-plugin-gtk.sh" \
  https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh
curl -fsSL -o "$TOOLDIR/appimagetool" \
  "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
chmod +x "$TOOLDIR/linuxdeploy" "$TOOLDIR/linuxdeploy-plugin-gtk.sh" "$TOOLDIR/appimagetool"

echo "== Bundling Python runtime ($PYTHON) =="
# Use base_prefix so a venv builder still ships a full stdlib (encodings, etc.).
PY_PREFIX="$("$PYTHON" -c 'import sys; print(sys.base_prefix)')"
PY_VER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_BIN="$("$PYTHON" -c 'import sys; print(sys.base_prefix)')/bin/python${PY_VER}"
if [ ! -x "$PY_BIN" ]; then
  PY_BIN="$("$PYTHON" -c 'import sys; print(sys.base_prefix)')/bin/python3"
fi
if [ ! -x "$PY_BIN" ]; then
  PY_BIN="$("$PYTHON" -c 'import sys; print(sys.executable)')"
fi
cp -L "$PY_BIN" "$APPDIR/usr/bin/python3"
cp -r "$PY_PREFIX/lib/python${PY_VER}" "$APPDIR/usr/lib/python${PY_VER}"
rm -rf "$APPDIR/usr/lib/python${PY_VER}/site-packages"

echo "== Installing Vocalinux + runtime deps into the bundle =="
# --ignore-installed: pip otherwise treats the builder env's packages as
# satisfying deps and skips copying vosk/pywhispercpp/etc. into AppDir.
"$PYTHON" -m pip install --no-cache-dir --ignore-installed --prefix "$APPDIR/usr" \
  "$WHEEL" PyGObject pycairo onnxruntime

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
  python3 - "$GTK_HOOK" <<'PY'
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

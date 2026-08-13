"""Regression guards for AppImage packaging."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SH = REPO_ROOT / "packaging" / "appimage" / "build.sh"

# Typelibs that must ship in the AppImage. xlib/Dbusmenu/GModule/fontconfig are
# transitive GIR deps — pruning them broke Gtk on openSUSE (#585).
REQUIRED_TYPELIBS = (
    "Gtk-3.0",
    "Gdk-3.0",
    "xlib-2.0",
    "GModule-2.0",
    "Dbusmenu-0.4",
    "fontconfig-2.0",
    "Notify-0.7",
)

# Tray stacks are alternates (same order as tray_indicator.py).
INDICATOR_TYPELIBS = (
    "AyatanaAppIndicator3-0.1",
    "AyatanaAppindicator3-0.1",
    "AppIndicator3-0.1",
)


def test_appimage_build_ships_transitive_typelibs():
    text = BUILD_SH.read_text()
    assert "TYPELIBS=(" in text
    # Must not wipe linuxdeploy's typelib set down to a partial allowlist.
    assert 'rm -rf "$APPDIR/usr/lib/girepository-1.0"' not in text
    assert "keeping linuxdeploy extras" in text or "Ensuring required typelibs" in text
    for typelib in REQUIRED_TYPELIBS:
        assert typelib in text, f"missing typelib seed {typelib} in {BUILD_SH}"
    for typelib in INDICATOR_TYPELIBS:
        assert typelib in text, f"missing indicator typelib seed {typelib}"
    assert "INDICATOR_TYPELIBS=" in text
    assert "indicator_found" in text
    assert "Need at least one of:" in text


def test_appimage_build_bundles_gi_runtime_libs():
    text = BUILD_SH.read_text()
    for lib in (
        "libappindicator3.so.1",
        "libayatana-appindicator3.so.1",
        "libdbusmenu-glib.so.4",
        "libdbusmenu-gtk3.so.4",
        "libnotify.so.4",
    ):
        assert lib in text, f"missing GI runtime lib {lib} in {BUILD_SH}"


def test_appimage_build_smokes_gi_without_host_typelibs():
    text = BUILD_SH.read_text()
    assert "smoke_gi_imports" in text
    assert "unshare --user --mount" in text


def test_appimage_build_rebuilds_pywhispercpp_with_vulkan():
    text = BUILD_SH.read_text()
    assert "GGML_VULKAN=1" in text
    assert "libggml-vulkan" in text
    assert "VOCALINUX_APPIMAGE_REQUIRE_VULKAN" in text
    assert "VOCALINUX_APPIMAGE_SKIP_VULKAN" in text
    assert "rebuild_pywhispercpp_vulkan" in text
    assert 'CC="${CC:-gcc}"' in text
    assert 'CXX="${CXX:-g++}"' in text

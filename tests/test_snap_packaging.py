"""Structural tests for Snap packaging (issue #48)."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPCRAFT_YAML = REPO_ROOT / "snap" / "snapcraft.yaml"
DESKTOP_FILE = REPO_ROOT / "snap" / "gui" / "vocalinux.desktop"
SNAP_PNG = REPO_ROOT / "snap" / "gui" / "vocalinux.png"


def test_snapcraft_recipe_and_gui_assets() -> None:
    assert SNAPCRAFT_YAML.is_file()
    doc = yaml.safe_load(SNAPCRAFT_YAML.read_text(encoding="utf-8"))
    assert doc["name"] == "vocalinux"
    assert doc["base"] == "core24"
    assert doc["summary"] == "Free offline voice dictation for Linux"
    assert doc["license"] == "AGPL-3.0-only"
    assert doc["icon"] == "snap/gui/vocalinux.png"
    assert doc["website"] == "https://vocalinux.com"
    assert doc["confinement"] == "strict"
    assert doc["grade"] == "stable"

    plugs = set((doc.get("apps") or {}).get("vocalinux", {}).get("plugs") or [])
    assert "raw-input" in plugs
    assert "audio-record" in plugs
    assert "uinput" in plugs
    stage = doc["parts"]["vocalinux"].get("stage-packages") or []
    assert "ydotool" in stage

    assert DESKTOP_FILE.is_file()
    assert SNAP_PNG.is_file()
    assert SNAP_PNG.stat().st_size > 0


def test_snap_puts_gnome_platform_first_on_ld_library_path() -> None:
    """core24 gdk-pixbuf finds libpixbufloader_svg.so only if gnome-platform wins.

    Stage-packages pull a second gdk-pixbuf (no SVG loader) into
    $SNAP/usr/lib/<triplet>. desktop-launch's query-loaders walks the first
    LD_LIBRARY_PATH entry that ends in that triplet, so gnome-platform must
    come first or About-page SVGs fail with "Image type svg is not supported".
    """
    doc = yaml.safe_load(SNAPCRAFT_YAML.read_text(encoding="utf-8"))
    env = (doc.get("apps") or {}).get("vocalinux", {}).get("environment") or {}
    ld_path = env.get("LD_LIBRARY_PATH")
    assert isinstance(ld_path, str)
    assert ld_path.startswith("$SNAP/gnome-platform/usr/lib/$CRAFT_ARCH_TRIPLET:")
    assert ld_path.endswith(":$LD_LIBRARY_PATH")


def test_snap_docs_warn_that_0162_has_no_uinput_plug() -> None:
    """v0.16.2 edge has no uinput plug; the connect command must not stand alone."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    install = (REPO_ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    update = (REPO_ROOT / "docs" / "UPDATE.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "web" / "src" / "app" / "changelog" / "page.tsx").read_text(
        encoding="utf-8"
    )
    snapcraft = SNAPCRAFT_YAML.read_text(encoding="utf-8")
    for text in (readme, install, update, changelog, snapcraft):
        uinput_lines = "\n".join(line for line in text.splitlines() if "uinput" in line.lower())
        lowered = uinput_lines.lower()
        assert "uinput" in lowered
        assert "plug" in lowered and "no" in lowered
        assert "0.17" not in uinput_lines


def test_snap_strips_pygobject_and_uses_gnome_gi() -> None:
    """Pip must not build PyGObject; GI comes from the gnome extension."""
    text = SNAPCRAFT_YAML.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    override_pull = doc["parts"]["vocalinux"]["override-pull"]
    assert "PyGObject" in override_pull
    assert "pyproject.toml" in override_pull
    assert "gnome extension" in override_pull
    stage = doc["parts"]["vocalinux"].get("stage-packages") or []
    assert "python3-gi" not in stage
    assert "python3-gi-cairo" not in stage


def test_release_publishes_snap_to_edge_and_candidate() -> None:
    """v* tags must ship the snap to the store, not attach it to GitHub."""
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "  publish-snap:\n" in text
    job = text.split("  publish-snap:\n", 1)[1].split("\n  deploy-website:", 1)[0]
    assert "needs: build-and-release" in job
    assert "snapcore/action-build@" in job
    assert "snapcore/action-publish@" in job
    assert "release: edge,candidate" in job
    assert "release: stable" not in job
    assert "SNAPCRAFT_STORE_CREDENTIALS is unset; cannot publish the snap" in job
    assert "gh release upload" not in job
    assert "action-gh-release" not in job
    assert "upload-artifact" not in job

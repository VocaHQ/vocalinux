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

    assert DESKTOP_FILE.is_file()
    assert SNAP_PNG.is_file()
    assert SNAP_PNG.stat().st_size > 0


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

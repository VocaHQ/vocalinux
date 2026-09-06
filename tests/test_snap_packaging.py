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

    plugs = set((doc.get("apps") or {}).get("vocalinux", {}).get("plugs") or [])
    assert "raw-input" in plugs
    assert "audio-record" in plugs

    assert DESKTOP_FILE.is_file()
    assert SNAP_PNG.is_file()
    assert SNAP_PNG.stat().st_size > 0

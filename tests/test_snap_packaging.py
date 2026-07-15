"""Structural tests for Snap packaging (issue #48).

These tests exercise the real shipped recipe on disk so a broken or stale
snapcraft.yaml fails CI. They do not run snapcraft (providers may be absent).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPCRAFT_YAML = REPO_ROOT / "snap" / "snapcraft.yaml"
VERSION_PY = REPO_ROOT / "src" / "vocalinux" / "version.py"
SNAP_README = REPO_ROOT / "packaging" / "snap" / "README.md"
DESKTOP_FILE = REPO_ROOT / "snap" / "gui" / "vocalinux.desktop"
SNAP_ICON = REPO_ROOT / "snap" / "gui" / "vocalinux.svg"


@pytest.fixture(scope="module")
def snapcraft_doc() -> dict:
    """Load and return the real snapcraft.yaml as a dict."""
    assert SNAPCRAFT_YAML.is_file(), f"missing snap recipe at {SNAPCRAFT_YAML}"
    raw = SNAPCRAFT_YAML.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    assert isinstance(doc, dict), "snapcraft.yaml must parse to a mapping"
    return doc


def _app_version_from_source() -> str:
    text = VERSION_PY.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    assert match, "could not parse __version__ from version.py"
    return match.group(1)


def test_snapcraft_yaml_exists_and_names_vocalinux(snapcraft_doc: dict) -> None:
    assert snapcraft_doc["name"] == "vocalinux"
    assert snapcraft_doc["base"] in {"core22", "core24"}
    assert snapcraft_doc["confinement"] in {"strict", "classic", "devmode"}


def test_version_tracks_project_not_issue_draft_only(snapcraft_doc: dict) -> None:
    """Recipe must not be hard-locked solely to the outdated issue #48 draft."""
    app_version = _app_version_from_source()
    recipe_version = str(snapcraft_doc.get("version", ""))
    recipe_text = SNAPCRAFT_YAML.read_text(encoding="utf-8")

    # Stale draft from the GitHub issue must not be the only version story.
    assert recipe_version != "0.2.0-alpha" or app_version == "0.2.0-alpha"
    assert "0.2.0-alpha" not in recipe_version or app_version == "0.2.0-alpha"

    # Prefer adopt-from-source override, or a version matching version.py.
    has_version_override = "craftctl set version" in recipe_text and "version.py" in recipe_text
    matches_source = recipe_version == app_version
    assert has_version_override or matches_source, (
        f"snap version {recipe_version!r} must match {app_version!r} "
        "or set version from version.py in override-pull"
    )


def test_strict_first_ship_or_documented_classic(snapcraft_doc: dict) -> None:
    confinement = snapcraft_doc["confinement"]
    if confinement == "strict":
        return
    # Classic/devmode only acceptable if packaging README documents why.
    readme = SNAP_README.read_text(encoding="utf-8")
    assert "classic" in readme.lower() or "devmode" in readme.lower()


def test_app_entry_and_required_plugs(snapcraft_doc: dict) -> None:
    apps = snapcraft_doc.get("apps") or {}
    assert "vocalinux" in apps, "apps.vocalinux entry required"
    app = apps["vocalinux"]
    assert "command" in app

    plugs = set(app.get("plugs") or [])
    extensions = set(app.get("extensions") or [])

    # Microphone + model download must be explicit on the app.
    assert "audio-record" in plugs
    assert "network" in plugs
    # Global hotkeys (evdev) need raw-input under strict confinement.
    assert "raw-input" in plugs

    # Desktop/X11 either via gnome extension or explicit plugs.
    desktop_ok = "gnome" in extensions or (
        {"desktop", "x11"} <= plugs or {"desktop-legacy", "x11"} <= plugs
    )
    assert desktop_ok, "need gnome extension or desktop+x11 plugs for tray/GUI and injection"


def test_stage_packages_include_injection_helpers(snapcraft_doc: dict) -> None:
    parts = snapcraft_doc.get("parts") or {}
    assert "vocalinux" in parts
    stage = set(parts["vocalinux"].get("stage-packages") or [])
    # X11 injection path used by the app (same idea as Flatpak).
    assert "xdotool" in stage
    assert "xsel" in stage or "xclip" in stage
    # PortAudio runtime for pyaudio.
    assert "libportaudio2" in stage
    # ALSA→Pulse plugins so Settings device list does not abort in PortAudio.
    assert "libasound2-plugins" in stage


def test_alsa_pulse_routing_config_present() -> None:
    """Snap must ship an asound.conf that routes ALSA to PulseAudio."""
    conf = REPO_ROOT / "snap" / "local" / "alsa" / "asound.conf"
    assert conf.is_file()
    text = conf.read_text(encoding="utf-8").lower()
    assert "type pulse" in text
    recipe = SNAPCRAFT_YAML.read_text(encoding="utf-8")
    assert "ALSA_CONFIG_PATH" in recipe
    assert "asound.conf" in recipe


def test_snap_gui_assets_exist() -> None:
    assert DESKTOP_FILE.is_file()
    desktop = DESKTOP_FILE.read_text(encoding="utf-8")
    assert "Name=Vocalinux" in desktop
    assert "Exec=vocalinux" in desktop
    assert SNAP_ICON.is_file()
    assert SNAP_ICON.stat().st_size > 0


def test_packaging_readme_covers_store_strategy() -> None:
    text = SNAP_README.read_text(encoding="utf-8")
    lower = text.lower()
    # Strategy pillars from the goal / issue #48.
    assert "snapcraft" in lower
    assert "register" in lower and "vocalinux" in lower
    assert "edge" in lower and "stable" in lower
    assert "audio-record" in lower
    assert "human" in lower or "maintainer" in lower
    assert "not yet" in lower or "not published" in lower

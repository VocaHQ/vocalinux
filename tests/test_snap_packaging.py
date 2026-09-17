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
    """v0.16.2 edge (rev 7) has no uinput plug; the connect command must not stand alone."""
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
        assert "0.16.2" in uinput_lines or "rev 7" in lowered
        assert "plug" in lowered and "no" in lowered


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


def test_release_attaches_snap_then_tries_the_store() -> None:
    """Store review of uinput must not swallow the GitHub .snap (v0.17.0)."""
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "  build-snap:\n" in text
    assert "  attach-snap:\n" in text
    assert "  publish-snap:\n" in text

    build = text.split("  build-snap:\n", 1)[1].split("\n  attach-snap:", 1)[0]
    assert "snapcore/action-build@" in build
    assert "upload-artifact" in build
    assert "name: snap-amd64" in build
    assert "gh release upload" not in build
    assert "action-publish" not in build

    attach = text.split("  attach-snap:\n", 1)[1].split("\n  publish-snap:", 1)[0]
    assert "needs: [build-and-release, build-snap]" in attach
    assert "gh release upload" in attach
    assert "dist/*.snap" in attach
    assert "--clobber" in attach
    assert "contents: write" in attach
    assert "TAG: ${{ github.ref_name }}" in attach
    assert 'gh release upload "$TAG"' in attach
    assert '"${{ github.ref_name }}"' not in attach

    store = text.split("  publish-snap:\n", 1)[1].split("\n  deploy-website:", 1)[0]
    assert "needs: build-snap" in store
    assert "--release edge,candidate" in store
    assert "release: stable" not in store
    assert "SNAPCRAFT_STORE_CREDENTIALS is unset; cannot publish the snap" in store
    assert "will need manual review" in store
    assert "allow-installation" in store
    assert "continue-on-error" not in store
    assert "snapcore/action-publish" not in store
    assert "SNAP_FILE:" in store
    assert 'snapcraft upload "$SNAP_FILE"' in store
    assert "gh release upload" not in store
    assert "action-gh-release" not in store


def test_release_notes_document_snap_sideload() -> None:
    body = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "snap install --dangerous" in body
    assert "snap connect vocalinux:uinput" in body
    assert "vocalinux_${{ steps.get_version.outputs.VERSION }}_amd64.snap" in body


def test_snap_backfill_workflow_attests_only_the_snap() -> None:
    """Existing tags (v0.17.0) need a dispatch that does not re-attest AppImages."""
    path = REPO_ROOT / ".github" / "workflows" / "snap-backfill.yml"
    text = path.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "snapcore/action-build@" in text
    assert "gh release upload" in text
    assert "SHA256SUMS" in text
    assert "actions/attest-build-provenance@" in text
    assert "subject-path: dist/${{ steps.stage.outputs.name }}" in text
    assert "subject-checksums:" not in text
    assert "  verify:\n" in text
    assert "scripts/verify_release.py" in text
    assert 'python3 scripts/verify_release.py "$TAG"' in text


def test_snap_backfill_dispatch_input_never_reaches_the_shell() -> None:
    """Same rule as verify-release.yml: interpolating the tag into run: is injection."""
    import re

    text = (REPO_ROOT / ".github" / "workflows" / "snap-backfill.yml").read_text(
        encoding="utf-8"
    )
    run_lines = [line for line in text.splitlines() if re.match(r"^\s*-?\s*run:", line)]
    assert run_lines, "found no run: step, so this guard is scanning nothing"
    for line in run_lines:
        assert "${{" not in line, f"a run: step interpolates a template expression: {line.strip()}"
    assert "TAG: ${{ inputs.tag }}" in text
    assert 'gh release upload "$TAG"' in text

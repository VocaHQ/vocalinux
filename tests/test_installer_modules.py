"""Structural guards for the sourced install.sh modules."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install.sh"
MODULE_DIR = REPO_ROOT / "install.d"
PIPELINE = REPO_ROOT / ".github" / "workflows" / "unified-pipeline.yml"
LABELER = REPO_ROOT / ".github" / "labeler.yml"
EXPECTED_MODULES = {
    "desktop.sh",
    "interactive.sh",
    "models.sh",
    "system_dependencies.sh",
}


def test_installer_loads_every_module_from_the_resolved_tree() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'module="$INSTALL_DIR/install.d/$1"' in source
    assert "source_installer_module()" in source
    for module in EXPECTED_MODULES:
        assert module in source

    remote_handoff = source.index("handoff_to_tagged_installer")
    module_loader = source.index("source_installer_module()")
    assert remote_handoff < module_loader


def test_modules_are_shell_syntax_valid_and_safe_to_source() -> None:
    modules = sorted(MODULE_DIR.glob("*.sh"))
    assert {path.name for path in modules} == EXPECTED_MODULES
    for module in modules:
        syntax = subprocess.run(
            ["bash", "-n", str(module)],
            capture_output=True,
            text=True,
        )
        assert syntax.returncode == 0, syntax.stderr

        sourced = subprocess.run(
            ["bash", "-c", 'set -Eeuo pipefail; source "$1"', "bash", str(module)],
            capture_output=True,
            text=True,
        )
        assert sourced.returncode == 0, sourced.stderr
        assert sourced.stdout == ""


def test_entry_point_is_an_orchestrator_not_a_four_thousand_line_monolith() -> None:
    assert len(INSTALLER.read_text(encoding="utf-8").splitlines()) < 3500


def test_module_changes_reach_the_python_ci_jobs() -> None:
    workflow = PIPELINE.read_text(encoding="utf-8")
    assert "- 'install.d/**'" in workflow


def test_module_changes_receive_the_installer_label() -> None:
    labeler = LABELER.read_text(encoding="utf-8")
    installer_rules = labeler[labeler.index("installer:") : labeler.index("\n# Icons")]
    assert '"install.d/**/*"' in installer_rules


def test_interactive_guide_does_not_invent_privacy_or_ranking_claims() -> None:
    source = (MODULE_DIR / "interactive.sh").read_text(encoding="utf-8")
    assert "100% offline" not in source
    assert "never leaves your computer" not in source
    assert "99+" not in source
    assert "Fastest, most accurate" not in source

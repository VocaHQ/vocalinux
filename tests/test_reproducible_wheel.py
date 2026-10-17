"""Exercise byte comparison and ensure failed verification exposes no release files."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# Other legacy tests replace zipfile in sys.modules during collection.
ZIPFILE = getattr(sys, "_vocalinux_real_zipfile", __import__("zipfile"))
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_reproducible_wheel.py"


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load the standalone build tool without importing Vocalinux/GTK."""
    spec = importlib.util.spec_from_file_location("reproducible_wheel", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "zipfile", ZIPFILE)
    return module


def wheel(path: Path, content: str = "payload", year: int = 2020) -> Path:
    """Make a tiny real archive, including independently controllable ZIP metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    info = ZIPFILE.ZipInfo("vocalinux/__init__.py", date_time=(year, 1, 1, 0, 0, 0))
    with ZIPFILE.ZipFile(path, "w") as archive:
        archive.writestr(info, content)
    return path


def test_identical_wheels_pass(gate: ModuleType, tmp_path: Path) -> None:
    first = wheel(tmp_path / "a/package.whl")
    second = wheel(tmp_path / "b/package.whl")
    report = tmp_path / "comparison.txt"
    gate.compare_wheels(first, second, report)
    assert "PASS" in report.read_text()
    assert gate.digest(first) in report.read_text()


@pytest.mark.parametrize("difference", ["payload", "metadata", "filename"])
def test_mismatches_fail_without_normalizing_archives(
    gate: ModuleType, tmp_path: Path, difference: str
) -> None:
    first = wheel(tmp_path / "a/package.whl")
    second = wheel(
        tmp_path / "b" / ("other.whl" if difference == "filename" else "package.whl"),
        content="changed" if difference == "payload" else "payload",
        year=2021 if difference == "metadata" else 2020,
    )
    report = tmp_path / "comparison.txt"
    with pytest.raises(RuntimeError, match="reproducibility failed"):
        gate.compare_wheels(first, second, report)
    assert "FAIL" in report.read_text()
    if difference == "payload":
        assert "member content differs: vocalinux/__init__.py" in report.read_text()


def test_snapshot_uses_working_source_without_ignored_build_state(
    gate: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / ".gitignore").write_text("build/\n*.egg-info/\n.venv/\n")
    (source / "tracked.py").write_text("old")
    (source / "deleted.py").write_text("deleted")
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    (source / "tracked.py").write_text("working-tree edit")
    (source / "deleted.py").unlink()
    (source / "new.py").write_text("new file")
    for name in ("build", "stale.egg-info", ".venv"):
        (source / name).mkdir()
        (source / name / "stale").write_text("must not be copied")
    target = tmp_path / "snapshot"
    gate.snapshot(source, target)
    assert (target / "tracked.py").read_text() == "working-tree edit"
    assert (target / "new.py").read_text() == "new file"
    assert {path.name for path in target.iterdir()} == {"tracked.py", "new.py", ".gitignore"}


@pytest.mark.parametrize("mismatch", [False, True])
def test_staging_waits_for_comparison_and_uses_only_canonical_outputs(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: bool
) -> None:
    """Stand in for external tools; real comparison controls the publication boundary."""
    source = tmp_path / "repo"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        cwd=source,
        check=True,
    )
    monkeypatch.setattr(gate, "ROOT", source)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1")
    epoch = subprocess.check_output(
        ["git", "log", "-1", "--format=%ct"], cwd=source, text=True
    ).strip()
    calls = []

    def fake_run(argv: list[str], cwd: Path, env: dict[str, str], log: Path) -> None:
        assert env["SOURCE_DATE_EPOCH"] == epoch
        assert env["UV_PYTHON"] == sys.executable
        calls.append((argv, cwd))
        if "--outdir" in argv:
            dist = Path(argv[argv.index("--outdir") + 1])
            wheel(
                dist / "package.whl",
                "different" if mismatch and dist.name == "independent" else "payload",
            )
            (dist / "package.tar.gz").write_text(dist.name)

    monkeypatch.setattr(gate, "run", fake_run)
    output = tmp_path / "dist"
    diagnostics = tmp_path / "diagnostics"
    if mismatch:
        with pytest.raises(RuntimeError, match="reproducibility failed"):
            gate.build(sys.executable, output, diagnostics)
        assert not output.exists()
    else:
        gate.build(sys.executable, output, diagnostics)
        assert sorted(path.name for path in output.iterdir()) == ["package.tar.gz", "package.whl"]
        assert (output / "package.tar.gz").read_text() == "canonical"
    # A second invocation cleans both successful and partial failed builds.
    calls.clear()
    if mismatch:
        with pytest.raises(RuntimeError, match="reproducibility failed"):
            gate.build(sys.executable, output, diagnostics)
        assert not output.exists()
    else:
        gate.build(sys.executable, output, diagnostics)
        assert (output / "package.tar.gz").read_text() == "canonical"
    builds = [(argv, cwd) for argv, cwd in calls if "--outdir" in argv]
    assert len(builds) == 2
    assert builds[0][0][0] != builds[1][0][0]  # Separate venv interpreters.
    assert builds[0][1] != builds[1][1]  # Separate source/build trees.
    assert all("--no-isolation" in argv for argv, _ in builds)
    venvs = [argv for argv, _ in calls if argv[:2] == ["uv", "venv"]]
    assert len(venvs) == 2
    assert all("--system-site-packages" not in argv for argv in venvs)
    installs = [argv for argv, _ in calls if argv[:3] == ["uv", "pip", "install"]]
    assert len(installs) == 2
    for argv in installs:
        assert {"--require-hashes", "--no-deps", "--only-binary=:all:", "--reinstall"} <= set(argv)


def test_existing_output_is_preserved(gate: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    existing = output / "user-file"
    existing.write_text("keep")
    with pytest.raises(RuntimeError, match="unrecognized or modified output"):
        gate.build(sys.executable, output, tmp_path / "diagnostics")
    assert existing.read_text() == "keep"


@pytest.mark.parametrize("unexpected", ["dist-file", "modified", "diagnostics-file", "symlink"])
def test_cleanup_validates_everything_before_removing_anything(
    gate: ModuleType, tmp_path: Path, unexpected: str
) -> None:
    output = tmp_path / "dist"
    diagnostics = tmp_path / "build/reproducible-wheel"
    canonical = wheel(diagnostics / "canonical/package.whl")
    staged = wheel(output / "package.whl")
    log = diagnostics / "inputs.log"
    log.write_text("previous build")
    unrelated_build = tmp_path / "build/user-file"
    unrelated_build.write_text("keep")
    if unexpected == "dist-file":
        (output / "user-file").write_text("keep")
    elif unexpected == "modified":
        staged.write_text("user modified archive")
    elif unexpected == "diagnostics-file":
        (diagnostics / "user-file").write_text("keep")
    else:
        (diagnostics / "independent").symlink_to(output, target_is_directory=True)
    with pytest.raises(RuntimeError):
        gate.prepare_outputs(output, diagnostics)
    assert canonical.exists()
    assert staged.exists()
    assert log.read_text() == "previous build"
    assert unrelated_build.read_text() == "keep"


def test_cleanup_only_removes_gate_files(gate: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "dist"
    diagnostics = tmp_path / "build/reproducible-wheel"
    wheel(diagnostics / "canonical/package.whl")
    wheel(diagnostics / "independent/package.whl", content="failed build")
    wheel(output / "package.whl")
    (diagnostics / "inputs.log").write_text("previous build")
    unrelated = tmp_path / "build/user-file"
    unrelated.write_text("keep")
    gate.prepare_outputs(output, diagnostics)
    assert not list(output.iterdir())
    assert not list(diagnostics.iterdir())
    assert unrelated.read_text() == "keep"


def test_cleanup_rejects_symlinked_parent(gate: ModuleType, tmp_path: Path) -> None:
    real_build = tmp_path / "real-build"
    real_build.mkdir()
    (tmp_path / "build").symlink_to(real_build, target_is_directory=True)
    diagnostics = tmp_path / "build/reproducible-wheel"
    wheel(diagnostics / "canonical/package.whl")
    output = tmp_path / "dist"
    staged = wheel(output / "package.whl")
    with pytest.raises(RuntimeError, match="through symlink"):
        gate.prepare_outputs(output, diagnostics)
    assert staged.exists()
    assert (real_build / "reproducible-wheel/canonical/package.whl").exists()


def test_cleanup_rejects_aliased_overlap(gate: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    diagnostics = output / ".." / "dist"
    with pytest.raises(RuntimeError, match="must not overlap"):
        gate.prepare_outputs(output, diagnostics)


@pytest.mark.parametrize("interrupt_after", range(1, 7))
def test_interrupted_cleanup_can_be_retried(
    gate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_after: int,
) -> None:
    """Canonical ownership evidence must survive until every staged copy is gone."""
    output = tmp_path / "dist"
    diagnostics = tmp_path / "build/reproducible-wheel"
    for name in ("package.whl", "package.tar.gz"):
        wheel(diagnostics / "canonical" / name)
        wheel(diagnostics / "independent" / name)
        wheel(output / name)
    unrelated = tmp_path / "build/user-file"
    unrelated.write_text("keep")
    unlink = Path.unlink
    deleted = 0

    def interrupted_unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal deleted
        unlink(path, missing_ok=missing_ok)
        deleted += 1
        if deleted == interrupt_after:
            raise OSError("simulated interruption")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted_unlink)
        with pytest.raises(OSError, match="simulated interruption"):
            gate.prepare_outputs(output, diagnostics)
    gate.prepare_outputs(output, diagnostics)
    assert not list(output.iterdir())
    assert not list(diagnostics.iterdir())
    assert unrelated.read_text() == "keep"

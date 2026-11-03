"""Exercise the remote gate's witnesses and real bootstrap/clone/handoff offline."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/remote_installer_fixture.py"
TAG = "v0.0.0-fixture"


@pytest.fixture
def helper(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Other suites globally mock zipfile; these wheels must be real archives."""
    monkeypatch.setitem(sys.modules, "zipfile", sys._vocalinux_real_zipfile)
    spec = importlib.util.spec_from_file_location("remote_installer_fixture", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_source(tree: Path) -> None:
    tree.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "install.sh", tree / "install.sh")
    shutil.copyfile(ROOT / "pyproject.toml", tree / "pyproject.toml")
    shutil.copytree(ROOT / "install.d", tree / "install.d", dirs_exist_ok=True)
    (tree / "requirements").mkdir(exist_ok=True)
    for name in ("runtime.txt", "installer-build.txt"):
        shutil.copyfile(ROOT / "requirements" / name, tree / "requirements" / name)
    (tree / "src/vocalinux").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "src/vocalinux/version.py", tree / "src/vocalinux/version.py")


def _git(tree: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(tree), *args],
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "gate",
            "GIT_AUTHOR_EMAIL": "gate@local",
            "GIT_COMMITTER_NAME": "gate",
            "GIT_COMMITTER_EMAIL": "gate@local",
        },
        text=True,
        stderr=subprocess.STDOUT,
        timeout=10,
    ).strip()


@pytest.fixture
def releases(tmp_path: Path, helper: ModuleType) -> tuple[Path, Path]:
    """Real tags stop at a missing module, before root checks or system actions."""
    tree, output = tmp_path / "repository", tmp_path / "gate fixtures"
    _git(tmp_path, "init", str(tree))
    for role, tag in (("explicit", TAG), ("latest", f"{TAG}-latest")):
        _copy_source(tree)
        helper.prepare_fixture(tree, output, role)
        (tree / "install.d/system_dependencies.sh").unlink()
        _git(tree, "add", ".")
        _git(tree, "commit", "-m", role)
        _git(tree, "tag", tag)
    # These early-path tests run on the contributor's host, not in the gate's
    # container. Never enumerate/stop their app or reach privileged actions.
    for command, code in (("pgrep", 1), ("sudo", 98)):
        guard = output / "bin" / command
        guard.write_text(f"#!/bin/sh\nexit {code}\n")
        guard.chmod(0o755)
    return tree, output


def _bootstrap(
    tmp_path: Path, releases: tuple[Path, Path], *args: str, latest: str = "unavailable"
) -> subprocess.CompletedProcess:
    tree, output = releases
    home = tmp_path / "isolated home"
    home.mkdir()
    return subprocess.run(
        ["bash", str(output / "bootstrap.sh"), "--auto", "--skip-models", *args],
        cwd=home,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{output / 'bin'}:{os.environ['PATH']}",
            "VOCALINUX_REPO_URL": tree.as_uri(),
            "REMOTE_GATE_LATEST": latest,
            "TMPDIR": str(tmp_path),
            "XDG_STATE_HOME": str(home / "state"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize("explicit", [False, True])
def test_real_bootstrap_selects_release_and_executes_its_installer_and_modules(
    tmp_path: Path, helper: ModuleType, releases: tuple[Path, Path], explicit: bool
) -> None:
    """No extracted installer functions or fake git: run the actual entry point."""
    tree, output = releases
    response = output / "latest.json"
    response.write_text(json.dumps({"tag_name": f"{TAG}-latest"}))
    args = [f"--tag={TAG}"] if explicit else []
    result = _bootstrap(
        tmp_path, releases, *args, latest="unavailable" if explicit else str(response)
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Installer module is missing or unreadable:" in result.stdout + result.stderr
    home = tmp_path / "isolated home"
    clone = home / ".local/share/vocalinux-install"
    tag, role = (TAG, "explicit") if explicit else (f"{TAG}-latest", "latest")
    assert _git(clone, "rev-parse", "HEAD") == _git(tree, "rev-parse", tag)
    assert (home / "remote-gate.trace").read_text().splitlines() == [
        "bootstrap",
        f"installer:{role}",
        *[f"module:{role}:{module}" for module in helper.MODULES[:2]],
    ]
    assert (home / "remote-gate.api").exists() != explicit
    assert not (home / ".local/share/vocalinux/venv").exists()


def test_api_outage_without_tag_fails_with_network_exit_and_hint(
    tmp_path: Path, releases: tuple[Path, Path]
) -> None:
    """Stop with a network error and a --tag hint when latest cannot be resolved."""
    result = _bootstrap(tmp_path, releases)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "No release tag available:" in result.stdout + result.stderr
    assert "Re-run with an explicit release tag" in result.stdout + result.stderr
    assert not (tmp_path / "isolated home/.local/share/vocalinux-install").exists()


def test_nonexistent_tag_does_not_fall_back_to_an_existing_release(
    tmp_path: Path, releases: tuple[Path, Path]
) -> None:
    """Reject a missing tag instead of installing another available release."""
    result = _bootstrap(tmp_path, releases, f"--tag={TAG}-nonexistent")
    assert result.returncode == 3, result.stdout + result.stderr
    assert f"Remote branch {TAG}-nonexistent not found" in result.stdout + result.stderr
    assert "Failed to clone Vocalinux repository" in result.stdout + result.stderr
    assert not (tmp_path / "isolated home/.local/share/vocalinux-install/.git").exists()


def test_handoff_bypass_is_a_behavioral_failure_even_with_the_correct_checkout(
    tmp_path: Path, releases: tuple[Path, Path]
) -> None:
    """Reject a skipped handoff even when the clone points at the requested tag."""
    tree, output = releases
    bootstrap = output / "bootstrap.sh"
    source = bootstrap.read_text()
    before = '    handoff_to_tagged_installer\n    exit "$EXIT_OK"\n'
    assert source.count(before) == 1
    bootstrap.write_text(source.replace(before, "    : # deliberately bypass handoff\n"))
    result = _bootstrap(tmp_path, releases, f"--tag={TAG}")
    assert result.returncode == 97, result.stdout + result.stderr
    assert "bootstrap continued past tagged handoff" in result.stdout + result.stderr
    home = tmp_path / "isolated home"
    assert _git(home / ".local/share/vocalinux-install", "rev-parse", "HEAD") == _git(
        tree, "rev-parse", TAG
    )
    assert (home / "remote-gate.trace").read_text() == "bootstrap\n"


@pytest.mark.parametrize("events", ["bootstrap\n", "bootstrap\ninstaller:latest\n"])
def test_gate_rejects_missing_or_wrong_execution_witnesses(tmp_path: Path, events: str) -> None:
    """Reject traces that omit the tagged installer or execute a different release."""
    gate = (ROOT / "scripts/install-remote-test.sh").read_text()
    assertion = re.search(r"^assert_trace\(\) \{\n.*?^\}", gate, re.M | re.S)
    assert assertion
    (tmp_path / "remote-gate.trace").write_text(events)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"WORK={shlex.quote(str(tmp_path))}\nINSTALL_HOME=$WORK\n"
            'fail() { echo "$*" >&2; exit 1; }\n' + assertion[0] + "\nassert_trace explicit",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "tagged installer and modules did not execute exactly once" in result.stderr


def test_latest_shim_delegates_every_other_url_and_preserves_arguments(
    tmp_path: Path, helper: ModuleType
) -> None:
    """Keep unrelated curl requests and their arguments unchanged."""
    real = tmp_path / "real curl"
    real.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\nexit 17\n')
    real.chmod(0o755)
    shim = tmp_path / "bin/curl"
    helper.write_latest_shim(shim, real)
    # Even a near-match is not the latest endpoint under test.
    args = ["-fsSL", helper.LATEST_ENDPOINT + "/other", "an argument with spaces"]
    result = subprocess.run([str(shim), *args], capture_output=True, text=True, timeout=10)
    assert result.returncode == 17
    assert result.stdout.splitlines() == args


@pytest.mark.parametrize("args", [[], [f"--tag={TAG}"], ["--upgrade"]])
def test_gate_runner_preserves_an_empty_or_explicit_argument_list(args: list[str]) -> None:
    """Start the remote installer without adding or losing arguments."""
    gate = (ROOT / "scripts/install-remote-test.sh").read_text()
    runner = re.search(r"^run_remote_install\(\) \{\n.*?^\}", gate, re.M | re.S)
    assert runner
    result = subprocess.run(
        [
            "bash",
            "-c",
            "BOOTSTRAP='/path with spaces/bootstrap.sh'\n"
            'run_remote_command() { printf "%s\\n" "$1"; }\n'
            + runner[0]
            + '\nrun_remote_install "$@"',
            "runner",
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert shlex.split(result.stdout) == [
        "bash",
        "/path with spaces/bootstrap.sh",
        "--auto",
        "--skip-models",
        *args,
    ]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("role,version", [("explicit", "1.0"), ("latest", "2.0")])
def test_both_export_witnesses_are_real_hash_pinned_installable_wheels(
    tmp_path: Path, helper: ModuleType, role: str, version: str
) -> None:
    """Verify both exports supply hashed wheels that real pip can install offline."""
    tree, output = tmp_path / "tree", tmp_path / "gate fixtures"
    _copy_source(tree)
    helper.prepare_fixture(tree, output, role)
    app_version = runpy.run_path(str(tree / "src/vocalinux/version.py"))
    revision = int(version.split(".")[0])
    assert app_version["__version__"] == f"0.0.{revision}"
    assert app_version["__version_info__"] == (0, 0, revision)
    witnesses = []
    for name in ("runtime.txt", "installer-build.txt"):
        original = (ROOT / "requirements" / name).read_text()
        actual = (tree / "requirements" / name).read_text()
        assert actual.startswith(original)
        witnesses.append(actual[len(original) :])
    requirements = tmp_path / "witnesses.txt"
    requirements.write_text("".join(witnesses))
    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True, timeout=30
    )
    python = str(venv / "bin/python")
    result = subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--require-hashes",
            "-r",
            str(requirements),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    subprocess.run(
        [
            python,
            "-c",
            "from importlib.metadata import version; "
            f"assert version('vocalinux-remote-build-fixture') == {version!r}; "
            f"assert version('vocalinux-remote-runtime-fixture') == {version!r}",
        ],
        check=True,
        timeout=10,
    )

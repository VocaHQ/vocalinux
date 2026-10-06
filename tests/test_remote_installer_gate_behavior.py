"""Check the remote gate's failure oracles with deliberately incorrect outcomes."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "scripts/remote-install-test.sh"


def run_helpers(tmp_path: Path, command: str) -> subprocess.CompletedProcess:
    """Load gate definitions without running its container bootstrap."""
    source = GATE.read_text().split('[ -f "$REPO/install.sh" ] || fail', 1)[0]
    return subprocess.run(
        ["bash", "-c", source + "\n" + command],
        cwd=tmp_path,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("kind", ["correct", "wrong-status", "wrong-reason", "success"])
def test_negative_case_requires_status_and_reason(tmp_path: Path, kind: str) -> None:
    """A clone ownership error must not masquerade as a missing tag."""
    status = {"correct": 3, "wrong-status": 1, "wrong-reason": 3, "success": 0}[kind]
    message = "dubious ownership" if kind == "wrong-reason" else "expected failure"
    result = run_helpers(
        tmp_path,
        f"""
RUN_LOG=case.log
dump_install_log() {{ :; }}
run_bootstrap() {{ printf '%s\\n' {shlex.quote(message)} >"$RUN_LOG"; return {status}; }}
expect_bootstrap_failure 3 fail 'expected failure' --auto
""",
    )
    assert (result.returncode == 0) == (kind == "correct"), result.stdout + result.stderr


@pytest.mark.parametrize(
    "kind", ["correct", "no-handoff", "wrong-tag", "lost-arg", "fallthrough", "wrong-pid", "no-pid"]
)
def test_handoff_oracle_rejects_mutated_results(tmp_path: Path, kind: str) -> None:
    """A stale marker or changed argv cannot count as the selected handoff."""
    args = b"--auto\0--venv-dir=/path with spaces/venv\0"
    (tmp_path / "expected").write_bytes(args)
    (tmp_path / "args").write_bytes(b"--auto\0" if kind == "lost-arg" else args)
    if kind != "no-handoff":
        (tmp_path / "marker").write_text("old-tag\n" if kind == "wrong-tag" else "new-tag\n")
    if kind == "fallthrough":
        (tmp_path / "fallthrough").touch()
    (tmp_path / "bootstrap-pid").write_text("123\n")
    if kind != "no-pid":
        (tmp_path / "tag-pid").write_text("456\n" if kind == "wrong-pid" else "123\n")
    result = run_helpers(
        tmp_path,
        """
TAG_MARKER=marker
TAG_ARGS=args
EXPECTED_ARGS=expected
FALLTHROUGH_MARKER=fallthrough
BOOTSTRAP_PID=bootstrap-pid
TAG_PID=tag-pid
dump_install_log() { :; }
assert_tagged_installer_ran new-tag
""",
    )
    assert (result.returncode == 0) == (kind == "correct"), result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["none", "early-pip", "missing-log"])
def test_missing_export_oracle_rejects_early_pip(tmp_path: Path, kind: str) -> None:
    """The expected status and diagnostic alone do not prove pip never ran."""
    if kind != "missing-log":
        (tmp_path / "pip-calls").write_text("pip install\n" if kind == "early-pip" else "")
    result = run_helpers(
        tmp_path,
        """
PIP_CALL_LOG=pip-calls
dump_install_log() { :; }
assert_no_pip_calls
""",
    )
    assert (result.returncode == 0) == (kind == "none"), result.stdout + result.stderr


@pytest.mark.parametrize("handoff", ["exec bash", "bash"])
def test_pid_oracle_checks_real_handoff(tmp_path: Path, handoff: str) -> None:
    """A child installer followed by exit 0 must not masquerade as exec."""
    (tmp_path / "install.sh").write_text("#!/bin/bash\nexit 0\n")
    (tmp_path / "expected").write_bytes(b"--auto\0")
    result = run_helpers(
        tmp_path,
        f"""
FIXTURE_TREE=.
TAG_MARKER=marker
TAG_ARGS=args
EXPECTED_ARGS=expected
BOOTSTRAP_PID=bootstrap-pid
TAG_PID=tag-pid
FALLTHROUGH_MARKER=fallthrough
dump_install_log() {{ :; }}
instrument_fixture_installer new-tag
export VOCALINUX_REMOTE_INSTALL=yes
export REMOTE_INSTALL_TEST_MARKER_FILE=marker
export REMOTE_INSTALL_TEST_ARGS_FILE=args
export REMOTE_INSTALL_TEST_TAG_PID_FILE=tag-pid
bash -c 'printf "%s\\n" "$$" >bootstrap-pid; {handoff} ./install.sh --auto; exit 0'
assert_tagged_installer_ran new-tag
""",
    )
    assert (result.returncode == 0) == (handoff == "exec bash"), result.stdout + result.stderr


@pytest.mark.parametrize("entry", ["module", "script", "not-pip"])
def test_pip_observer_records_only_pip(tmp_path: Path, entry: str) -> None:
    """Use the gate's actual observer with module and console-script entry points."""
    source = GATE.read_text().split("cat >\"$PIP_MONITOR/sitecustomize.py\" <<'PY'\n", 1)[1]
    (tmp_path / "sitecustomize.py").write_text(source.split("\nPY\n", 1)[0])
    (tmp_path / "pip.py").write_text("print('fixture pip')\n")
    (tmp_path / "pip3").write_text("print('fixture pip')\n")
    log = tmp_path / "calls"
    args = {
        "module": ["-m", "pip"],
        "script": [str(tmp_path / "pip3")],
        "not-pip": ["-c", "pass"],
    }
    result = subprocess.run(
        [sys.executable, *args[entry]],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "REMOTE_INSTALL_TEST_PIP_LOG": str(log)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert log.exists() == (entry != "not-pip")
    if log.exists():
        assert log.read_text().strip()

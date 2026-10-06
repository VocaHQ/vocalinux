"""Check the remote gate's failure oracles with deliberately incorrect outcomes."""

import os
import shlex
import subprocess
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


@pytest.mark.parametrize("kind", ["correct", "no-handoff", "wrong-tag", "lost-arg", "fallthrough"])
def test_handoff_oracle_rejects_mutated_results(tmp_path: Path, kind: str) -> None:
    """A stale marker or changed argv cannot count as the selected handoff."""
    args = b"--auto\0--venv-dir=/path with spaces/venv\0"
    (tmp_path / "expected").write_bytes(args)
    (tmp_path / "args").write_bytes(b"--auto\0" if kind == "lost-arg" else args)
    if kind != "no-handoff":
        (tmp_path / "marker").write_text("old-tag\n" if kind == "wrong-tag" else "new-tag\n")
    if kind == "fallthrough":
        (tmp_path / "fallthrough").touch()
    result = run_helpers(
        tmp_path,
        """
TAG_MARKER=marker
TAG_ARGS=args
EXPECTED_ARGS=expected
FALLTHROUGH_MARKER=fallthrough
dump_install_log() { :; }
assert_tagged_installer_ran new-tag
""",
    )
    assert (result.returncode == 0) == (kind == "correct"), result.stdout + result.stderr

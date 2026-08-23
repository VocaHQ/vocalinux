"""Behavioral tests for the installer's Python interpreter selection.

Regression cover for the "Distro PyGObject is not importable in the venv"
failure: running install.sh from an activated virtualenv (e.g. uv's .venv left
active after `just deps`) made it build venv/ from that interpreter, where the
distro's gi is invisible.
"""

import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"

PRELUDE = """
set -uo pipefail

print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
"""


def _source(*functions: str) -> str:
    """Source the named function definitions out of install.sh."""
    return "\n".join(
        f"source <(sed -n '/^{name}() {{$/,/^}}$/p' \"{INSTALL_SH}\")" for name in functions
    )


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", PRELUDE + script], capture_output=True, text=True, timeout=30
    )


def _fake_python(path: Path, version: str, has_gi: bool, base_prefix: str = "") -> Path:
    """Create a stub interpreter answering the probes install.sh runs.

    ``base_prefix`` defaults to the stub's own directory, so two stubs are
    distinct installations unless they are told to share one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/bash\n"
        'if [[ "$*" == *"sys.version_info"* ]]; then\n'
        f'    echo "{version}"\n'
        "    exit 0\n"
        "fi\n"
        'if [[ "$*" == *"sys.base_prefix"* ]]; then\n'
        f'    echo "{base_prefix or path.parent}"\n'
        "    exit 0\n"
        "fi\n"
        'if [[ "$*" == *"import gi"* ]]; then\n'
        f"    exit {0 if has_gi else 1}\n"
        "fi\n"
        "exit 0\n"
    )
    path.chmod(0o755)
    return path


class TestDeactivateInheritedVirtualenv:
    def test_removes_active_venv_from_path(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)

        script = f"""
{_source("deactivate_inherited_virtualenv")}
export VIRTUAL_ENV="{venv}"
export PATH="{venv}/bin:/usr/bin:/bin"
deactivate_inherited_virtualenv
echo "PATH=$PATH"
echo "VIRTUAL_ENV=${{VIRTUAL_ENV:-<unset>}}"
"""
        result = _run(script)
        assert "PATH=/usr/bin:/bin" in result.stdout
        assert "VIRTUAL_ENV=<unset>" in result.stdout

    def test_removes_trailing_slash_venv_and_repeats(self, tmp_path):
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)

        script = f"""
{_source("deactivate_inherited_virtualenv")}
export VIRTUAL_ENV="{venv}/"
export PATH="{venv}/bin:/usr/bin:{venv}/bin:/bin"
deactivate_inherited_virtualenv
echo "PATH=$PATH"
"""
        result = _run(script)
        assert "PATH=/usr/bin:/bin" in result.stdout

    def test_no_active_venv_leaves_path_alone(self):
        script = f"""
{_source("deactivate_inherited_virtualenv")}
unset VIRTUAL_ENV
export PATH="/usr/bin:/bin"
deactivate_inherited_virtualenv
echo "PATH=$PATH"
"""
        result = _run(script)
        assert "PATH=/usr/bin:/bin" in result.stdout
        assert "WARNING" not in result.stdout


class TestSelectPythonInterpreter:
    @staticmethod
    def _select(path_python: Path, system_python: Path, min_version: str = "3.9") -> str:
        script = f"""
PYTHON_CMD="python3"
SYSTEM_PYTHON="{system_python}"
{_source("python_version_of", "python_version_at_least", "python_has_gi", "select_python_interpreter")}
# Keep the system bin dirs: the fake interpreters shadow python3, while
# sort/head that select_python_interpreter relies on stay reachable.
export PATH="{path_python.parent}:/usr/bin:/bin"
select_python_interpreter "{min_version}" && echo "SELECTED=$PYTHON_CMD" || echo "SELECT_FAILED"
"""
        return _run(script).stdout

    def test_prefers_system_python_when_path_python_lacks_gi(self, tmp_path):
        # The reported failure: PATH points at uv's 3.13 venv without gi while
        # the distro built PyGObject for the system 3.14.
        path_python = _fake_python(tmp_path / "pathbin" / "python3", "3.13", has_gi=False)
        system_python = _fake_python(tmp_path / "usrbin" / "python3", "3.14", has_gi=True)

        assert f"SELECTED={system_python}" in self._select(path_python, system_python)

    def test_keeps_path_python_when_it_has_gi(self, tmp_path):
        path_python = _fake_python(tmp_path / "pathbin" / "python3", "3.14", has_gi=True)
        system_python = _fake_python(tmp_path / "usrbin" / "python3", "3.14", has_gi=True)

        assert f"SELECTED={path_python}" in self._select(path_python, system_python)

    def test_falls_back_to_the_system_python_when_no_candidate_has_gi(self, tmp_path):
        # gi is usually installed later in the same run, so the fallback has to
        # pick the interpreter that PyGObject will land on. Picking the PATH one
        # here is exactly the venv-cannot-import-gi bug this file covers.
        path_python = _fake_python(tmp_path / "pathbin" / "python3", "3.13", has_gi=False)
        system_python = _fake_python(tmp_path / "usrbin" / "python3", "3.14", has_gi=False)

        stdout = self._select(path_python, system_python)
        assert f"SELECTED={system_python}" in stdout

    def test_falls_back_to_path_python_when_the_system_one_is_too_old(self, tmp_path):
        """Preferring the system interpreter must not override the floor."""
        path_python = _fake_python(tmp_path / "pathbin" / "python3", "3.12", has_gi=False)
        system_python = _fake_python(tmp_path / "usrbin" / "python3", "3.9", has_gi=False)

        stdout = self._select(path_python, system_python, min_version="3.11")
        assert f"SELECTED={path_python}" in stdout
        assert "SELECTED=python3" not in stdout

    def test_skips_python_below_minimum_version(self, tmp_path):
        too_old = _fake_python(tmp_path / "pathbin" / "python3", "3.6", has_gi=True)
        system_python = _fake_python(tmp_path / "usrbin" / "python3", "3.14", has_gi=False)

        assert f"SELECTED={system_python}" in self._select(too_old, system_python)

    def test_reports_failure_when_no_python_exists(self, tmp_path):
        empty_bin = tmp_path / "empty"
        empty_bin.mkdir()

        script = f"""
PYTHON_CMD="python3"
SYSTEM_PYTHON="{tmp_path}/missing-python3"
{_source("python_version_of", "python_version_at_least", "python_has_gi", "select_python_interpreter")}
export PATH="{empty_bin}"
select_python_interpreter "3.9" && echo "SELECTED=$PYTHON_CMD" || echo "SELECT_FAILED"
"""
        assert "SELECT_FAILED" in _run(script).stdout


class TestVenvMatchesSelectedPython:
    def test_venv_built_from_the_selected_interpreter(self, tmp_path):
        base = str(tmp_path / "usr")
        venv_python = _fake_python(
            tmp_path / "venv" / "bin" / "python", "3.14", has_gi=True, base_prefix=base
        )
        selected = _fake_python(tmp_path / "usr" / "python3", "3.14", has_gi=True, base_prefix=base)

        script = f"""
VENV_DIR="{venv_python.parents[1]}"
PYTHON_CMD="{selected}"
{_source("python_base_prefix", "venv_matches_selected_python")}
venv_matches_selected_python && echo "MATCH" || echo "MISMATCH"
"""
        result = _run(script)
        assert "MATCH" in result.stdout

    def test_stale_venv_from_other_interpreter(self, tmp_path):
        venv_python = _fake_python(tmp_path / "venv" / "bin" / "python", "3.13", has_gi=False)
        selected = _fake_python(tmp_path / "usr" / "python3", "3.14", has_gi=True)

        script = f"""
VENV_DIR="{venv_python.parents[1]}"
PYTHON_CMD="{selected}"
{_source("python_base_prefix", "venv_matches_selected_python")}
venv_matches_selected_python && echo "MATCH" || echo "MISMATCH"
"""
        result = _run(script)
        assert "MISMATCH" in result.stdout

    def test_same_version_from_a_different_installation_is_stale(self, tmp_path):
        """A distro 3.12 and a pyenv/uv 3.12 are not interchangeable."""
        venv_python = _fake_python(
            tmp_path / "venv" / "bin" / "python",
            "3.12",
            has_gi=False,
            base_prefix=str(tmp_path / "pyenv"),
        )
        selected = _fake_python(
            tmp_path / "usr" / "python3", "3.12", has_gi=True, base_prefix="/usr"
        )

        script = f"""
VENV_DIR="{venv_python.parents[1]}"
PYTHON_CMD="{selected}"
{_source("python_base_prefix", "venv_matches_selected_python")}
venv_matches_selected_python && echo "MATCH" || echo "MISMATCH"
"""
        result = _run(script)
        assert "MISMATCH" in result.stdout

    def test_missing_venv_python(self, tmp_path):
        selected = _fake_python(tmp_path / "usr" / "python3", "3.14", has_gi=True)

        script = f"""
VENV_DIR="{tmp_path}/nonexistent"
PYTHON_CMD="{selected}"
{_source("python_base_prefix", "venv_matches_selected_python")}
venv_matches_selected_python && echo "MATCH" || echo "MISMATCH"
"""
        result = _run(script)
        assert "MISMATCH" in result.stdout


class TestTheFloorIsTheInterpreterNotTheReleaseLabel:
    """Any distro that ships a new enough Python must be installable.

    The installer used to reject the Ubuntu family on `VERSION_ID` alone. That
    label is not the requirement and derivatives do not share Ubuntu's numbering:
    Linux Mint 22 and elementary OS 8 are built on Ubuntu 24.04 and ship Python
    3.12, yet report "22" and "8", which sort below "24.04".
    """

    # The two shapes that matter, both handed an interpreter at 3.12: a label
    # that sorts below the base release, and one that is not a release number at
    # all. Pop!_OS and Kubuntu need no case of their own — they use Ubuntu's
    # numbering, so they were never the ones being turned away.
    DERIVATIVES = [
        ("linuxmint", "22"),
        ("elementary", "8"),
    ]

    def test_no_release_number_gate_survives_in_the_installer(self):
        source = INSTALL_SH.read_text(encoding="utf-8")
        assert "check_ubuntu_version" not in source
        assert "requires Ubuntu" not in source, "the installer must not gate on a release label"

    @staticmethod
    def _check(interpreter: Path) -> str:
        script = f"""
PYTHON_CMD="python3"
SYSTEM_PYTHON="{interpreter}"
{_source("python_version_of", "python_version_at_least", "python_has_gi",
         "select_python_interpreter", "check_python_version")}
export PATH="{interpreter.parent}:/usr/bin:/bin"
check_python_version && echo "ACCEPTED" || echo "REJECTED"
"""
        return _run(script).stdout

    @pytest.mark.parametrize("distro_id,version_id", DERIVATIVES)
    def test_a_derivative_with_a_new_enough_python_is_accepted(
        self, tmp_path, distro_id, version_id
    ):
        """What the distro calls itself must not decide this; its Python must."""
        interpreter = _fake_python(
            tmp_path / f"{distro_id}-{version_id}" / "python3", "3.12", has_gi=True
        )
        assert "ACCEPTED" in self._check(interpreter)

    def test_an_interpreter_below_the_floor_is_still_rejected(self, tmp_path):
        """Dropping the label gate must not drop the real one."""
        interpreter = _fake_python(tmp_path / "jammy" / "python3", "3.10", has_gi=True)
        assert "REJECTED" in self._check(interpreter)

    def test_the_floor_itself_is_accepted(self, tmp_path):
        interpreter = _fake_python(tmp_path / "floor" / "python3", "3.11", has_gi=True)
        assert "ACCEPTED" in self._check(interpreter)


def test_installer_never_creates_venv_with_bare_python3():
    source = INSTALL_SH.read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("python3 -m venv") or stripped.startswith("python3 -m virtualenv"):
            raise AssertionError(f"venv must be created via $PYTHON_CMD: {stripped}")

"""Exercise pinned installer calls, including fail-closed and rebuild paths."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
INSTALLER_MODULES = ROOT / "install.d"


def installer_source() -> str:
    """Read the installer entry point and all sourced implementation modules."""
    parts = [INSTALLER, *sorted(INSTALLER_MODULES.glob("*.sh"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in parts)


SELECTOR = ROOT / "scripts/installer_requirements.py"


def _run(tmp_path: Path, command: str, *, fail_pip: bool = False) -> subprocess.CompletedProcess:
    """Run real shell helpers with a recording interpreter in a path with spaces."""
    venv = tmp_path / "test venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin/python"
    python.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "if sys.argv[1:3] == ['-m', 'pip']:\n"
        "    with open(os.environ['PIP_CALLS'], 'a') as log:\n"
        "        log.write(json.dumps(sys.argv[3:]) + '\\n')\n"
        "    sys.exit(int(os.environ.get('FAIL_PIP', '0')))\n"
        f"sys.exit(subprocess.call([{sys.executable!r}, *sys.argv[1:]]))\n"
    )
    python.chmod(0o755)
    functions = [
        "pip_install_reqs_file",
        "pip_install_project_skip_pygobject",
        "pip_install_extras_skip_pygobject",
        "pip_reinstall_pywhispercpp",
        "install_cpu_pywhispercpp",
        "get_pywhispercpp_cmake_args",
        "install_pinned_build_tools",
    ]
    source = "\n".join(
        f"source <(sed -n '/^{name}() {{$/,/^}}$/p' {shlex.quote(str(INSTALLER))})"
        for name in functions
    )
    script = f"""
set -euo pipefail
print_error() {{ echo "$*" >&2; }}
print_info() {{ :; }}
require_distro_gi() {{ :; }}
VENV_DIR={shlex.quote(str(venv))}
INSTALL_DIR={shlex.quote(str(ROOT))}
VOCALINUX_TMP_DIR={shlex.quote(str(tmp_path))}
{source}
{command}
"""
    return subprocess.run(
        ["bash", "-c", script],
        env={**os.environ, "PIP_CALLS": str(tmp_path / "calls"), "FAIL_PIP": str(int(fail_pip))},
        capture_output=True,
        text=True,
        timeout=10,
    )


def _calls(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "calls"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("extra", ["vad", "vosk", "parakeet", "faster_whisper", "whisper", "dev"])
def test_extras_use_committed_hashes(tmp_path: Path, extra: str) -> None:
    result = _run(tmp_path, f'pip_install_extras_skip_pygobject "install log" {extra}')
    assert result.returncode == 0, result.stderr
    (call,) = _calls(tmp_path)
    assert {"--require-hashes", "--no-deps", "--no-build-isolation"} <= set(call)
    assert call[call.index("-r") + 1] == str(ROOT / f"requirements/{extra.replace('_', '-')}.txt")


@pytest.mark.parametrize("editable", [False, True])
def test_project_follows_locked_runtime_without_resolution(tmp_path: Path, editable: bool) -> None:
    args = '-e "project directory"' if editable else '"project directory"'
    result = _run(tmp_path, f"pip_install_project_skip_pygobject log {args}")
    assert result.returncode == 0, result.stderr
    runtime, project = _calls(tmp_path)
    assert runtime[runtime.index("-r") + 1].endswith("/requirements/runtime.txt")
    assert "--require-hashes" in runtime
    assert {"--no-deps", "--no-build-isolation"} <= set(project)
    assert ("-e" in project) == editable
    assert project[-1] == "project directory"


def test_failed_dependencies_never_install_project(tmp_path: Path) -> None:
    result = _run(tmp_path, "pip_install_project_skip_pygobject log .", fail_pip=True)
    assert result.returncode != 0
    assert len(_calls(tmp_path)) == 1


@pytest.mark.parametrize("kind", ["missing", "empty", "unknown-extra"])
def test_missing_pins_fail_before_pip(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "missing.txt"
    if kind == "empty":
        path.touch()
    command = (
        "pip_install_extras_skip_pygobject log typo"
        if kind == "unknown-extra"
        else f"pip_install_reqs_file log {shlex.quote(str(path))}"
    )
    result = _run(tmp_path, command)
    assert result.returncode != 0
    assert not _calls(tmp_path)


@pytest.mark.parametrize("backend", ["cpu", "vulkan", "cuda"])
def test_rebuild_uses_only_locked_pywhispercpp(tmp_path: Path, backend: str) -> None:
    command = (
        "install_cpu_pywhispercpp log"
        if backend == "cpu"
        else f"GGML_{backend.upper()}=1 pip_reinstall_pywhispercpp log --no-binary pywhispercpp"
    )
    result = _run(tmp_path, command)
    assert result.returncode == 0, result.stderr
    (call,) = _calls(tmp_path)
    assert {"--require-hashes", "--no-deps", "--no-build-isolation", "--force-reinstall"} <= set(
        call
    )
    selected = (tmp_path / "pywhispercpp.txt").read_text()
    assert re.findall(r"^([\w.-]+)==", selected, re.M) == ["pywhispercpp"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    package = next(p for p in lock["package"] if p["name"] == "pywhispercpp")
    assert f"pywhispercpp=={package['version']}" in selected
    for artifact in [package["sdist"], *package["wheels"]]:
        assert artifact["hash"] in selected


def test_bootstrap_uses_only_hashed_wheels(tmp_path: Path) -> None:
    result = _run(tmp_path, "install_pinned_build_tools")
    assert result.returncode == 0, result.stderr
    (call,) = _calls(tmp_path)
    assert {"--require-hashes", "--only-binary=:all:", "--ignore-installed", "--no-deps"} <= set(
        call
    )


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_bootstrap_rejects_missing_or_empty_export(tmp_path: Path, kind: str) -> None:
    """Reject missing pins before invoking pip, including in a conditional."""
    requirements = tmp_path / "requirements"
    requirements.mkdir()
    export = requirements / "installer-build.txt"
    if kind == "empty":
        export.touch()
    result = _run(
        tmp_path,
        f"INSTALL_DIR={shlex.quote(str(tmp_path))}\n" "install_pinned_build_tools || exit 23",
    )
    assert result.returncode == 23, result.stdout + result.stderr
    assert f"Missing or empty pinned requirements: {export}" in result.stderr
    assert not _calls(tmp_path)


@pytest.mark.parametrize("remote_aware", [False, True])
def test_remote_handoff_preserves_tagged_behavior(tmp_path: Path, remote_aware: bool) -> None:
    """A main bootstrap must preserve remote behavior for every tag."""
    clone = tmp_path / "old tagged tree"
    clone.mkdir()
    marker = 'CLEANUP_ON_EXIT="${VOCALINUX_REMOTE_INSTALL:-no}"\n' if remote_aware else ""
    (clone / "install.sh").write_text(
        "#!/bin/bash\n"
        + marker
        + 'printf "%s\\n" "${VOCALINUX_REMOTE_INSTALL:-no}" "$PWD" "$@"\n'
        + "helper=activate-vocalinux.sh\n"
        + 'if [ "${VOCALINUX_REMOTE_INSTALL:-no}" = yes ]; then\n'
        + '  mkdir -p "$HOME/.local/bin"\n'
        + '  helper="$HOME/.local/bin/activate-vocalinux.sh"\n'
        + "fi\n"
        + 'printf helper > "$helper"\n'
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    text = INSTALLER.read_text()
    start = text.index("handoff_to_tagged_installer() {")
    end = text.index("\n}", start) + 2
    handoff = text[start:end]
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"set -eu\n{handoff}\ncd {shlex.quote(str(clone))}\n"
            f"INSTALL_DIR={shlex.quote(str(clone))}\n"
            f"VOCALINUX_TMP_DIR={shlex.quote(str(scratch))}\n"
            "INSTALLER_ARGS=(--auto --tag=v0.17.0 --engine=remote_api)\n"
            'print_error() { echo "$*" >&2; }\n'
            "handoff_to_tagged_installer",
        ],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "yes" if remote_aware else "no",
        str(clone),
        "--auto",
        "--tag=v0.17.0",
        "--engine=remote_api",
        f"--venv-dir={home}/.local/share/vocalinux/venv",
    ]
    assert scratch.exists() != remote_aware
    helper = home / ".local/bin/activate-vocalinux.sh"
    assert helper.read_text() == "helper"
    assert not (clone / "activate-vocalinux.sh").exists()


def test_every_pip_install_has_an_explicit_resolution_boundary() -> None:
    """Catch a new engine adding a bare pip install outside the shared helpers."""
    source = INSTALLER.read_text().replace("\\\n", " ")
    installs = [
        line.strip()
        for line in source.splitlines()
        if re.match(r'^\s*(?:pip |"\$VENV_DIR/bin/python" -m pip )install ', line)
    ]
    assert len(installs) >= 4
    for line in installs:
        assert "--no-deps" in line, line
        if "--require-hashes" in line:
            assert "--no-build-isolation" in line or "--only-binary=:all:" in line, line
        else:
            assert '--log "$pip_log" "$@"' in line, line  # the local project only
            assert "--no-build-isolation" in line, line


def test_selector_preserves_python_markers_and_rejects_absent_package(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("installer_requirements", SELECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = ROOT / "requirements/runtime.txt"
    selected = module.select_requirements(source, "numpy")
    assert "python_full_version < '3.12'" in selected
    assert "python_full_version >= '3.12'" in selected
    assert selected.count("numpy==") == 2
    with pytest.raises(ValueError, match="No pin"):
        module.select_requirements(source, "typo")


@pytest.mark.parametrize("minor", [11, 12, 13, 14])
def test_whisper_does_not_replace_runtime_or_build_pins(minor: int) -> None:
    environment = {
        "python_version": f"3.{minor}",
        "python_full_version": f"3.{minor}.0",
        "sys_platform": "linux",
        "platform_machine": "x86_64",
    }

    def pins(name: str) -> dict[str, str]:
        result = {}
        for line in (ROOT / f"requirements/{name}.txt").read_text().splitlines():
            if re.match(r"^[\w.-]+==", line):
                requirement = Requirement(line.rstrip(" \\"))
                if requirement.marker is None or requirement.marker.evaluate(environment):
                    result[requirement.name] = str(requirement.specifier)
        return result

    base = pins("runtime") | pins("installer-build")
    whisper = pins("whisper")
    assert whisper["torch"].endswith("+cpu")
    for name in base.keys() & whisper.keys():
        assert base[name] == whisper[name], name


@pytest.mark.timeout(60)
@pytest.mark.parametrize("tamper", [False, True])
def test_real_pip_checks_hash_before_install(tmp_path: Path, tamper: bool) -> None:
    """Use a local wheel and no index: exercise pip, not a mocked hash checker."""
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True)
    wheel = tmp_path / "pinned_fixture-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("pinned_fixture.py", "VALUE = 1\n")
        archive.writestr(
            "pinned_fixture-1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: pinned-fixture\nVersion: 1.0\n",
        )
        archive.writestr(
            "pinned_fixture-1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("pinned_fixture-1.0.dist-info/RECORD", "")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if tamper:
        with zipfile.ZipFile(wheel, "a") as archive:
            archive.writestr("tampered.txt", "changed bytes")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"pinned-fixture==1.0 --hash=sha256:{digest}\n")
    source = (
        f"source <(sed -n '/^pip_install_reqs_file() {{$/,/^}}$/p' {shlex.quote(str(INSTALLER))})"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'{source}\nVENV_DIR={shlex.quote(str(venv))}\nprint_error() {{ echo "$*" >&2; }}\npip_install_reqs_file {shlex.quote(str(tmp_path / "pip.log"))} {shlex.quote(str(requirements))}',
        ],
        env={
            **os.environ,
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": str(tmp_path),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode != 0) == tamper, result.stdout + result.stderr
    if tamper:
        assert "HASHES" in result.stderr


def test_source_built_runtime_packages_have_build_deps_on_split_devel_distros() -> None:
    """The pinned runtime builds these from source; distro lists that split
    -devel packages must carry their build deps."""
    runtime = (ROOT / "requirements/runtime.txt").read_text(encoding="utf-8")
    installer = installer_source()

    def package_line(prefix: str) -> str:
        return next(line for line in installer.splitlines() if f"local {prefix}=" in line)

    build_deps = {
        "pycairo": ("cairo-devel", "libcairo2-dev"),
        "pyaudio": ("portaudio-devel", "portaudio19-dev"),
        "evdev": ("python3-devel", "python3-dev"),
    }
    for name, (dnf_pkg, apt_pkg) in build_deps.items():
        if not re.search(rf"^{name}==", runtime, re.MULTILINE):
            continue  # wheels-only or dropped: nothing to build
        assert dnf_pkg in package_line("DNF_PACKAGES"), name
        assert apt_pkg in package_line("APT_PACKAGES_UBUNTU"), name
        assert apt_pkg in package_line("APT_PACKAGES_DEBIAN_BASE"), name

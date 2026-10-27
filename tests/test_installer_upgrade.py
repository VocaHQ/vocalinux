"""Behavioral tests for the installer's existing-install upgrade path.

Re-running install.sh used to replay first-time setup with no way to keep the
existing configuration (issue #1009): the mode menu offered only interactive or
automatic, automatic mode forced whisper.cpp regardless of the configured
engine, and nothing said config.json would be kept. The upgrade path detects a
venv + config.json pair, offers "Upgrade (keep current settings)" as the
default, installs dependencies for the configured engine, and never rewrites
the file.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
INTERACTIVE_SH = REPO_ROOT / "install.d" / "interactive.sh"

PRELUDE = """
set -uo pipefail

print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
"""

#: read_prompt writes its answer into the variable named by its last argument,
#: but some calls ("Press Enter to continue...") take no variable name at all:
#: only assign when the last arg is a legal identifier. Answers come from
#: PROMPT_QUEUE so each prompt can be answered differently.
STUBS = """
read_prompt() {
    local last="${@: -1}" ans=""
    if [ ${#PROMPT_QUEUE[@]} -gt 0 ]; then
        ans="${PROMPT_QUEUE[0]}"
        PROMPT_QUEUE=("${PROMPT_QUEUE[@]:1}")
    fi
    if [[ "$last" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        printf -v "$last" '%s' "$ans"
    fi
}
PROMPT_QUEUE=()
"""


def _run(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", PRELUDE + script],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
    )


def _source(*functions: str) -> str:
    """Source the named function definitions out of install.sh."""
    return "\n".join(
        f"source <(sed -n '/^{name}() {{$/,/^}}$/p' {shlex.quote(str(INSTALL_SH))})"
        for name in functions
    )


def _make_install(tmp_path: Path, engine: str = "vosk") -> tuple[Path, Path]:
    """Seed the pair detect_existing_install looks for: venv + config.json."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").touch()
    # set_configured_engine invokes "$VENV_DIR/bin/python"; point it at a real
    # interpreter so the non-upgrade write path can run.
    (venv / "bin" / "python").symlink_to(shutil.which("python3"))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"speech_recognition": {"engine": engine}}))
    return venv, config_dir


@pytest.mark.parametrize(
    ("with_venv", "with_config", "expected"),
    [(True, True, "0"), (True, False, "1"), (False, True, "1"), (False, False, "1")],
)
def test_existing_install_requires_venv_and_config(
    tmp_path: Path, with_venv: bool, with_config: bool, expected: str
) -> None:
    venv = tmp_path / "venv"
    config_dir = tmp_path / "config"
    if with_venv:
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "activate").touch()
    if with_config:
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("{}")

    result = _run(f"""
VENV_DIR={shlex.quote(str(venv))}
CONFIG_DIR={shlex.quote(str(config_dir))}
{_source("detect_existing_install")}
detect_existing_install
echo "EXIT=$?"
""")

    assert f"EXIT={expected}" in result.stdout


def test_upgrade_flag_parses_to_noninteractive_upgrade() -> None:
    """--upgrade selects upgrade semantics without any prompts."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    start = text.index("while [[ $# -gt 0 ]]; do")
    end = text.index("\ndone", start) + len("\ndone")
    arg_parse = text[start:end]
    result = _run(f"""
AUTO_MODE="no"; INTERACTIVE_MODE="yes"; NON_INTERACTIVE="no"; UPGRADE_MODE="no"
INSTALLER_ARGS=()
set -- --upgrade
{arg_parse}
echo "U=$UPGRADE_MODE A=$AUTO_MODE I=$INTERACTIVE_MODE N=$NON_INTERACTIVE"
""")

    assert "U=yes A=yes I=no N=yes" in result.stdout


def test_help_documents_the_upgrade_flag() -> None:
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0
    assert "--upgrade" in result.stdout


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("", "U=yes A=yes I=no N=yes"),  # default: Upgrade
        ("1", "U=yes A=yes I=no N=yes"),
        ("2", "U=no A=no I=yes N=no"),  # Interactive
        ("3", "U=no A=yes I=no N=yes"),  # Automatic
    ],
)
def test_mode_menu_defaults_to_upgrade_on_existing_install(answer: str, expected: str) -> None:
    result = _run(STUBS + f"""
INTERACTIVE_MODE="ask"; AUTO_MODE="no"; NON_INTERACTIVE="no"; UPGRADE_MODE="no"
EXISTING_INSTALL="yes"
{_source("choose_installation_mode")}
PROMPT_QUEUE=("{answer}")
choose_installation_mode
echo "U=$UPGRADE_MODE A=$AUTO_MODE I=$INTERACTIVE_MODE N=$NON_INTERACTIVE"
""")

    assert "Upgrade (keep current settings)" in result.stdout
    assert expected in result.stdout


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("", "U=no A=no I=yes N=no"), ("2", "U=no A=yes I=no N=yes")],
)
def test_mode_menu_is_unchanged_without_an_install(answer: str, expected: str) -> None:
    result = _run(STUBS + f"""
INTERACTIVE_MODE="ask"; AUTO_MODE="no"; NON_INTERACTIVE="no"; UPGRADE_MODE="no"
EXISTING_INSTALL="no"
{_source("choose_installation_mode")}
PROMPT_QUEUE=("{answer}")
choose_installation_mode
echo "U=$UPGRADE_MODE A=$AUTO_MODE I=$INTERACTIVE_MODE N=$NON_INTERACTIVE"
""")

    assert "Upgrade (keep current settings)" not in result.stdout
    assert expected in result.stdout


def test_upgrade_flag_without_an_install_falls_back_to_auto(tmp_path: Path) -> None:
    result = _run(f"""
UPGRADE_MODE="yes"
EXISTING_INSTALL="no"
VENV_DIR={shlex.quote(str(tmp_path / 'venv'))}
CONFIG_DIR={shlex.quote(str(tmp_path / 'config'))}
{_source("resolve_upgrade_request")}
resolve_upgrade_request
echo "U=$UPGRADE_MODE"
""")

    assert "no existing install was found" in result.stdout
    assert "U=no" in result.stdout


@pytest.mark.parametrize("engine", ["vosk", "parakeet", "faster_whisper", "remote_api"])
def test_upgrade_keeps_the_engine_from_config(tmp_path: Path, engine: str) -> None:
    """The configured engine wins over the automatic default (whisper.cpp)."""
    venv, config_dir = _make_install(tmp_path, engine=engine)
    result = _run(f"""
UPGRADE_MODE="yes"; SELECTED_ENGINE=""
VENV_DIR={shlex.quote(str(venv))}
CONFIG_DIR={shlex.quote(str(config_dir))}
{_source("read_configured_engine", "apply_upgrade_engine")}
apply_upgrade_engine
echo "SELECTED=$SELECTED_ENGINE"
""")

    assert f"SELECTED={engine}" in result.stdout
    assert f"keeping configured engine '{engine}'" in result.stdout


def test_upgrade_falls_back_to_default_when_engine_is_unreadable(tmp_path: Path) -> None:
    venv, config_dir = _make_install(tmp_path)
    (config_dir / "config.json").write_text("{not json")
    result = _run(f"""
UPGRADE_MODE="yes"; SELECTED_ENGINE=""
VENV_DIR={shlex.quote(str(venv))}
CONFIG_DIR={shlex.quote(str(config_dir))}
{_source("read_configured_engine", "apply_upgrade_engine")}
apply_upgrade_engine
echo "SELECTED=$SELECTED_ENGINE"
""")

    assert "SELECTED=whisper_cpp" in result.stdout


def test_explicit_engine_flag_wins_over_the_configured_one(tmp_path: Path) -> None:
    venv, config_dir = _make_install(tmp_path, engine="vosk")
    result = _run(f"""
UPGRADE_MODE="yes"; SELECTED_ENGINE="whisper"
VENV_DIR={shlex.quote(str(venv))}
CONFIG_DIR={shlex.quote(str(config_dir))}
{_source("read_configured_engine", "apply_upgrade_engine")}
apply_upgrade_engine
echo "SELECTED=$SELECTED_ENGINE"
""")

    assert "SELECTED=whisper" in result.stdout


def test_upgrade_never_rewrites_config_json(tmp_path: Path) -> None:
    """write_configured_engine must leave the file byte-for-byte identical."""
    venv, config_dir = _make_install(tmp_path, engine="whisper")
    config = config_dir / "config.json"
    original = config.read_bytes()
    result = _run(f"""
UPGRADE_MODE="yes"
VENV_DIR={shlex.quote(str(venv))}
{_source("set_configured_engine", "write_configured_engine")}
write_configured_engine {shlex.quote(str(config))} vosk
""")

    assert result.returncode == 0, result.stderr
    assert "kept unchanged" in result.stdout
    assert config.read_bytes() == original


def test_write_configured_engine_still_writes_outside_upgrade(tmp_path: Path) -> None:
    venv, config_dir = _make_install(tmp_path, engine="whisper")
    config = config_dir / "config.json"
    result = _run(f"""
UPGRADE_MODE="no"
VENV_DIR={shlex.quote(str(venv))}
{_source("set_configured_engine", "write_configured_engine")}
write_configured_engine {shlex.quote(str(config))} vosk
""")

    assert result.returncode == 0, result.stderr
    assert json.loads(config.read_text())["speech_recognition"]["engine"] == "vosk"


def _verify(config_dir: Path, venv_dir: Path, upgrade: bool) -> subprocess.CompletedProcess[str]:
    script = f"""
CONFIG_DIR={shlex.quote(str(config_dir))}
VENV_DIR={shlex.quote(str(venv_dir))}
UPGRADE_MODE="{'yes' if upgrade else 'no'}"
SELECTED_ENGINE=""
{_source(
        "engine_import_module",
        "engine_pip_name",
        "venv_can_import",
        "set_configured_engine",
        "write_configured_engine",
        "verify_configured_engine",
    )}
verify_configured_engine
echo "EXIT=$?"
"""
    return _run(script)


def _stub_venv_python(venv_dir: Path, importable: set[str]) -> None:
    """Real python3 whose chosen engine imports succeed; the rest fail."""
    modules = {"vosk", "whisper", "pywhispercpp.model", "sherpa_onnx", "faster_whisper"}
    python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    branches = "".join(
        'if [[ "$*" == *"import {module}"* ]]; then\n'
        "    if [ {code} -eq 0 ]; then exit 0; fi\n"
        "    echo \"ModuleNotFoundError: No module named '{module}'\" >&2\n"
        "    exit 1\n"
        "fi\n".format(module=module, code=0 if module in importable else 1)
        for module in sorted(modules, key=len, reverse=True)
    )
    python.write_text("#!/bin/bash\n" + branches + 'exec python3 "$@"\n')
    python.chmod(0o755)


def test_upgrade_reports_an_unimportable_engine_instead_of_repairing(
    tmp_path: Path,
) -> None:
    """The repair path rewrites config.json; upgrade mode must not take it."""
    venv = tmp_path / "venv"
    _stub_venv_python(venv, importable=set())
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "config.json"
    config.write_text(json.dumps({"speech_recognition": {"engine": "vosk"}}))

    result = _verify(config_dir, venv, upgrade=True)

    assert "EXIT=1" in result.stdout
    assert "pip install vosk" in result.stdout
    assert json.loads(config.read_text())["speech_recognition"]["engine"] == "vosk"


def test_upgrade_leaves_a_working_configured_engine_alone(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    _stub_venv_python(venv, importable={"vosk"})
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "config.json"
    config.write_text(json.dumps({"speech_recognition": {"engine": "vosk"}}))

    result = _verify(config_dir, venv, upgrade=True)

    assert "EXIT=0" in result.stdout
    assert "WARNING" not in result.stdout
    assert json.loads(config.read_text())["speech_recognition"]["engine"] == "vosk"


def test_guided_setup_offers_upgrade_first_on_existing_install() -> None:
    """run_interactive_install returns before Step 1 when upgrade is chosen."""
    result = _run(STUBS + f"""
EXISTING_INSTALL="yes"
UPGRADE_MODE="no"; INTERACTIVE_MODE="yes"; NON_INTERACTIVE="no"
CONFIG_DIR=/tmp/unused-config; VENV_DIR=/tmp/unused-venv
clear_screen() {{ :; }}
print_header() {{ echo "HEADER: $*"; }}
get_engine_recommendation() {{ echo "REACHED_GUIDED_SETUP"; }}
source {shlex.quote(str(INTERACTIVE_SH))}
PROMPT_QUEUE=("")
run_interactive_install
echo "U=$UPGRADE_MODE N=$NON_INTERACTIVE I=$INTERACTIVE_MODE"
""")

    assert "existing Vocalinux installation was detected" in result.stdout
    assert "REACHED_GUIDED_SETUP" not in result.stdout
    assert "U=yes N=yes I=no" in result.stdout


def test_guided_setup_still_runs_when_the_user_declines_upgrade() -> None:
    result = _run(STUBS + f"""
EXISTING_INSTALL="yes"
UPGRADE_MODE="no"; INTERACTIVE_MODE="yes"; NON_INTERACTIVE="no"
SELECTED_ENGINE=""
CONFIG_DIR=/tmp/unused-config; VENV_DIR=/tmp/unused-venv
DISTRO_NAME="Test"; DISTRO_VERSION="1"
clear_screen() {{ :; }}
print_header() {{ echo "HEADER: $*"; }}
get_engine_recommendation() {{ printf 'whisper_cpp:star:reason'; }}
detect_whispercpp_backends() {{ printf 'cpu:reason:false:no:no:false:false:na:na'; }}
source {shlex.quote(str(INTERACTIVE_SH))}
# "2" declines the upgrade offer; every later prompt gets the default.
PROMPT_QUEUE=("2")
run_interactive_install
echo "U=$UPGRADE_MODE SELECTED=$SELECTED_ENGINE"
""")

    assert "Step 2: Choose Speech Recognition Engine" in result.stdout
    assert "U=no" in result.stdout
    assert "SELECTED=whisper_cpp" in result.stdout


SCRIPT = shutil.which("script")
needs_pty = pytest.mark.skipif(
    SCRIPT is None,
    reason="script(1) is needed to give a piped installer a controlling terminal",
)


@needs_pty
@pytest.mark.timeout(90)
def test_piped_installer_defaults_to_upgrade_on_existing_install(tmp_path: Path) -> None:
    """End to end: `cat install.sh | bash` on an existing install picks upgrade.

    The venv and config.json are seeded under a scratch HOME; --venv-dir points
    the installer at them and --tag skips the release lookup. A bare Enter at
    the mode menu must land on "Upgrade (keep current settings)" and then name
    the configured engine, not the automatic default.
    """
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").touch()
    config_dir = tmp_path / ".config" / "vocalinux"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"speech_recognition": {"engine": "vosk"}}))

    transcript = tmp_path / "upgrade.typescript"
    feeder = tmp_path / "feed-input.sh"
    feeder.write_text(
        "#!/bin/sh\n"
        # Queued until the "Choose mode" prompt reads /dev/tty; a bare Enter
        # exercises the default, which must be the upgrade entry.
        "sleep 1; printf '\\n'\n"
        # Interrupt only once the upgrade marker is on screen: a blind delay
        # loses to a slow runner and Ctrl+C's a healthy installer mid-prompt.
        "for _ in $(seq 1 60); do\n"
        f"  grep -q 'keeping configured engine' {shlex.quote(str(transcript))} 2>/dev/null && break\n"
        "  sleep 1\n"
        "done\n"
        "printf '\\003'\n",
        encoding="utf-8",
    )
    feeder.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    # conftest points XDG_CONFIG_HOME at an isolation dir; the installer reads
    # config.json from $XDG_CONFIG_HOME/vocalinux, not straight from $HOME.
    env["XDG_CONFIG_HOME"] = str(tmp_path / ".config")
    env["XDG_STATE_HOME"] = str(tmp_path / ".local" / "state")
    env["TMPDIR"] = str(tmp_path)

    inner = (
        f"cat {shlex.quote(str(INSTALL_SH))} | bash -s --"
        f" --tag=v0.0.0-test --venv-dir={shlex.quote(str(venv))}"
    )
    subprocess.run(
        f"{shlex.quote(str(feeder))} | {shlex.quote(str(SCRIPT))} -ec "
        + shlex.quote(f"bash -c {shlex.quote(inner)}")
        + f" {shlex.quote(str(transcript))}",
        shell=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=75,
        check=False,
        cwd=REPO_ROOT,
        env=env,
    )
    output = transcript.read_text(encoding="utf-8", errors="replace")
    assert "Existing configuration found at" in output
    assert "it will be kept" in output
    assert "Upgrade (keep current settings)" in output
    assert "keeping configured engine 'vosk'" in output

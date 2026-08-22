"""Behavioral tests for the installer's speech-engine sanity check.

config.json survives reinstalls, so it can name an engine the current venv
cannot import — vosk is an optional extra since #705. Vocalinux then dies at
startup with "No module named 'vosk'" instead of the installer saying so.
"""

import json
import subprocess
from pathlib import Path

INSTALL_SH = Path(__file__).resolve().parents[1] / "install.sh"

PRELUDE = """
set -uo pipefail

print_info() { echo "INFO: $*"; }
print_warning() { echo "WARNING: $*"; }
print_error() { echo "ERROR: $*"; }
print_success() { echo "SUCCESS: $*"; }
"""


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", PRELUDE + script], capture_output=True, text=True, timeout=30
    )


def _venv_python(venv_dir: Path, importable: "set[str] | None" = None) -> Path:
    """A stub venv interpreter: real python3, with chosen imports forced.

    ``importable`` names the engine modules that succeed; every other engine
    module fails. Anything else (the json probes) runs on the real interpreter.
    """
    modules = {"vosk", "whisper", "pywhispercpp.model"}
    ok = importable if importable is not None else set()
    python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)

    branches = "".join(
        'if [[ "$*" == *"import {module}"* ]]; then\n'
        "    exit {code}\n"
        "fi\n".format(module=module, code=0 if module in ok else 1)
        for module in sorted(modules, key=len, reverse=True)
    )
    python.write_text("#!/bin/bash\n" + branches + 'exec python3 "$@"\n')
    python.chmod(0o755)
    return python


def _engine_of(config_file: Path) -> str:
    return json.loads(config_file.read_text())["speech_recognition"]["engine"]


def _config(config_dir: Path, engine: str) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.json"
    path.write_text(json.dumps({"speech_recognition": {"engine": engine}}))
    return path


def _check(config_dir: Path, venv_dir: Path) -> subprocess.CompletedProcess:
    script = f"""
CONFIG_DIR="{config_dir}"
VENV_DIR="{venv_dir}"
for fn in engine_import_module engine_pip_name venv_can_import set_configured_engine verify_configured_engine; do
    source <(sed -n "/^$fn() {{$/,/^}}$/p" "{INSTALL_SH}")
done
verify_configured_engine
echo "EXIT=$?"
"""
    return _run(script)


def test_repairs_a_config_naming_an_uninstallable_engine(tmp_path):
    """Don't leave a config the app cannot start with."""
    venv = tmp_path / "venv"
    _venv_python(venv, importable={"pywhispercpp.model"})
    config = _config(tmp_path / "config", "vosk")

    result = _check(tmp_path / "config", venv)

    assert "EXIT=0" in result.stdout
    assert _engine_of(config) == "whisper_cpp"
    assert "Switched" in result.stdout


def test_repairs_a_leftover_whisper_engine_too(tmp_path):
    """The check was vosk-only; whisper is an optional extra as well."""
    venv = tmp_path / "venv"
    _venv_python(venv, importable={"pywhispercpp.model"})
    config = _config(tmp_path / "config", "whisper")

    result = _check(tmp_path / "config", venv)

    assert "EXIT=0" in result.stdout
    assert _engine_of(config) == "whisper_cpp"


def test_fails_when_no_engine_works(tmp_path):
    """Nothing to fall back to: the install must not report success."""
    venv = tmp_path / "venv"
    _venv_python(venv, importable=set())
    config = _config(tmp_path / "config", "vosk")

    result = _check(tmp_path / "config", venv)

    assert "EXIT=1" in result.stdout
    assert "cannot start" in result.stdout
    # The config is left alone so the user can see what it asked for.
    assert _engine_of(config) == "vosk"


def test_leaves_a_working_engine_alone(tmp_path):
    venv = tmp_path / "venv"
    _venv_python(venv, importable={"vosk"})
    config = _config(tmp_path / "config", "vosk")

    result = _check(tmp_path / "config", venv)

    assert "EXIT=0" in result.stdout
    assert _engine_of(config) == "vosk"
    assert "WARNING" not in result.stdout


def test_ignores_engines_that_need_no_extra(tmp_path):
    venv = tmp_path / "venv"
    _venv_python(venv, importable=set())
    config = _config(tmp_path / "config", "remote_api")

    result = _check(tmp_path / "config", venv)

    assert "EXIT=0" in result.stdout
    assert _engine_of(config) == "remote_api"


def test_silent_without_a_config_file(tmp_path):
    venv = tmp_path / "venv"
    _venv_python(venv, importable=set())

    result = _check(tmp_path / "config", venv)

    assert "EXIT=0" in result.stdout


def test_unreadable_config_is_not_treated_as_an_engine(tmp_path):
    venv = tmp_path / "venv"
    _venv_python(venv, importable=set())
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text("{not json")

    result = _check(config_dir, venv)

    assert "EXIT=0" in result.stdout

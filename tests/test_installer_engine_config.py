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


def _venv_python(venv_dir: Path, vosk_importable: bool) -> Path:
    """A stub venv interpreter: real python3, with `import vosk` forced."""
    python = venv_dir / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(
        "#!/bin/bash\n"
        'if [[ "$*" == *"import vosk"* ]]; then\n'
        f"    exit {0 if vosk_importable else 1}\n"
        "fi\n"
        'exec python3 "$@"\n'
    )
    python.chmod(0o755)
    return python


def _config(config_dir: Path, engine: str) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.json"
    path.write_text(json.dumps({"speech_recognition": {"engine": engine}}))
    return path


def _check(config_dir: Path, venv_dir: Path) -> subprocess.CompletedProcess:
    script = f"""
CONFIG_DIR="{config_dir}"
VENV_DIR="{venv_dir}"
source <(sed -n '/^verify_configured_engine() {{$/,/^}}$/p' "{INSTALL_SH}")
verify_configured_engine
echo "EXIT=$?"
"""
    return _run(script)


def test_warns_when_configured_vosk_is_missing(tmp_path):
    _config(tmp_path / "config", "vosk")
    _venv_python(tmp_path / "venv", vosk_importable=False)

    result = _check(tmp_path / "config", tmp_path / "venv")

    assert "not importable" in result.stdout
    assert "pip install vosk" in result.stdout
    assert "whisper_cpp" in result.stdout
    assert "EXIT=0" in result.stdout  # a warning, not a failed install


def test_silent_when_vosk_is_installed(tmp_path):
    _config(tmp_path / "config", "vosk")
    _venv_python(tmp_path / "venv", vosk_importable=True)

    result = _check(tmp_path / "config", tmp_path / "venv")

    assert "WARNING" not in result.stdout
    assert "EXIT=0" in result.stdout


def test_silent_for_other_engines(tmp_path):
    _config(tmp_path / "config", "whisper_cpp")
    _venv_python(tmp_path / "venv", vosk_importable=False)

    result = _check(tmp_path / "config", tmp_path / "venv")

    assert "WARNING" not in result.stdout


def test_silent_without_a_config_file(tmp_path):
    (tmp_path / "config").mkdir()
    _venv_python(tmp_path / "venv", vosk_importable=False)

    result = _check(tmp_path / "config", tmp_path / "venv")

    assert "WARNING" not in result.stdout
    assert "EXIT=0" in result.stdout


def test_unreadable_config_is_not_treated_as_vosk(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{not json")
    _venv_python(tmp_path / "venv", vosk_importable=False)

    result = _check(config_dir, tmp_path / "venv")

    assert "WARNING" not in result.stdout
    assert "EXIT=0" in result.stdout

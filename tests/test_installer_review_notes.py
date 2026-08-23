"""Source checks for leftover installer review notes from #700 and #705."""

import os
import subprocess
import sys
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
SETTINGS = Path(__file__).resolve().parents[1] / "src" / "vocalinux" / "ui" / "settings_dialog.py"
AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"


def _installer_source() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def test_help_places_transcript_under_installation() -> None:
    result = subprocess.run(
        ["bash", str(INSTALLER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "During installation a full transcript is saved to" in result.stdout
    assert "every run" not in result.stdout


def test_help_does_not_create_install_log_or_scratch_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()

    result = subprocess.run(
        ["bash", str(INSTALLER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert not list((tmp_path / "state").rglob("install-*.log"))
    assert not list((tmp_path / "tmp").glob("vocalinux-install.*"))


def test_scratch_dir_owns_pip_logs_and_model_temps() -> None:
    source = _installer_source()
    assert 'PIP_LOG_DIR="$VOCALINUX_TMP_DIR/pip"' in source
    assert 'export TMPDIR="$VOCALINUX_TMP_DIR"' in source
    assert 'TEMP_FILE="$VOCALINUX_TMP_DIR/tiny.pt"' in source
    assert 'TEMP_FILE="$VOCALINUX_TMP_DIR/ggml-tiny.bin"' in source
    assert 'TEMP_ZIP="$VOCALINUX_TMP_DIR/$(basename $SMALL_MODEL_URL)"' in source


def test_system_dep_and_venv_failures_use_structured_exit_codes() -> None:
    source = _installer_source()
    assert 'print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"' in source
    assert 'print_error "Failed to update package lists"; exit "$EXIT_NETWORK"' in source
    assert (
        'print_error "Failed to create virtual environment. Please check your Python installation."'
        in source
    )
    assert 'exit "$EXIT_MISSING_DEPS"' in source
    assert (
        'print_error "Failed to update pip, setuptools, and wheel"; exit "$EXIT_NETWORK"' in source
    )
    assert (
        'print_error "Failed to install Vocalinux package. Installation cannot continue."' in source
    )
    assert 'exit "$EXIT_NETWORK"' in source
    assert "Could not terminate all Vocalinux processes" in source
    assert 'exit "$EXIT_USER_ABORT"' in source


def test_release_tag_hint_is_not_hardcoded() -> None:
    source = _installer_source()
    assert "--tag=<release>" in source
    assert "--tag=v0.15.0" not in source


def test_whispercpp_fallback_installs_vosk_extra() -> None:
    source = _installer_source()
    assert 'pip_install_extras_skip_pygobject "$PIP_LOG_FILE" vosk' in source
    assert "pip install vosk --log" not in source
    assert 'pip install ".[vosk]"' not in source


def test_project_pip_install_skips_pygobject() -> None:
    source = _installer_source()
    assert "write_pip_reqs_skip_pygobject()" in source
    assert "pip_install_project_skip_pygobject()" in source
    assert "pip install --no-deps" in source
    assert "--no-emit-package pygobject" in source
    assert 'pip install . --log "$PIP_LOG_FILE"' not in source
    assert 'pip install -e . --log "$PIP_LOG_FILE"' not in source
    assert 'pip install ".[vad]"' not in source
    assert 'pip install -e ".[vad]"' not in source
    assert 'pip install -e ".[whisper,dev]"' not in source


def _run_reqs_writer(dest: Path, *extras: str) -> None:
    source = _installer_source()
    start = source.index("from pathlib import Path\nimport re\nimport sys\n")
    end = source.index("\nPY\n}", start)
    result = subprocess.run(
        [sys.executable, "-", str(dest), *extras],
        check=False,
        cwd=INSTALLER.parent,
        input=source[start:end],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_write_pip_reqs_skip_pygobject_runtime(tmp_path) -> None:
    dest = tmp_path / "runtime.txt"
    _run_reqs_writer(dest)
    reqs = dest.read_text().splitlines()
    assert reqs
    assert all("pygobject" not in req.lower() for req in reqs)
    assert any(req.startswith("pyaudio") for req in reqs)
    assert any(req.startswith("pywhispercpp") for req in reqs)


def test_write_pip_reqs_skip_pygobject_vosk_extra(tmp_path) -> None:
    dest = tmp_path / "vosk.txt"
    _run_reqs_writer(dest, "vosk")
    reqs = dest.read_text().splitlines()
    assert reqs == ["vosk>=0.3.45"]


def test_settings_uses_engine_flag_not_removed_with_whisper() -> None:
    text = SETTINGS.read_text(encoding="utf-8")
    assert "./install.sh --engine=whisper" in text
    assert "--with-whisper" not in text


def test_session_type_env_reads_use_default_expansion() -> None:
    source = _installer_source()
    start = source.index("install_text_input_tools()")
    end = source.index('print_info "Detected session type:', start)
    block = source[start:end]
    assert '[ -n "${XDG_SESSION_TYPE:-}" ]' in block
    assert '[ -n "${WAYLAND_DISPLAY:-}" ]' in block
    assert '[ -n "${DISPLAY:-}" ]' in block
    assert '"$XDG_SESSION_TYPE"' not in block
    assert '"$WAYLAND_DISPLAY"' not in block
    assert '"$DISPLAY"' not in block

    env = os.environ.copy()
    env.pop("XDG_SESSION_TYPE", None)
    env.pop("WAYLAND_DISPLAY", None)
    env["DISPLAY"] = ":1"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -u; [ -n "${XDG_SESSION_TYPE:-}" ] && echo xdg; '
            '[ -n "${DISPLAY:-}" ] && echo x11',
        ],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "x11"


def test_agents_does_not_claim_requirements_are_consumed() -> None:
    text = AGENTS.read_text(encoding="utf-8")
    assert "consumed by `install.sh`" not in text
    assert "`uv.lock` is authoritative" in text
    assert "Do not edit `requirements/*.txt` by hand" in text
    assert "https://just.systems" in text

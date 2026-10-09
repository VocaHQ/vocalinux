"""Regression guards for the curl|bash terminal-prompt path (issue #933).

`curl ... | bash` leaves bash reading the installer itself from stdin, so the
script must never redirect fd 0 away from the pipe: the old `exec < /dev/tty`
closed the pipe mid-download (curl error 23) and made bash read the rest of
the installer from the terminal as commands. Interactive prompts now pull
from /dev/tty per-read through `read_prompt`, and `TERMINAL_PROMPTS` records
whether a controlling terminal exists instead of testing `-t 0` on stdin.

The behavioral tests run the real install.sh under a pseudo-terminal exactly
the way a curl user runs it — script text on a pipe, /dev/tty on a terminal.
A saved file or a headless pipe exercises different branches and proves
nothing about this one.
"""

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install.sh"
MODULE_DIR = REPO_ROOT / "install.d"

#: A `read -p` (optionally `read_prompt -p`) anywhere in the installer tree.
PROMPT_LINE = re.compile(r"^\s*(read|read_prompt)\s+-p\s")

SCRIPT = shutil.which("script")
needs_pty = pytest.mark.skipif(
    SCRIPT is None,
    reason="script(1) is needed to give a piped installer a controlling terminal",
)


def _installer_sources() -> dict[Path, str]:
    sources = {INSTALLER: INSTALLER.read_text(encoding="utf-8")}
    for module in MODULE_DIR.glob("*.sh"):
        sources[module] = module.read_text(encoding="utf-8")
    return sources


def _pty_env(tmp_path: Path) -> dict:
    """Isolate the installer's log and scratch writes inside the test tmp dir."""
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["XDG_STATE_HOME"] = str(tmp_path / ".local" / "state")
    env["TMPDIR"] = str(tmp_path)
    return env


def test_stdin_is_never_redirected_off_the_pipe() -> None:
    """No fd-0 redirect may run while bash still reads the script from stdin."""
    for path, source in _installer_sources().items():
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert (
                "exec <" not in stripped
            ), f"{path.name}: `{stripped}` steals stdin from the piped script"
            assert "exec 0<" not in stripped


def test_every_interactive_read_uses_read_prompt() -> None:
    """All `read -p` sites go through read_prompt so answers come from /dev/tty."""
    source = INSTALLER.read_text(encoding="utf-8")
    helper = re.search(r"read_prompt\(\)\s*\{(.*?)\}", source, re.S)
    assert helper is not None, "install.sh does not define read_prompt"
    assert "< /dev/tty" in helper.group(1), "read_prompt does not read /dev/tty"

    for path, source in _installer_sources().items():
        bare = [line for line in source.splitlines() if PROMPT_LINE.match(line)]
        leftovers = [line.strip() for line in bare if "read_prompt" not in line]
        assert not leftovers, f"{path.name} prompts straight off stdin: {leftovers}"


def test_terminal_probe_selects_ask_or_auto() -> None:
    """A reachable /dev/tty asks for a mode; no terminal falls back to --auto."""
    source = INSTALLER.read_text(encoding="utf-8")
    assert "{ true < /dev/tty; } 2>/dev/null" in source
    assert 'INTERACTIVE_MODE="ask"' in source
    assert 'NON_INTERACTIVE="yes"' in source
    # Interactive mode is gated on a reachable terminal, not on a tty stdin:
    # under curl|bash stdin stays the pipe even while prompts work.
    assert '"$TERMINAL_PROMPTS" != "yes"' in source


@needs_pty
@pytest.mark.timeout(60)
def test_piped_installer_reaches_past_the_stdin_probe(tmp_path: Path) -> None:
    """`cat install.sh | bash -s -- --help` under a pty prints usage.

    On the broken version bash never got past the early stdin redirect: it
    read the rest of the script from the terminal instead of the pipe, so no
    installer output appeared at all.
    """
    transcript = tmp_path / "help.typescript"
    inner = f"cat {shlex.quote(str(INSTALLER))} | bash -s -- --help"
    subprocess.run(
        [SCRIPT, "-ec", f"bash -c {shlex.quote(inner)}", str(transcript)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=45,
        check=False,
    )
    output = transcript.read_text(encoding="utf-8", errors="replace")
    assert "Vocalinux Installer" in output
    assert "Usage:" in output


@needs_pty
@pytest.mark.timeout(90)
def test_piped_installer_prompts_answer_on_the_terminal(tmp_path: Path) -> None:
    """Prompts read /dev/tty while bash keeps reading the script from the pipe.

    Feed "1" (interactive) early — pty input queues until the mode prompt
    reads it — then Ctrl+C once the engine menu is up. Reaching "Choose
    engine" proves the tty answer was accepted while the script still flowed
    through the pipe.
    """
    transcript = tmp_path / "interactive.typescript"
    feeder = tmp_path / "feed-input.sh"
    feeder.write_text(
        "#!/bin/sh\n"
        # Queued until the "Choose mode" prompt reads /dev/tty.
        "sleep 1; printf '1\\n'\n"
        # Interrupt once the engine menu is on screen; late on purpose — a
        # slow runner must not see Ctrl+C before the second prompt appears.
        "sleep 12; printf '\\003'\n",
        encoding="utf-8",
    )
    feeder.chmod(0o755)
    subprocess.run(
        f"{shlex.quote(str(feeder))} | {shlex.quote(str(SCRIPT))} -ec "
        + shlex.quote(f"cat {INSTALLER} | bash")
        + f" {shlex.quote(str(transcript))}",
        shell=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=75,
        check=False,
        cwd=REPO_ROOT,
        env=_pty_env(tmp_path),
    )
    output = transcript.read_text(encoding="utf-8", errors="replace")
    assert "Choose mode" in output
    assert "Choose engine" in output

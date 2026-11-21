"""Post-processing of transcribed text via an external executable."""

import logging
import os
import signal
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Optional

from .ui.config_manager import (
    DEFAULT_POST_PROCESSING_TIMEOUT_SECONDS,
    clamp_post_processing_timeout,
)
from .utils.host_process import host_env

if TYPE_CHECKING:
    from .ui.config_manager import ConfigManager

logger = logging.getLogger(__name__)

_active_processes_lock = threading.Lock()
_active_processes: set[subprocess.Popen[str]] = set()


def _process_group_alive(proc: subprocess.Popen[str]) -> bool:
    """Return True if any process in ``proc``'s process group is still alive."""
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0 and hasattr(os, "killpg"):
        try:
            os.killpg(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
    return False


def _close_pipes(proc: subprocess.Popen[str]) -> None:
    """Close stdio pipes on a subprocess defensively so reads never hang."""
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def _signal_process_group(proc: subprocess.Popen[str], sig: int) -> bool:
    """Send ``sig`` to ``proc``'s process group when available; return True if handled."""
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0 and hasattr(os, "killpg"):
        try:
            os.killpg(pid, sig)
            return True
        except ProcessLookupError:
            return True
        except OSError:
            return False
    return False


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    """Politely terminate a post-processor process group (falling back to the process)."""
    if _signal_process_group(proc, signal.SIGTERM):
        return
    try:
        proc.terminate()
    except OSError:
        pass


def _kill_process(proc: subprocess.Popen[str]) -> None:
    """Force-kill a post-processor process group (falling back to the process)."""
    if _signal_process_group(proc, signal.SIGKILL):
        return
    try:
        proc.kill()
    except OSError:
        pass


def abort_active_post_processors(grace_seconds: float = 0.5) -> None:
    """Stop any running post-processing scripts and child helpers on quit."""
    with _active_processes_lock:
        procs = list(_active_processes)
    if not procs:
        return

    for proc in procs:
        _terminate_process(proc)

    deadline = time.monotonic() + max(0.0, grace_seconds)
    for proc in procs:
        remaining = max(0.0, deadline - time.monotonic())
        still_running = False
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            still_running = True
        except OSError:
            pass

        # A parent shell may exit on SIGTERM while a child helper stays alive
        # in the same process group holding stdout/stderr pipes open. Wait up
        # to the shared deadline for the group to drain, then SIGKILL survivors.
        while not still_running and _process_group_alive(proc):
            if time.monotonic() >= deadline:
                still_running = True
                break
            time.sleep(0.02)

        if still_running or _process_group_alive(proc):
            _kill_process(proc)
            try:
                proc.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, OSError):
                pass


class PostProcessor:
    """Pipes transcribed text through a user-defined executable and returns the output."""

    def __init__(
        self,
        script_path: str,
        timeout: float = DEFAULT_POST_PROCESSING_TIMEOUT_SECONDS,
    ) -> None:
        self.script_path = script_path
        self.timeout = clamp_post_processing_timeout(timeout)

    def process(self, text: str, *, cancel_event: Optional[threading.Event] = None) -> str:
        """Run the script with text on stdin; return stdout. Falls back to original on failure."""
        if cancel_event is not None and cancel_event.is_set():
            logger.debug("Skipping post-processor %s: shutdown in progress", self.script_path)
            return text

        logger.info("Running post-processor: %s", self.script_path)
        try:
            proc = subprocess.Popen(
                [self.script_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=host_env(),
            )
        except (OSError, subprocess.SubprocessError, UnicodeError) as e:
            logger.warning("Post-processor failed: %s", e)
            return text

        with _active_processes_lock:
            _active_processes.add(proc)
        try:
            if cancel_event is not None and cancel_event.is_set():
                _terminate_process(proc)
                try:
                    proc.communicate(timeout=0.5)
                except subprocess.TimeoutExpired:
                    _kill_process(proc)
                    try:
                        proc.communicate(timeout=0.5)
                    except (
                        subprocess.TimeoutExpired,
                        OSError,
                        subprocess.SubprocessError,
                        UnicodeError,
                    ):
                        _close_pipes(proc)
                except (OSError, subprocess.SubprocessError, UnicodeError):
                    _close_pipes(proc)
                logger.debug("Post-processor aborted on shutdown: %s", self.script_path)
                return text

            try:
                stdout, stderr = proc.communicate(input=text, timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                _kill_process(proc)
                try:
                    proc.communicate(timeout=0.5)
                except (
                    subprocess.TimeoutExpired,
                    OSError,
                    subprocess.SubprocessError,
                    UnicodeError,
                ):
                    _close_pipes(proc)
                logger.warning("Post-processor failed: %s", e)
                return text
            except (OSError, subprocess.SubprocessError, UnicodeError) as e:
                if cancel_event is not None and cancel_event.is_set():
                    logger.debug("Post-processor aborted on shutdown: %s", self.script_path)
                else:
                    logger.warning("Post-processor failed: %s", e)
                return text
        finally:
            with _active_processes_lock:
                _active_processes.discard(proc)

        if cancel_event is not None and cancel_event.is_set():
            logger.debug("Post-processor aborted on shutdown: %s", self.script_path)
            return text

        if proc.returncode != 0:
            logger.warning("Post-processor exited %d: %s", proc.returncode, stderr.strip())
            return text

        # Success is logged without the output text: transformed dictation can
        # be sensitive, and logs are retained and exportable.
        logger.debug("Post-processor succeeded, %d bytes out", len(stdout))
        return self._strip_convenience_newline(text, stdout)

    @staticmethod
    def _strip_convenience_newline(original: str, transformed: str) -> str:
        """Drop one trailing newline a script may add, keeping meaningful ones.

        Line-oriented tools (``echo``, ``print``) terminate their output with a
        newline the input never had; injecting it would press Return after
        every segment. Newlines beyond that — like the ``\\n\\n`` a "new
        paragraph" voice command leaves — are part of the text and stay.
        """
        if transformed.endswith("\n") and not original.endswith("\n"):
            return transformed[:-1]
        return transformed


def apply_post_processing(
    text: str,
    config_manager: "ConfigManager",
    *,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[str]:
    """Apply post-processing script to text if configured.

    Returns processed text, or None to signal the caller should skip injection.
    Returns original text unchanged when no script is configured.
    """
    script_path = config_manager.get_str("post_processing", "script_path", "")
    if not script_path:
        return text
    timeout = clamp_post_processing_timeout(
        config_manager.get(
            "post_processing",
            "timeout_seconds",
            DEFAULT_POST_PROCESSING_TIMEOUT_SECONDS,
        )
    )
    result = PostProcessor(script_path, timeout=timeout).process(text, cancel_event=cancel_event)
    return result if result else None

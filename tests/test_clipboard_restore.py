"""Tests for _read_clipboard() and clipboard restore in _inject_via_clipboard_paste.

Covers the behaviour introduced in PR #588: before injecting text via the
ydotool clipboard-paste path, the existing clipboard content is saved and
restored ~300 ms after the Ctrl+V keystroke is sent.
"""

import os
import subprocess
import threading
import time
import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch


def _make_injector() -> Any:
    from vocalinux.text_injection.text_injector import DesktopEnvironment, TextInjector

    obj = cast(Any, TextInjector.__new__(TextInjector))
    obj._ibus_injector = None
    obj.environment = DesktopEnvironment.WAYLAND
    obj._session_environment = DesktopEnvironment.WAYLAND
    obj._ibus_ready = False
    obj._ibus_init_failed = False
    obj._ibus_init_thread = None
    obj._state_lock = threading.Lock()
    obj._clipboard_tool_health = {}
    obj._clipboard_timeout = 0.35
    obj._clipboard_restore_generation = 0
    obj._clipboard_restore_target = None
    return obj


class TestReadClipboard(unittest.TestCase):
    """Unit tests for the _read_clipboard() helper.

    subprocess.run is called with text=True so stdout is always a str.
    """

    def test_wl_paste_used_first_on_wayland(self):
        """On Wayland, wl-paste is the first candidate and its output is returned."""
        obj = _make_injector()
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: (
                    "/usr/bin/wl-paste" if cmd == "wl-paste" else None
                )
                with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="copied text")
                    result = obj._read_clipboard()
        self.assertEqual(result, "copied text")
        mock_run.assert_called_once()
        self.assertEqual(
            mock_run.call_args.args[0],
            ["wl-paste", "--no-newline", "--type", "text"],
        )

    def test_xclip_requests_utf8_string_target(self):
        """xclip must request UTF8_STRING so image clipboards are not read as text."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: ("/usr/bin/xclip" if cmd == "xclip" else None)
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="xclip text")
                result = obj._read_clipboard()
        self.assertEqual(result, "xclip text")
        self.assertEqual(
            mock_run.call_args.args[0],
            ["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"],
        )

    def test_xclip_fallback_when_wl_paste_unavailable(self):
        """Falls back to xclip when wl-paste is not installed."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: ("/usr/bin/xclip" if cmd == "xclip" else None)
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="xclip text")
                result = obj._read_clipboard()
        self.assertEqual(result, "xclip text")

    def test_xsel_fallback_when_wl_paste_and_xclip_unavailable(self):
        """Falls back to xsel when wl-paste and xclip are both not installed."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: ("/usr/bin/xsel" if cmd == "xsel" else None)
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="xsel text")
                result = obj._read_clipboard()
        self.assertEqual(result, "xsel text")

    def test_returns_none_when_no_tool_installed(self):
        """Returns None when no clipboard read tool is available."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which", return_value=None):
            result = obj._read_clipboard()
        self.assertIsNone(result)

    def test_returns_none_when_tool_exits_nonzero_with_unknown_stderr(self):
        """Returns None when exit code is non-zero and stderr has no recognised empty-clipboard message."""
        obj = _make_injector()
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                return_value="/usr/bin/wl-paste",
            ):
                with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")
                    result = obj._read_clipboard()
        self.assertIsNone(result)

    def test_returns_none_and_does_not_raise_on_timeout(self):
        """Returns None without raising when the clipboard tool times out."""
        obj = _make_injector()
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                return_value="/usr/bin/wl-paste",
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("wl-paste", 1.0),
                ):
                    result = obj._read_clipboard()
        self.assertIsNone(result)

    def test_returns_none_and_does_not_raise_on_oserror(self):
        """Returns None without raising when subprocess raises OSError."""
        obj = _make_injector()
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                return_value="/usr/bin/wl-paste",
            ):
                with patch(
                    "vocalinux.text_injection.text_injector.subprocess.run",
                    side_effect=OSError("not found"),
                ):
                    result = obj._read_clipboard()
        self.assertIsNone(result)

    def test_tries_next_tool_after_failure(self):
        """When the first tool fails, the next candidate is tried."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: (
                "/usr/bin/" + cmd if cmd in ("wl-paste", "xclip") else None
            )
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=1, stdout=""),  # wl-paste fails
                    MagicMock(returncode=0, stdout="via xclip"),  # xclip succeeds
                ]
                result = obj._read_clipboard()
        self.assertEqual(result, "via xclip")

    def test_returns_arabic_text(self):
        """Correctly returns multi-byte UTF-8 content such as Arabic text."""
        obj = _make_injector()
        arabic = "مرحبا بالعالم"
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                return_value="/usr/bin/wl-paste",
            ):
                with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout=arabic)
                    result = obj._read_clipboard()
        self.assertEqual(result, arabic)

    def test_wl_paste_used_as_fallback_on_x11(self):
        """On X11, wl-paste is added as a last-resort candidate (XWayland environments)."""
        from vocalinux.text_injection.text_injector import DesktopEnvironment

        obj = _make_injector()
        obj._session_environment = DesktopEnvironment.X11
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
            with patch(
                "vocalinux.text_injection.text_injector.shutil.which",
                return_value="/usr/bin/wl-paste",
            ):
                with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="x11 clipboard")
                    result = obj._read_clipboard()
        self.assertEqual(result, "x11 clipboard")


class TestClipboardRestoreAfterInjection(unittest.TestCase):
    """Behavioural tests for the save/restore logic in _inject_via_clipboard_paste."""

    def test_clipboard_restored_to_previous_content(self):
        """Previous clipboard content is written back ~300ms after injection."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        # First read: saves previous content. Second read (inside _restore): clipboard
        # still holds injected text, confirming the user hasn't copied anything else.
        with patch.object(
            obj, "_read_clipboard", side_effect=["original clipboard", "injected text"]
        ):
            with patch.object(
                obj, "_copy_to_clipboard", side_effect=lambda t, **kw: copy_calls.append(t) or True
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("injected text")
                            time.sleep(0.5)  # wait for the 300ms restore thread

        self.assertTrue(result)
        self.assertEqual(copy_calls[0], "injected text")
        self.assertEqual(copy_calls[-1], "original clipboard")

    def test_read_clipboard_is_called_before_overwriting(self):
        """_read_clipboard must be called first, before _copy_to_clipboard."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        call_order: list[str] = []

        with patch.object(
            obj,
            "_read_clipboard",
            side_effect=lambda: call_order.append("read") or "prev",
        ):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: call_order.append(f"copy:{t}") or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            obj._inject_via_clipboard_paste("text")
                            time.sleep(0.5)

        self.assertEqual(call_order[0], "read", "read must happen before any copy")
        self.assertIn("copy:text", call_order)

    def test_no_restore_when_clipboard_was_empty(self):
        """No restore is attempted when _read_clipboard() returns None (clipboard empty)."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        with patch.object(obj, "_read_clipboard", return_value=None):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("text")
                            time.sleep(0.5)

        self.assertTrue(result)
        # Only one call: the injection. No second call for restore.
        self.assertEqual(copy_calls, ["text"])

    def test_no_restore_when_copy_to_clipboard_setting_enabled(self):
        """No restore when the user has opted-in to keeping dictated text in clipboard.

        When copy_to_clipboard=true, the user explicitly wants the dictated text
        to stay in the clipboard after injection. Restoring the old content would
        silently undo that preference.
        """
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        with patch.object(obj, "_read_clipboard", return_value="old clipboard"):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=True):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("dictated text")
                            time.sleep(0.5)

        self.assertTrue(result)
        # Only one copy call — the injection. The old content must NOT be restored.
        self.assertEqual(copy_calls, ["dictated text"])

    def test_clipboard_restored_when_ctrl_v_fails(self):
        """Clipboard is restored immediately when Ctrl+V fails, not silently lost."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        with patch.object(obj, "_read_clipboard", return_value="prev"):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            side_effect=subprocess.CalledProcessError(1, ["ydotool", "key"]),
                        ):
                            result = obj._inject_via_clipboard_paste("text")
                            time.sleep(0.5)

        self.assertFalse(result)
        # First copy: injection; second copy: immediate restore after paste failure
        self.assertEqual(copy_calls, ["text", "prev"])

    def test_restore_thread_is_a_daemon(self):
        """The restore thread is a daemon so it never blocks interpreter shutdown."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        started: list[threading.Thread] = []
        original_start = threading.Thread.start

        def capture_start(self_t: threading.Thread) -> None:
            started.append(self_t)
            original_start(self_t)

        with patch.object(obj, "_read_clipboard", return_value="prev"):
            with patch.object(obj, "_copy_to_clipboard", return_value=True):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            with patch.object(threading.Thread, "start", capture_start):
                                obj._inject_via_clipboard_paste("text")

        self.assertEqual(len(started), 1, "exactly one restore thread should start")
        self.assertTrue(started[0].daemon, "restore thread must be a daemon")

    def test_arabic_content_is_preserved(self):
        """Clipboard content containing Arabic text is correctly restored."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []
        arabic_previous = "نص عربي سابق"

        with patch.object(obj, "_read_clipboard", side_effect=[arabic_previous, "مرحبا"]):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            obj._inject_via_clipboard_paste("مرحبا")
                            time.sleep(0.5)

        self.assertEqual(copy_calls[-1], arabic_previous)

    def test_restore_failure_is_handled_gracefully(self):
        """No exception when _copy_to_clipboard returns False during restore."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        def fake_copy(t: str, **kwargs) -> bool:
            copy_calls.append(t)
            # injection copy succeeds; restore copy fails
            return t != "previous_content"

        with patch.object(
            obj, "_read_clipboard", side_effect=["previous_content", "injected text"]
        ):
            with patch.object(obj, "_copy_to_clipboard", side_effect=fake_copy):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("injected text")
                            time.sleep(0.5)

        self.assertTrue(result)
        # The restore attempt was made but failed — no exception raised
        self.assertIn("previous_content", copy_calls)

    def test_clipboard_restored_immediately_when_paste_fails(self):
        """Original clipboard is restored right away when Ctrl+V fails, not after 300ms."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        with patch.object(obj, "_read_clipboard", return_value="original content"):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            side_effect=subprocess.CalledProcessError(1, ["ydotool", "key"]),
                        ):
                            result = obj._inject_via_clipboard_paste("injected text")

        self.assertFalse(result)
        # First copy: injected text; second copy: immediate restore after failure
        self.assertEqual(copy_calls, ["injected text", "original content"])

    def test_no_restore_when_paste_fails_and_clipboard_was_unreadable(self):
        """No restore attempted when Ctrl+V fails and clipboard could not be read."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        with patch.object(obj, "_read_clipboard", return_value=None):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            side_effect=subprocess.CalledProcessError(1, ["ydotool", "key"]),
                        ):
                            result = obj._inject_via_clipboard_paste("text")

        self.assertFalse(result)
        # Only injection copy — no restore since clipboard was unreadable
        self.assertEqual(copy_calls, ["text"])

    def test_empty_clipboard_is_cleared_after_injection(self):
        """When clipboard was empty, _clear_clipboard() is called instead of copy("")."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        clear_called: list[bool] = []

        with patch.object(obj, "_read_clipboard", side_effect=["", "new text"]):
            with patch.object(obj, "_copy_to_clipboard", return_value=True):
                with patch.object(
                    obj, "_clear_clipboard", side_effect=lambda: clear_called.append(True) or True
                ):
                    with patch.object(
                        obj,
                        "_ydotool_ctrl_v_command",
                        return_value=["ydotool", "key", "ctrl+v"],
                    ):
                        with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                            with patch(
                                "vocalinux.text_injection.text_injector.subprocess.run",
                                return_value=MagicMock(returncode=0),
                            ):
                                result = obj._inject_via_clipboard_paste("new text")
                                time.sleep(0.5)

        self.assertTrue(result)
        self.assertTrue(
            clear_called, "_clear_clipboard() must be called for empty previous content"
        )

    def test_restore_skipped_when_clipboard_changed_during_delay(self):
        """Restore is skipped if the user copied something else during the 300ms window."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        # First read: previous content. Second read (inside _restore): user copied "new thing"
        with patch.object(obj, "_read_clipboard", side_effect=["original", "new thing"]):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("injected text")
                            time.sleep(0.5)

        self.assertTrue(result)
        # Only the injection copy — restore was skipped because clipboard changed
        self.assertEqual(copy_calls, ["injected text"])

    def test_restore_proceeds_when_clipboard_unchanged(self):
        """Restore fires when clipboard still holds the injected text after 300ms."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []

        # First read: previous content. Second read (inside _restore): still the injected text
        with patch.object(obj, "_read_clipboard", side_effect=["original", "injected text"]):
            with patch.object(
                obj,
                "_copy_to_clipboard",
                side_effect=lambda t, **kw: copy_calls.append(t) or True,
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            result = obj._inject_via_clipboard_paste("injected text")
                            time.sleep(0.5)

        self.assertTrue(result)
        self.assertEqual(copy_calls, ["injected text", "original"])


class TestClearClipboard(unittest.TestCase):
    """Unit tests for the _clear_clipboard() helper."""

    def test_wl_copy_clear_flag_used(self):
        """Uses 'wl-copy --clear' on Wayland."""
        obj = _make_injector()
        with patch(
            "vocalinux.text_injection.text_injector.shutil.which", return_value="/usr/bin/wl-copy"
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = obj._clear_clipboard()
        self.assertTrue(result)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["wl-copy", "--clear"])

    def test_xsel_clear_flag_used(self):
        """Uses 'xsel --clipboard --clear' when xsel is available."""
        obj = _make_injector()
        obj._session_environment = None
        with patch(
            "vocalinux.text_injection.text_injector.shutil.which",
            side_effect=lambda cmd: "/usr/bin/xsel" if cmd == "xsel" else None,
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
                    result = obj._clear_clipboard()
        self.assertTrue(result)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd, ["xsel", "--clipboard", "--clear"])

    def test_xclip_empty_input_used(self):
        """Uses xclip with empty input when xclip is the only available tool."""
        obj = _make_injector()
        obj._session_environment = None
        with patch(
            "vocalinux.text_injection.text_injector.shutil.which",
            side_effect=lambda cmd: "/usr/bin/xclip" if cmd == "xclip" else None,
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
                    result = obj._clear_clipboard()
        self.assertTrue(result)
        call_kwargs = mock_run.call_args
        self.assertEqual(call_kwargs[0][0], ["xclip", "-selection", "clipboard"])

    def test_skips_unhealthy_tool_and_tries_next(self):
        """Skips a tool marked unhealthy; returns False when it was the only tool."""
        obj = _make_injector()
        obj._clipboard_tool_health["wl-copy"] = False
        with patch(
            "vocalinux.text_injection.text_injector.shutil.which",
            side_effect=lambda cmd: "/usr/bin/wl-copy" if cmd == "wl-copy" else None,
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                result = obj._clear_clipboard()
        self.assertFalse(result)
        mock_run.assert_not_called()

    def test_exception_falls_through_to_next_tool(self):
        """When one tool throws, the next candidate is tried."""
        obj = _make_injector()
        obj._session_environment = None
        with patch(
            "vocalinux.text_injection.text_injector.shutil.which",
            side_effect=lambda cmd: "/usr/bin/" + cmd if cmd in ("xclip", "xsel") else None,
        ):
            with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                mock_run.side_effect = [
                    subprocess.CalledProcessError(1, ["xclip"]),  # xclip fails
                    MagicMock(returncode=0),  # xsel succeeds
                ]
                with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
                    result = obj._clear_clipboard()
        self.assertTrue(result)

    def test_clear_called_when_paste_fails_and_clipboard_was_empty(self):
        """_clear_clipboard() is called immediately when paste fails and clipboard was empty."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        clear_called: list[bool] = []

        with patch.object(obj, "_read_clipboard", return_value=""):
            with patch.object(obj, "_copy_to_clipboard", return_value=True):
                with patch.object(
                    obj, "_clear_clipboard", side_effect=lambda: clear_called.append(True) or True
                ):
                    with patch.object(
                        obj,
                        "_ydotool_ctrl_v_command",
                        return_value=["ydotool", "key", "ctrl+v"],
                    ):
                        with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                            with patch(
                                "vocalinux.text_injection.text_injector.subprocess.run",
                                side_effect=subprocess.CalledProcessError(1, ["ydotool", "key"]),
                            ):
                                result = obj._inject_via_clipboard_paste("text")

        self.assertFalse(result)
        self.assertTrue(
            clear_called,
            "_clear_clipboard() must be called when paste fails with empty previous clipboard",
        )

    def test_returns_false_when_no_tool_available(self):
        """Returns False when no clipboard tool is installed."""
        obj = _make_injector()
        with patch("vocalinux.text_injection.text_injector.shutil.which", return_value=None):
            result = obj._clear_clipboard()
        self.assertFalse(result)


class TestReadClipboardEmptyDetection(unittest.TestCase):
    """Tests for _read_clipboard() detecting empty clipboard via stderr patterns."""

    def test_wl_paste_nothing_is_copied_returns_empty_string(self):
        """Returns '' when wl-paste stderr says 'Nothing is copied'."""
        obj = _make_injector()
        with patch("shutil.which", return_value="/usr/bin/wl-paste"):
            with patch(
                "vocalinux.text_injection.text_injector.subprocess.run",
                return_value=MagicMock(returncode=1, stdout="", stderr="Nothing is copied"),
            ):
                result = obj._read_clipboard()
        self.assertEqual(result, "")

    def test_xclip_target_not_available_returns_none(self):
        """xclip 'target not available' means no text — not an empty clipboard.

        Image/file clipboards produce this message for UTF8_STRING. Returning
        '' would cause a clear that destroys non-text data; skip restore instead.
        """
        obj = _make_injector()
        obj._session_environment = None  # non-Wayland so xclip is tried
        with patch(
            "shutil.which", side_effect=lambda cmd: "/usr/bin/xclip" if cmd == "xclip" else None
        ):
            with patch(
                "vocalinux.text_injection.text_injector.subprocess.run",
                return_value=MagicMock(
                    returncode=1, stdout="", stderr="Error: target UTF8_STRING not available"
                ),
            ):
                with patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": ""}):
                    result = obj._read_clipboard()
        self.assertIsNone(result)

    def test_wl_paste_empty_falls_through_to_xclip_text(self):
        """Empty Wayland clipboard must not skip an X11 backend that still has text."""
        obj = _make_injector()
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with patch("vocalinux.text_injection.text_injector.shutil.which") as mock_which:
                mock_which.side_effect = lambda cmd: (
                    "/usr/bin/" + cmd if cmd in ("wl-paste", "xclip") else None
                )
                with patch("vocalinux.text_injection.text_injector.subprocess.run") as mock_run:
                    mock_run.side_effect = [
                        MagicMock(returncode=1, stdout="", stderr="Nothing is copied"),
                        MagicMock(returncode=0, stdout="x11 text"),
                    ]
                    result = obj._read_clipboard()
        self.assertEqual(result, "x11 text")

    def test_non_empty_clipboard_error_still_returns_none(self):
        """A non-zero exit code with unknown stderr does not trigger empty detection."""
        obj = _make_injector()
        with patch("shutil.which", return_value=None):
            result = obj._read_clipboard()
        self.assertIsNone(result)


class TestOverlappingClipboardRestore(unittest.TestCase):
    """Overlapping pastes must restore the original pre-first-injection content."""

    def test_overlapping_pastes_restore_original_clipboard(self):
        """Second paste within the restore window must not restore intermediate text."""
        obj = _make_injector()
        obj.wayland_tool = "ydotool"
        copy_calls: list[str] = []
        # First paste saves "URL". Second paste would naively save "hello" (still on
        # clipboard); pending-target must keep restoring to "URL".
        read_values = iter(["URL", "world"])

        with patch.object(obj, "_read_clipboard", side_effect=lambda: next(read_values)):
            with patch.object(
                obj, "_copy_to_clipboard", side_effect=lambda t, **kw: copy_calls.append(t) or True
            ):
                with patch.object(
                    obj,
                    "_ydotool_ctrl_v_command",
                    return_value=["ydotool", "key", "ctrl+v"],
                ):
                    with patch.object(obj, "_should_copy_to_clipboard", return_value=False):
                        with patch(
                            "vocalinux.text_injection.text_injector.subprocess.run",
                            return_value=MagicMock(returncode=0),
                        ):
                            self.assertTrue(obj._inject_via_clipboard_paste("hello"))
                            self.assertTrue(obj._inject_via_clipboard_paste("world"))
                            time.sleep(0.5)

        self.assertEqual(copy_calls[0], "hello")
        self.assertEqual(copy_calls[1], "world")
        self.assertEqual(copy_calls[-1], "URL")
        self.assertNotIn("hello", copy_calls[2:])
        self.assertIsNone(obj._clipboard_restore_target)


if __name__ == "__main__":
    unittest.main()

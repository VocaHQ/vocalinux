"""
Regression tests for #984: standalone windows must not carry the DIALOG
type hint.

On GTK's Wayland backend, a toplevel with the DIALOG hint and no transient
parent becomes an "orphan dialog": the next toplevel in the app to receive
keyboard focus silently becomes its xdg_toplevel parent. GNOME then treats
the pair as one window for minimize/restore, raising, and workspace moves.

The dictation pad is a plain Gtk.Window (NORMAL hint) that is focused
constantly, so any standalone Gtk.Dialog left parentless gets bound to it.
Settings, the transcript viewer, and the log viewer are standalone windows
and must opt out with the NORMAL hint.
"""

import os
import unittest


def _read_source(filename: str) -> str:
    """Read a UI module's source code."""
    source_path = os.path.join(os.path.dirname(__file__), "..", "src", "vocalinux", "ui", filename)
    with open(source_path, "r") as f:
        return f.read()


class TestStandaloneDialogsUseNormalHint(unittest.TestCase):
    """Parentless standalone dialogs must not stay DIALOG-hinted (#984)."""

    def _assert_normal_hint(self, filename: str, class_name: str) -> None:
        source = _read_source(filename)
        class_start = source.index(f"class {class_name}(")
        init_start = source.index("def __init__", class_start)
        # The hint must be reset inside __init__ before the window is shown.
        init_end = source.index("\n    def ", init_start + 1)
        init_source = source[init_start:init_end]
        self.assertIn(
            "set_type_hint(Gdk.WindowTypeHint.NORMAL)",
            init_source,
            f"{class_name} must opt out of the DIALOG type hint so GTK's "
            "Wayland backend never adopts it as an orphan dialog (#984)",
        )

    def test_settings_dialog_uses_normal_hint(self) -> None:
        self._assert_normal_hint("settings_dialog.py", "SettingsDialog")

    def test_transcript_dialog_uses_normal_hint(self) -> None:
        self._assert_normal_hint("transcript_dialog.py", "TranscriptDialog")

    def test_logging_dialog_uses_normal_hint(self) -> None:
        self._assert_normal_hint("logging_dialog.py", "LoggingDialog")

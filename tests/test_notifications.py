"""Tests for vocalinux.ui.notifications against a fake libnotify.

Every other test patches the whole ``notifications`` module away, so the
libnotify/notify-send boundary itself was never exercised. These drive the
module directly: ``conftest`` already installs ``gi.repository`` as a
MagicMock, so the fake ``Notify`` is steered through that.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def notifications():
    """The real module with its lazy state reset, restored afterwards."""
    from vocalinux.ui import notifications as module

    saved = (module._notify_module, module._notify_initialized, set(module._pending))
    module._notify_module = None
    module._notify_initialized = False
    module._pending.clear()
    yield module
    module._notify_module, module._notify_initialized = saved[0], saved[1]
    module._pending.clear()
    module._pending.update(saved[2])


@pytest.fixture
def fake_notify(notifications):
    """A libnotify that advertises action buttons, handed to the module directly.

    Installed through the module's own lazy cache rather than by patching
    ``gi.repository.Notify``: that global is shared with every other test in
    the process, and background threads left behind by earlier tests (the
    single-instance checks in test_main, for one) keep calling into it. A fake
    that only this module can reach is immune to them.
    """
    notify = MagicMock()
    notify.get_server_caps.return_value = ["body", "actions"]
    notifications._notify_module = notify
    notifications._notify_initialized = True
    return notify


@pytest.fixture
def notify_send(notifications):
    with patch.object(notifications.subprocess, "Popen") as popen:
        yield popen


def _registered_callback(notification, signal_name):
    """The callback the module connected to ``signal_name`` on the fake."""
    for call in notification.connect.call_args_list:
        if call.args[0] == signal_name:
            return call.args[1]
    raise AssertionError(f"nothing connected to {signal_name!r}")


class TestFallbackToNotifySend:
    def test_action_without_server_support_falls_back_to_notify_send(
        self, notifications, fake_notify, notify_send
    ):
        fake_notify.get_server_caps.return_value = ["body"]

        handle = notifications.notify(
            "Title", "Body", "dialog-warning", action=("Go", lambda: None)
        )

        assert handle is None
        notify_send.assert_called_once()
        argv = notify_send.call_args.args[0]
        assert argv[0] == "notify-send"
        assert argv[-2:] == ["Title", "Body"]

    def test_failed_libnotify_init_falls_back(self, notifications, notify_send):
        broken = MagicMock()
        broken.is_initted.return_value = False
        broken.init.return_value = False
        with patch.object(sys.modules["gi.repository"], "Notify", broken):
            handle = notifications.notify("Title", "Body")

        assert handle is None
        assert notifications._notify_module is None
        notify_send.assert_called_once()

    def test_plain_notification_needs_no_action_support(
        self, notifications, fake_notify, notify_send
    ):
        fake_notify.get_server_caps.return_value = ["body"]

        handle = notifications.notify("Title", "Body")

        assert handle is fake_notify.Notification.new.return_value
        notify_send.assert_not_called()


class TestPendingHandles:
    def test_action_keeps_the_notification_alive_until_answered(self, notifications, fake_notify):
        handle = notifications.notify("Title", "Body", action=("Go", lambda: None))

        assert handle in notifications._pending

        _registered_callback(handle, "closed")(handle)

        assert handle not in notifications._pending

    def test_action_callback_runs_and_releases_the_handle(self, notifications, fake_notify):
        callback = MagicMock()
        handle = notifications.notify("Title", "Body", action=("Go", callback))
        on_action = handle.add_action.call_args.args[2]

        on_action(handle, "default-action", None)

        callback.assert_called_once_with()
        assert handle not in notifications._pending

    def test_a_failing_action_callback_is_logged_not_raised(self, notifications, fake_notify):
        handle = notifications.notify(
            "Title", "Body", action=("Go", MagicMock(side_effect=RuntimeError("boom")))
        )
        on_action = handle.add_action.call_args.args[2]

        on_action(handle, "default-action", None)  # must not raise

        assert handle not in notifications._pending

    def test_close_releases_the_handle(self, notifications, fake_notify):
        handle = notifications.notify("Title", "Body", action=("Go", lambda: None))

        notifications.close(handle)

        assert handle not in notifications._pending
        handle.close.assert_called_once_with()


class TestUpdate:
    def test_update_returns_false_for_fallback_handles(self, notifications):
        assert notifications.update(None, "Title", "Body") is False

    def test_update_refreshes_a_real_handle_in_place(self, notifications, fake_notify):
        # A handle of our own: the fake's auto-created children are not safe to
        # count on, since other tests leave calls behind on shared mocks.
        handle = MagicMock()
        fake_notify.Notification.new.return_value = handle
        assert notifications.notify("Title", "Body") is handle
        handle.show.assert_called_once_with()

        assert notifications.update(handle, "New", "Text", "folder-download") is True
        handle.update.assert_called_once_with("New", "Text", "folder-download")
        assert handle.show.call_count == 2

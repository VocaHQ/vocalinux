"""Desktop notifications, with a clickable action where the server offers one.

libnotify is used when it is available and the notification server advertises
the "actions" capability, so a notification can carry a button and be updated
in place. Everywhere else this falls back to spawning ``notify-send``, which is
what the rest of the app has always used.
"""

import logging
import subprocess
from typing import Callable, Optional

logger = logging.getLogger(__name__)

APP_NAME = "Vocalinux"

# Notifications waiting for their action to be clicked. Without a reference the
# notification can be garbage collected before the user answers it, and the
# callback then never runs.
_pending: set = set()

_notify_module = None
_notify_initialized = False


def _libnotify():
    """Return an initialized Notify module, or None when unavailable."""
    global _notify_module, _notify_initialized

    if _notify_initialized:
        return _notify_module

    _notify_initialized = True
    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import Notify

        if not Notify.is_initted() and not Notify.init(APP_NAME):
            logger.debug("libnotify could not be initialized")
            return None
        _notify_module = Notify
    except Exception as e:
        logger.debug(f"libnotify unavailable, falling back to notify-send: {e}")
        _notify_module = None

    return _notify_module


def supports_actions() -> bool:
    """Report whether the notification server can show action buttons."""
    notify = _libnotify()
    if notify is None:
        return False
    try:
        return "actions" in (notify.get_server_caps() or [])
    except Exception as e:
        logger.debug(f"Could not read notification server capabilities: {e}")
        return False


def _notify_send(title: str, message: str, icon: str) -> None:
    """Show a notification through the notify-send binary."""
    try:
        subprocess.Popen(
            ["notify-send", "-i", icon, "-a", APP_NAME, title, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        logger.debug(f"Could not show notification: {e}")


def notify(
    title: str,
    message: str,
    icon: str = "dialog-information",
    action: Optional[tuple[str, Callable[[], None]]] = None,
):
    """Show a notification, optionally carrying a single action button.

    Args:
        title: Notification summary.
        message: Notification body.
        icon: Themed icon name.
        action: ``(label, callback)`` for the button. The callback runs on the
            main loop when the user clicks it.

    Returns:
        A handle that :func:`update` can refresh, or None when the notification
        was shown through the fallback and cannot be updated.
    """
    notify_module = _libnotify()
    if notify_module is None or (action is not None and not supports_actions()):
        # An unclickable button would strand the user, so drop to plain text and
        # keep the instructions that tell them where to go instead.
        _notify_send(title, message, icon)
        return None

    try:
        notification = notify_module.Notification.new(title, message, icon)
        if action is not None:
            label, callback = action

            def _on_action(_notification, _action_id, *_user_data):
                _pending.discard(notification)
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Notification action failed: {e}", exc_info=True)

            notification.add_action("default-action", label, _on_action, None)
            notification.connect("closed", lambda _n: _pending.discard(notification))
            _pending.add(notification)

        notification.show()
        return notification
    except Exception as e:
        logger.debug(f"libnotify failed, falling back to notify-send: {e}")
        _notify_send(title, message, icon)
        return None


def update(notification, title: str, message: str, icon: str = "dialog-information") -> bool:
    """Refresh an existing notification in place.

    Returns:
        True when the notification was updated, False when there is nothing to
        update (fallback notifications cannot be changed after the fact).
    """
    if notification is None:
        return False
    try:
        notification.update(title, message, icon)
        notification.show()
        return True
    except Exception as e:
        logger.debug(f"Could not update notification: {e}")
        return False


def close(notification) -> None:
    """Withdraw a notification that is still on screen."""
    if notification is None:
        return
    try:
        _pending.discard(notification)
        notification.close()
    except Exception as e:
        logger.debug(f"Could not close notification: {e}")

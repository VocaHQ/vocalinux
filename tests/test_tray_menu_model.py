"""
Tests for the Gtk.Menu → GMenuModel bridge used with libayatana-appindicator-glib.

Gio and the Gtk menu are small recording fakes, so the tests check what the
bridge exports without needing GObject Introspection or a display.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from unittest.mock import MagicMock

from vocalinux.ui.tray_menu_model import ACTION_PREFIX, GMenuIndicator, MenuModelBridge


class FakeGioMenu:
    """Records appended entries the way Gio.Menu exposes them."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, Any, Any]] = []
        self.rebuilds = 0

    def append(self, label: str, detailed_action: str) -> None:
        self.entries.append(("item", label, detailed_action))

    def append_submenu(self, label: str, submenu: "FakeGioMenu") -> None:
        self.entries.append(("submenu", label, submenu))

    def append_section(self, label: Optional[str], section: "FakeGioMenu") -> None:
        self.entries.append(("section", label, section))

    def remove_all(self) -> None:
        self.entries = []
        self.rebuilds += 1


class FakeAction:
    def __init__(self, name: str) -> None:
        self.name = name
        self.enabled = True
        self._handlers: list[tuple[Callable[..., None], tuple[Any, ...]]] = []

    def connect(self, _signal: str, handler: Callable[..., None], *user_data: Any) -> None:
        self._handlers.append((handler, user_data))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def activate(self) -> None:
        for handler, user_data in self._handlers:
            handler(self, None, *user_data)


class FakeActionGroup:
    def __init__(self) -> None:
        self.actions: dict[str, FakeAction] = {}

    def lookup_action(self, name: str) -> Optional[FakeAction]:
        return self.actions.get(name)

    def add_action(self, action: FakeAction) -> None:
        self.actions[action.name] = action

    def remove_action(self, name: str) -> None:
        del self.actions[name]


class FakeSimpleAction:
    @staticmethod
    def new(name: str, _parameter_type: Any) -> FakeAction:
        return FakeAction(name)


class FakeGio:
    Menu = FakeGioMenu
    SimpleActionGroup = FakeActionGroup
    SimpleAction = FakeSimpleAction


class FakeMenuItem:
    """Stand-in for Gtk.MenuItem / Gtk.SeparatorMenuItem (label "" = separator)."""

    def __init__(
        self,
        label: str = "",
        *,
        visible: bool = True,
        sensitive: bool = True,
        submenu: Optional["FakeMenu"] = None,
    ) -> None:
        self.label = label
        self.visible = visible
        self.sensitive = sensitive
        self.submenu = submenu
        self.activations = 0

    def get_label(self) -> str:
        return self.label

    def get_visible(self) -> bool:
        return self.visible

    def get_sensitive(self) -> bool:
        return self.sensitive

    def get_submenu(self) -> Optional["FakeMenu"]:
        return self.submenu

    def activate(self) -> None:
        self.activations += 1


class FakeMenu:
    def __init__(self, *items: FakeMenuItem) -> None:
        self.items = list(items)

    def get_children(self) -> list[FakeMenuItem]:
        return list(self.items)


def _sections(menu: FakeGioMenu) -> list[list[tuple[str, Any, Any]]]:
    return [section.entries for kind, _label, section in menu.entries if kind == "section"]


def _labels(menu: FakeGioMenu) -> list[list[str]]:
    return [[label for _kind, label, _payload in section] for section in _sections(menu)]


def test_separators_split_sections_and_hidden_items_are_skipped():
    start = FakeMenuItem("Start")
    menu = FakeMenu(
        start,
        FakeMenuItem("Cancel", visible=False),
        FakeMenuItem(),
        FakeMenuItem(),  # back-to-back separators must not leave an empty section
        FakeMenuItem("Quit"),
    )

    bridge = MenuModelBridge(menu, FakeGio)

    assert _labels(bridge.menu_model) == [["Start"], ["Quit"]]
    first = _sections(bridge.menu_model)[0][0]
    assert first[2].startswith(f"{ACTION_PREFIX}.")


def test_actions_follow_sensitivity_and_activate_the_gtk_item():
    start = FakeMenuItem("Start")
    stop = FakeMenuItem("Stop", sensitive=False)
    bridge = MenuModelBridge(FakeMenu(start, stop), FakeGio)

    names = [payload.split(".", 1)[1] for _k, _l, payload in _sections(bridge.menu_model)[0]]
    start_action, stop_action = (bridge.action_group.actions[name] for name in names)
    assert start_action.enabled is True
    assert stop_action.enabled is False

    start_action.activate()
    assert start.activations == 1

    stop.sensitive = True
    bridge.sync()
    assert stop_action.enabled is True


def test_submenus_are_mirrored_with_their_own_actions():
    snippet = FakeMenuItem("hello world")
    history = FakeMenuItem(
        "Recent Snippets",
        submenu=FakeMenu(snippet, FakeMenuItem(), FakeMenuItem("Clear History")),
    )
    bridge = MenuModelBridge(FakeMenu(history), FakeGio)

    kind, label, submenu = _sections(bridge.menu_model)[0][0]
    assert (kind, label) == ("submenu", "Recent Snippets")
    assert _labels(submenu) == [["hello world"], ["Clear History"]]

    action_name = _sections(submenu)[0][0][2].split(".", 1)[1]
    bridge.action_group.actions[action_name].activate()
    assert snippet.activations == 1


def test_sync_rebuilds_only_when_the_visible_layout_changes():
    update = FakeMenuItem("Update Available…", visible=False)
    bridge = MenuModelBridge(FakeMenu(FakeMenuItem("Start"), update), FakeGio)
    rebuilds = bridge.menu_model.rebuilds

    bridge.sync()
    assert bridge.menu_model.rebuilds == rebuilds

    update.visible = True
    update.label = "Update Available (v1.0.0)…"
    bridge.sync()
    assert bridge.menu_model.rebuilds == rebuilds + 1
    assert _labels(bridge.menu_model) == [["Start", "Update Available (v1.0.0)…"]]


def test_replaced_submenu_items_drop_stale_actions():
    old = FakeMenuItem("old snippet")
    history = FakeMenuItem("Recent Snippets", submenu=FakeMenu(old))
    bridge = MenuModelBridge(FakeMenu(FakeMenuItem("Start"), history), FakeGio)
    assert len(bridge.action_group.actions) == 2

    history.submenu = FakeMenu(FakeMenuItem("(no snippets yet)", sensitive=False))
    bridge.sync()
    assert len(bridge.action_group.actions) == 2

    history.submenu = FakeMenu()
    bridge.sync()
    assert len(bridge.action_group.actions) == 1


def test_gmenu_indicator_adapts_gtk3_calls():
    raw = MagicMock()
    indicator = GMenuIndicator(raw, FakeGio)

    indicator.set_menu(FakeMenu(FakeMenuItem("Start")))
    raw.set_menu.assert_called_once()
    raw.set_actions.assert_called_once()
    exported = raw.set_menu.call_args[0][0]
    assert _labels(exported) == [["Start"]]

    indicator.set_icon_full("vocalinux-microphone", "Microphone on")
    raw.set_icon.assert_called_once_with("vocalinux-microphone", "Microphone on")

    indicator.set_title("Vocalinux")
    raw.set_title.assert_called_once_with("Vocalinux")


def test_refresh_before_set_menu_is_a_no_op():
    GMenuIndicator(MagicMock(), FakeGio).refresh_menu()

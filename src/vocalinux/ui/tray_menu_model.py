"""
GMenuModel bridge for the libayatana-appindicator-glib tray backend.

libayatana-appindicator (GTK 3) takes a Gtk.Menu and now warns at startup
that it is deprecated. Its successor, libayatana-appindicator-glib
(``AyatanaAppIndicatorGlib`` 2.0), takes a GMenuModel plus a GActionGroup
instead. The tray keeps building and mutating its Gtk.Menu exactly as it
does for the GTK 3 backend; this module mirrors that menu into a Gio.Menu
whose actions activate the original Gtk items, so every existing callback
keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Action namespace the glib indicator exports its action group under.
ACTION_PREFIX = "indicator"

# A menu layout is a tuple of sections (Gtk separators split them). Each
# entry is ("item", label, action_name) or ("submenu", label, sub_layout).
_Layout = tuple[tuple[tuple[str, Any, Any], ...], ...]


def _is_separator(item: Any) -> bool:
    """True for a Gtk.SeparatorMenuItem: it has no label and no submenu."""
    return not item.get_label() and item.get_submenu() is None


class MenuModelBridge:
    """Mirror a Gtk.Menu tree into a Gio.Menu and Gio.SimpleActionGroup.

    Hidden items are left out, separators start a new section, submenus are
    mirrored recursively, and item sensitivity maps to action enabled state.
    Call :meth:`sync` after changing the Gtk menu.
    """

    def __init__(self, gtk_menu: Any, gio: Any) -> None:
        self._gtk_menu = gtk_menu
        self._gio = gio
        self.menu_model = gio.Menu()
        self.action_group = gio.SimpleActionGroup()
        self._items: dict[str, Any] = {}
        self._layout: Optional[_Layout] = None
        self.sync()

    def sync(self) -> None:
        """Bring the menu model and actions in line with the Gtk menu."""
        items: dict[str, Any] = {}
        layout = self._describe(self._gtk_menu, items)

        for name, item in items.items():
            action = self.action_group.lookup_action(name)
            if action is None:
                action = self._gio.SimpleAction.new(name, None)
                action.connect("activate", self._on_action_activate, name)
                self.action_group.add_action(action)
            action.set_enabled(bool(item.get_sensitive()))
        for name in self._items.keys() - items.keys():
            self.action_group.remove_action(name)
        self._items = items

        # Only rebuild the model when what the user sees changed: a rebuild
        # makes the tray host re-read the whole menu.
        if layout != self._layout:
            self.menu_model.remove_all()
            self._fill(self.menu_model, layout)
            self._layout = layout

    def _describe(self, gtk_menu: Any, items: dict[str, Any]) -> _Layout:
        """Snapshot the visible structure of ``gtk_menu``, naming each leaf action."""
        sections: list[tuple[tuple[str, Any, Any], ...]] = []
        current: list[tuple[str, Any, Any]] = []
        for item in gtk_menu.get_children():
            if not item.get_visible():
                continue
            if _is_separator(item):
                if current:
                    sections.append(tuple(current))
                current = []
                continue
            submenu = item.get_submenu()
            if submenu is not None:
                current.append(("submenu", item.get_label(), self._describe(submenu, items)))
                continue
            name = f"item-{len(items)}"
            items[name] = item
            current.append(("item", item.get_label(), name))
        if current:
            sections.append(tuple(current))
        return tuple(sections)

    def _fill(self, menu: Any, layout: _Layout) -> None:
        """Append ``layout`` to ``menu`` as one section per Gtk separator group."""
        for section in layout:
            section_menu = self._gio.Menu()
            for kind, label, payload in section:
                if kind == "submenu":
                    submenu = self._gio.Menu()
                    self._fill(submenu, payload)
                    section_menu.append_submenu(label, submenu)
                else:
                    section_menu.append(label, f"{ACTION_PREFIX}.{payload}")
            menu.append_section(None, section_menu)

    def _on_action_activate(self, _action: Any, _parameter: Any, name: str) -> None:
        """Forward an activated action to its Gtk item's ``activate`` handlers."""
        item = self._items.get(name)
        if item is None:
            logger.debug("Tray action %s no longer maps to a menu item", name)
            return
        item.activate()


class GMenuIndicator:
    """Give an ``AyatanaAppIndicatorGlib.Indicator`` the GTK 3 indicator's API.

    The tray calls ``set_menu`` with a Gtk.Menu and ``set_icon_full`` as it
    does on the GTK 3 backend; everything else passes through unchanged.
    """

    def __init__(self, indicator: Any, gio: Any) -> None:
        self._indicator = indicator
        self._gio = gio
        self._bridge: Optional[MenuModelBridge] = None

    def set_menu(self, gtk_menu: Any) -> None:
        """Export ``gtk_menu`` as the indicator's menu model and actions."""
        self._bridge = MenuModelBridge(gtk_menu, self._gio)
        self._indicator.set_menu(self._bridge.menu_model)
        self._indicator.set_actions(self._bridge.action_group)

    def refresh_menu(self) -> None:
        """Re-mirror the Gtk menu after its items changed."""
        if self._bridge is not None:
            self._bridge.sync()

    def set_icon_full(self, icon_name: str, description: str) -> None:
        """Set the icon; the glib library names this ``set_icon``."""
        self._indicator.set_icon(icon_name, description)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._indicator, name)

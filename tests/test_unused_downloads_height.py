"""Tests for sizing the "Unused downloads" list to the rows it holds.

The settings dialog cannot be instantiated under the mocked-GTK harness (see
test_settings_mode_change.py), so the arithmetic lives in a module-level
helper that is unit-tested directly, and the wiring around it is asserted
against the source of the two methods.
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui
from vocalinux.ui import settings_dialog
from vocalinux.ui.settings_dialog import (
    _UNUSED_DOWNLOADS_MAX_HEIGHT,
    _clamp_unused_downloads_height,
)


def _method_source(name: str) -> str:
    src = inspect.getsource(settings_dialog)
    match = re.search(rf"\n    def {name}\(.*?(?=\n    def )", src, re.DOTALL)
    assert match, f"could not locate method {name}"
    return match.group(0)


def test_list_is_as_tall_as_its_rows_render():
    """Two rows that measure 116px must not be squeezed into an estimate.

    56px per row was the old guess; real rows render taller than that once
    margins and the Delete button are counted, which cut off the last row
    while the header still counted it (#683).
    """
    assert _clamp_unused_downloads_height(116) == 116


def test_long_lists_stop_growing_at_the_cap():
    """Beyond the cap the list scrolls instead of pushing the page down."""
    assert _clamp_unused_downloads_height(_UNUSED_DOWNLOADS_MAX_HEIGHT * 3) == (
        _UNUSED_DOWNLOADS_MAX_HEIGHT
    )


def test_refresh_sizes_the_list_after_building_the_rows():
    """A measured height is worthless if the refresh never asks for one."""
    body = _method_source("_refresh_unused_downloads")
    assert "self._fit_unused_downloads_height()" in body
    # The per-row estimate is what clipped the list; it must not come back.
    assert "56 *" not in body


def test_fit_measures_the_listbox_and_feeds_the_scroll():
    body = _method_source("_fit_unused_downloads_height")
    assert "self.unused_models_group.listbox.get_preferred_height()" in body
    assert "self.unused_models_scroll.set_min_content_height(" in body
    assert "_clamp_unused_downloads_height(natural_height)" in body


def test_scrollbar_stays_in_the_layout():
    """An overlay scrollbar hides until hovered, so a capped list looks whole."""
    src = inspect.getsource(settings_dialog)
    assert "self.unused_models_scroll.set_overlay_scrolling(False)" in src


def test_mapping_the_list_remeasures_it():
    """Refresh may run before the dialog is mapped; map must remeasure so a
    short first measurement can never leave rows clipped."""
    src = inspect.getsource(settings_dialog)
    assert re.search(
        r"self\.unused_models_scroll\.connect\(\s*\"map\","
        r"\s*lambda \*_args: self\._fit_unused_downloads_height\(\)",
        src,
    )


def test_expanding_the_list_remeasures_it():
    """Measure while collapsed is worthless; expanding must remeasure."""
    src = inspect.getsource(settings_dialog)
    assert re.search(
        r"self\.unused_expander\.connect\(\s*\"notify::expanded\","
        r"\s*lambda \*_args: self\._fit_unused_downloads_height\(\)",
        src,
    )


def test_unused_downloads_are_a_sibling_expander_not_nested_in_advanced():
    """Same card chrome as Advanced, not an expander inside Advanced."""
    src = inspect.getsource(settings_dialog)
    assert "self.content_box.pack_start(self.unused_island" in src
    assert "self.advanced_box.pack_start(self.unused_models_group" not in src
    assert "self.unused_expander" in src
    assert "_make_expander_card" in src


def test_unused_island_visibility_tracks_nested_group_during_search():
    """Search hides leftover-model rows; the expander header must follow them."""
    src = inspect.getsource(settings_dialog)
    search_body = src.split("def _on_search_changed(self, entry)")[1].split("def ")[0]
    snapshot_body = src.split("def _snapshot_search_baseline")[1].split("def ")[0]
    assert "self.unused_island.set_visible" in search_body
    assert "self.unused_models_group.get_visible()" in search_body
    assert "unused_island" in snapshot_body


@pytest.fixture(scope="module")
def settings_dialog_module():
    """Reimport with real Gtk bases so SettingsDialog search methods stay callable."""
    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog")}
    saved_module = sys.modules.pop("vocalinux.ui.settings_dialog", None)
    saved_attribute = getattr(vocalinux.ui, "settings_dialog", None)
    try:
        with patch.object(repository, "Gtk", MagicMock(**bases)):
            module = importlib.import_module("vocalinux.ui.settings_dialog")
        yield module
    finally:
        sys.modules.pop("vocalinux.ui.settings_dialog", None)
        if saved_module is not None:
            sys.modules["vocalinux.ui.settings_dialog"] = saved_module
        if saved_attribute is not None:
            vocalinux.ui.settings_dialog = saved_attribute
        elif hasattr(vocalinux.ui, "settings_dialog"):
            del vocalinux.ui.settings_dialog


class _Visible:
    """Widget stand-in with the visibility API search actually calls."""

    def __init__(self, visible: bool = True) -> None:
        self._visible = visible
        self._parent = None

    def get_visible(self) -> bool:
        return self._visible

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)

    def hide(self) -> None:
        self._visible = False

    def show(self) -> None:
        self._visible = True

    def get_parent(self) -> Any:
        return self._parent


class _Label(_Visible):
    def __init__(self) -> None:
        super().__init__(visible=False)
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class _SidebarRow(_Visible):
    def __init__(self) -> None:
        super().__init__(visible=True)
        self.sensitive = True

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = bool(sensitive)


class _Group(_Visible):
    def __init__(
        self,
        title: str = "",
        description: str = "",
        keywords: tuple[str, ...] = (),
        rows: list[Any] | None = None,
        visible: bool = True,
    ) -> None:
        super().__init__(visible)
        self.title = title
        self.description = description
        self.keywords = keywords
        self.rows = list(rows or [])


class _Page:
    def __init__(self, name: str, groups: list[_Group]) -> None:
        self.name = name
        self.groups = groups
        self.extras: list[Any] = []
        self.box = _Visible()
        self.sidebar_row = _SidebarRow()
        self.match_count_label = _Label()
        self.update_badge_label = None


class _Stack:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_visible_child_name(self) -> str:
        return self._name

    def set_visible_child_name(self, name: str) -> None:
        self._name = name


class _Listbox:
    def __init__(self) -> None:
        self.selected = None

    def select_row(self, row: Any) -> None:
        self.selected = row

    def unselect_all(self) -> None:
        self.selected = None


class _Entry:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self) -> str:
        return self._text


def _search_row(settings_dialog_module: Any, title: str, **kwargs: Any) -> Any:
    """PreferenceRow subclass that skips GTK construction.

    ``matches_query`` is left on PreferenceRow so a stub cannot make row-only
    searches look like they work.
    """

    class _Row(settings_dialog_module.PreferenceRow, _Visible):
        def __init__(
            self,
            title: str,
            subtitle: str = "",
            keywords: tuple[str, ...] = (),
            visible: bool = True,
        ) -> None:
            _Visible.__init__(self, visible)
            self.title = title
            self.subtitle = subtitle
            self.keywords = keywords

    return _Row(title, **kwargs)


def _wire_unused_search_dialog(settings_dialog_module: Any) -> Mock:
    """Minimal dialog for `_on_search_changed` unused-island visibility."""
    unused_row = _search_row(
        settings_dialog_module,
        "Faster Whisper small",
        subtitle="244 MB",
        keywords=("unused", "download"),
    )
    unused_group = _Group(
        title="Unused downloads",
        description="Downloaded, but not the one in use",
        keywords=("delete", "remove", "unused", "disk", "storage", "downloaded"),
        rows=[unused_row],
    )
    other_group = _Group(
        title="Engine",
        rows=[_search_row(settings_dialog_module, "Speech engine")],
    )
    page = _Page("speech", groups=[other_group, unused_group])
    unused_island = _Visible(visible=True)

    dialog = Mock()
    dialog._pages = [page]
    dialog.unused_island = unused_island
    dialog.unused_models_group = unused_group
    dialog.settings_stack = _Stack("speech")
    dialog.sidebar_listbox = _Listbox()
    dialog._search_baseline = None
    dialog._search_previous_page = None
    dialog._pending_update = None
    dialog.search_empty_label = _Label()
    dialog._update_engine_specific_ui = lambda: None
    dialog._set_about_update_badge = lambda *_args, **_kwargs: None

    dialog_class = settings_dialog_module.SettingsDialog
    for name in (
        "_snapshot_search_baseline",
        "_restore_search_baseline",
        "_on_search_changed",
    ):
        setattr(dialog, name, getattr(dialog_class, name).__get__(dialog))
    return dialog


def test_unused_island_follows_search_hits_and_restores_on_clear(settings_dialog_module):
    """Matching, non-matching, and cleared queries must drive expander visibility."""
    dialog = _wire_unused_search_dialog(settings_dialog_module)
    island = dialog.unused_island
    group = dialog.unused_models_group
    unused_row = group.rows[0]
    engine_row = dialog._pages[0].groups[0].rows[0]

    # Subtitle-only needle: group title/keywords do not contain "244", so the
    # island can show only if PreferenceRow.matches_query actually runs.
    dialog._on_search_changed(_Entry("244"))
    assert unused_row.get_visible() is True
    assert engine_row.get_visible() is False
    assert island.get_visible() is True
    assert group.get_visible() is True

    dialog._on_search_changed(_Entry("unused"))
    assert island.get_visible() is True
    assert group.get_visible() is True

    dialog._on_search_changed(_Entry("engine"))
    assert unused_row.get_visible() is False
    assert island.get_visible() is False
    assert group.get_visible() is False

    dialog._on_search_changed(_Entry(""))
    assert island.get_visible() is True
    assert group.get_visible() is True

"""Tests for sizing the "Unused downloads" list to the rows it holds.

The settings dialog cannot be instantiated under the mocked-GTK harness (see
test_settings_mode_change.py), so the arithmetic lives in a module-level
helper that is unit-tested directly, and the wiring around it is asserted
against the source of the two methods.
"""

import inspect
import re

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


def test_expanding_the_list_remeasures_it():
    """The refresh measures while collapsed and possibly unmapped; expanding
    must remeasure so a short first measurement can never leave rows clipped."""
    src = inspect.getsource(settings_dialog)
    assert re.search(
        r"self\.unused_expander\.connect\(\s*\"notify::expanded\","
        r"\s*lambda \*_args: self\._fit_unused_downloads_height\(\)",
        src,
    )

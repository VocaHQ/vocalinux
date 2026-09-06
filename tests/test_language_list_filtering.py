"""The language list must be searchable while it is open.

A GtkComboBox dropdown takes the keyboard for its own first-letter jump the
moment it opens, so nothing typed reaches a filter. The picker opens a popover
with a search entry above the list instead; every keystroke narrows the rows.
"""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real base classes for its GTK subclasses.

    Box is already among the bases the module needs; SearchablePicker subclasses
    it. Both sys.modules and the package attribute are restored so later tests
    patching the module by name do not reach a second module object (#686).
    """
    repository = sys.modules["gi.repository"]
    bases = {name: type(name, (), {}) for name in ("Box", "ListBoxRow", "Dialog", "ComboBox")}
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


def _row(item_id, text):
    row = Mock()
    row.item_id = item_id
    row.item_text = text
    return row


def _picker_stub(settings_dialog, typed="", rows=(), active=None):
    """A stand-in ``self``: GTK is mocked, the picker's own logic is not."""
    picker = Mock()
    picker.base_model = [[text, item_id] for item_id, text in rows]
    picker._rows_by_id = {item_id: _row(item_id, text) for item_id, text in rows}
    picker._active_id = active
    picker._search.get_text.return_value = typed
    picker._list.get_children.return_value = list(picker._rows_by_id.values())
    # These are the picker's own logic, not collaborators, so they stay real:
    # _select decides whether "changed" fires, _row_is_visible is the filter.
    picker._select.side_effect = lambda item_id, text: settings_dialog.SearchablePicker._select(
        picker, item_id, text
    )
    picker._row_is_visible.side_effect = (
        lambda row: settings_dialog.SearchablePicker._row_is_visible(picker, row)
    )
    return picker


LANGS = (("en-us", "English (US)"), ("pl", "Polish"), ("ja", "Japanese"))


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("pol", ["Polish"]),
        ("POL", ["Polish"]),
        ("ja", ["Japanese"]),
        ("en", ["English (US)"]),
        ("", ["English (US)", "Polish", "Japanese"]),
        ("zzz", []),
    ],
)
def test_typing_narrows_the_list(settings_dialog, typed, expected):
    picker = _picker_stub(settings_dialog, typed=typed, rows=LANGS)
    shown = [
        row.item_text
        for row in picker._rows_by_id.values()
        if settings_dialog.SearchablePicker._row_is_visible(picker, row)
    ]
    assert shown == expected


def test_enter_takes_the_first_row_still_showing(settings_dialog):
    """Typing then Enter must not require reaching for the mouse."""
    picker = _picker_stub(settings_dialog, typed="pol", rows=LANGS)
    for row in picker._list.get_children.return_value:
        row.get_visible.return_value = True
        row.get_child_visible.return_value = True
    picker._first_visible_row.side_effect = (
        lambda: settings_dialog.SearchablePicker._first_visible_row(picker)
    )

    settings_dialog.SearchablePicker._on_search_activate(picker, picker._search)

    picker._on_row_activated.assert_called_once()
    assert picker._on_row_activated.call_args[0][1].item_id == "pl"


def test_enter_with_nothing_matching_selects_nothing(settings_dialog):
    picker = _picker_stub(settings_dialog, typed="zzz", rows=LANGS)
    for row in picker._list.get_children.return_value:
        row.get_visible.return_value = True
        row.get_child_visible.return_value = True
    picker._first_visible_row.side_effect = (
        lambda: settings_dialog.SearchablePicker._first_visible_row(picker)
    )

    settings_dialog.SearchablePicker._on_search_activate(picker, picker._search)

    picker._on_row_activated.assert_not_called()


def test_selecting_by_id_reports_whether_the_row_exists(settings_dialog):
    """_set_combo_active_id_or_first relies on the boolean to fall back."""
    picker = _picker_stub(settings_dialog, rows=LANGS)

    assert settings_dialog.SearchablePicker.set_active_id(picker, "pl") is True
    assert settings_dialog.SearchablePicker.set_active_id(picker, "xx") is False


def test_changed_fires_only_when_the_selection_actually_changes(settings_dialog):
    """Re-selecting the saved language on open must not look like a user edit."""
    picker = _picker_stub(settings_dialog, rows=LANGS, active="pl")

    settings_dialog.SearchablePicker._select(picker, "pl", "Polish")
    picker.emit.assert_not_called()

    settings_dialog.SearchablePicker._select(picker, "ja", "Japanese")
    picker.emit.assert_called_once_with("changed")
    assert picker._active_id == "ja"


def test_opening_starts_from_an_empty_search(settings_dialog):
    """Leftover text from last time would hide most of the list on open."""
    picker = _picker_stub(settings_dialog, rows=LANGS)

    settings_dialog.SearchablePicker._on_button_clicked(picker, None)

    picker._search.set_text.assert_called_once_with("")
    picker._search.grab_focus.assert_called_once()


def test_the_row_helpers_read_the_picker_store(settings_dialog):
    """Resolving typed text must see every language, not only the shown ones."""
    picker = _picker_stub(settings_dialog, rows=LANGS)
    picker.get_model.return_value = []  # would be wrong to consult

    assert settings_dialog._combo_text_rows(picker) == [
        ("en-us", "English (US)"),
        ("pl", "Polish"),
        ("ja", "Japanese"),
    ]


def test_completion_is_not_bolted_onto_the_picker(settings_dialog):
    """Its own filter and a completion popup would fight over the same entry."""
    # A plain Mock wearing the picker's class: isinstance() says picker, and the
    # Box methods GTK would provide are auto-created rather than spec-blocked.
    picker = Mock()
    picker.__class__ = settings_dialog.SearchablePicker

    with patch.object(settings_dialog.Gtk, "EntryCompletion") as completion:
        settings_dialog._attach_language_combo_search(picker)

    completion.assert_not_called()


def test_combo_styling_skips_combo_only_calls_on_the_picker(settings_dialog):
    """get_cells and set_popup_fixed_width do not exist on a Box."""
    picker = Mock()
    picker.__class__ = settings_dialog.SearchablePicker

    settings_dialog._style_combo(picker)

    picker.set_size_request.assert_called_once()
    picker.set_popup_fixed_width.assert_not_called()
    picker.get_cells.assert_not_called()

"""The recommendation must be applicable, and must not ignore the disk (#778)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, Mock, call, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog() -> Iterator[Any]:
    """Import settings_dialog with real base classes for its GTK subclasses.

    Same reasoning as tests/test_settings_model_state.py; both sys.modules and the
    package attribute are restored so later tests patching the module by name do
    not reach a second module object (#686).
    """
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


@pytest.fixture
def dialog_class(settings_dialog: Any) -> Any:
    return settings_dialog.SettingsDialog


def _dialog_stub(language: str = "en-us") -> Mock:
    dialog = Mock()
    dialog.language = language
    dialog.language_combo.get_active_id.return_value = language
    dialog._populating_models = False
    dialog._processing_language_change = False
    # Plain Mock attrs are truthy; these guards must be real False or the
    # language-changed handler returns before updating dialog.language.
    dialog._initializing = False
    dialog._applying_settings = False
    return dialog


def _with_disk(settings_dialog: Any, downloaded: list[str]) -> tuple[Any, Any]:
    """Patch the disk so only ``downloaded`` counts as present."""
    return (
        patch.object(settings_dialog, "list_downloaded_whispercpp_models", return_value=downloaded),
        patch.object(
            settings_dialog,
            "is_whispercpp_model_downloaded",
            side_effect=lambda name: name in downloaded,
        ),
    )


def test_a_bigger_model_on_disk_is_offered_instead_of_a_download(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """The reported case: recommended small.en, medium.en already paid for."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["medium.en", "small", "tiny"])

    with listed, downloaded:
        alternative = dialog_class._downloaded_alternative_for(dialog, "small.en")

    assert alternative == "medium.en"


def test_nothing_is_offered_when_the_recommendation_is_already_on_disk(
    settings_dialog: Any, dialog_class: Any
) -> None:
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["small.en", "medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small.en") is None


def test_a_smaller_model_is_never_offered(settings_dialog: Any, dialog_class: Any) -> None:
    """Reusing a download must not quietly cost accuracy."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["tiny", "tiny.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "medium.en") is None


def test_english_only_weights_are_not_offered_for_another_language(
    settings_dialog: Any, dialog_class: Any
) -> None:
    dialog = _dialog_stub(language="pl")
    listed, downloaded = _with_disk(settings_dialog, ["medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small") is None


def test_the_smallest_qualifying_model_wins(settings_dialog: Any, dialog_class: Any) -> None:
    """Between two usable downloads, take the cheaper one to run."""
    dialog = _dialog_stub()
    listed, downloaded = _with_disk(settings_dialog, ["large", "medium.en"])

    with listed, downloaded:
        assert dialog_class._downloaded_alternative_for(dialog, "small.en") == "medium.en"


def test_applying_the_recommendation_sets_both_pickers(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """Clicking must move size and specialization together, not just one."""
    dialog = _dialog_stub()
    dialog._recommended_target_model = "small.en"

    dialog_class._on_apply_recommendation(dialog, None)

    dialog.model_combo.set_active_id.assert_called_once_with("small")
    dialog._populate_whispercpp_variant_options.assert_called_once_with("small", "small.en")
    dialog.model_variant_combo.set_active_id.assert_called_once_with("small.en")
    dialog._sync_language_options_for_selected_model.assert_called_once_with()
    dialog._update_model_info.assert_called_once_with()
    dialog._refresh_unused_downloads.assert_called_once_with()
    dialog._auto_apply_settings.assert_called_once_with()
    assert dialog._populating_models is False


def test_applying_does_nothing_without_a_target(settings_dialog: Any, dialog_class: Any) -> None:
    dialog = _dialog_stub()
    dialog._recommended_target_model = None

    dialog_class._on_apply_recommendation(dialog, None)

    dialog.model_combo.set_active_id.assert_not_called()
    dialog._auto_apply_settings.assert_not_called()


def test_applying_recommendation_suppresses_model_changed_auto_apply(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """Size change must not briefly auto-apply the default size before the target.

    Without ``_populating_models``, ``set_active_id(large)`` would fire
    ``_on_model_changed`` and download full large before turbo-q5_0 lands.
    """
    dialog = _dialog_stub()
    dialog._recommended_target_model = "large-v3-turbo-q5_0"
    seen_while_setting_size: list[bool] = []

    def capture_flag(_model_size: str) -> bool:
        seen_while_setting_size.append(dialog._populating_models)
        return True

    dialog.model_combo.set_active_id.side_effect = capture_flag

    dialog_class._on_apply_recommendation(dialog, None)

    assert seen_while_setting_size == [True]
    dialog._populate_whispercpp_variant_options.assert_called_once_with(
        "large", "large-v3-turbo-q5_0"
    )
    dialog.model_variant_combo.set_active_id.assert_called_once_with("large-v3-turbo-q5_0")
    # One apply after both pickers settle — not during the size change.
    dialog._auto_apply_settings.assert_called_once_with()
    assert dialog._populating_models is False


def test_language_change_refreshes_recommendation_ui(
    settings_dialog: Any, dialog_class: Any
) -> None:
    """EN→PL must refresh recommendation target / label so Use it is not stale."""
    dialog = _dialog_stub(language="en-us")
    dialog.language_combo.get_active_id.return_value = "pl"
    dialog.engine_combo.get_active_text.return_value = "whisper.cpp"
    dialog._recommended_target_model = "small.en"

    dialog_class._on_language_changed(dialog, None)

    assert dialog.language == "pl"
    dialog._populate_model_options.assert_called_once_with()
    dialog._update_language_warning.assert_called_once_with()
    dialog._update_model_info.assert_called_once_with()
    dialog._auto_apply_settings.assert_called_once_with()
    # Refresh happens before auto-apply so the card is current when settings land.
    assert dialog.mock_calls.index(call._update_model_info()) < dialog.mock_calls.index(
        call._auto_apply_settings()
    )
    assert dialog._processing_language_change is False

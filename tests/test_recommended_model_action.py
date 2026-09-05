"""Tests for clickable recommendation, on-disk comparable offer, and size labels."""

import importlib
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

import vocalinux.ui


@pytest.fixture(scope="module")
def settings_dialog():
    """Import settings_dialog with real bases for GTK subclasses."""
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


class TestWhispercppSizeOptionLabel:
    def test_includes_weight_and_download_marker(self, settings_dialog):
        with patch.object(settings_dialog, "_whispercpp_size_is_downloaded", return_value=True):
            label = settings_dialog._whispercpp_size_option_label("small", "small")
        assert "Small" in label
        assert "MB" in label or "GB" in label
        assert "✓" in label
        assert "★" in label

    def test_marks_missing_download(self, settings_dialog):
        with patch.object(settings_dialog, "_whispercpp_size_is_downloaded", return_value=False):
            label = settings_dialog._whispercpp_size_option_label("medium", "small")
        assert "↓" in label
        assert "★" not in label


class TestFindComparableOnDisk:
    def test_returns_none_when_target_is_downloaded(self, settings_dialog):
        with patch.object(settings_dialog, "is_whispercpp_model_downloaded", return_value=True):
            assert settings_dialog._find_comparable_on_disk_whispercpp("small.en", "en-us") is None

    def test_prefers_same_size_english_when_language_is_english(self, settings_dialog):
        downloaded = {"small", "small-q5_1"}

        def is_downloaded(name):
            return name in downloaded

        with patch.object(
            settings_dialog, "is_whispercpp_model_downloaded", side_effect=is_downloaded
        ):
            result = settings_dialog._find_comparable_on_disk_whispercpp("small.en", "en-us")
        assert result == "small"

    def test_skips_english_only_when_language_is_not_english(self, settings_dialog):
        downloaded = {"small.en", "small.en-q5_1"}

        def is_downloaded(name):
            return name in downloaded

        with patch.object(
            settings_dialog, "is_whispercpp_model_downloaded", side_effect=is_downloaded
        ):
            result = settings_dialog._find_comparable_on_disk_whispercpp("small", "fr")
        assert result is None

    def test_prefers_full_precision_over_quantized(self, settings_dialog):
        downloaded = {"small-q5_1", "small"}

        def is_downloaded(name):
            return name in downloaded

        with patch.object(
            settings_dialog, "is_whispercpp_model_downloaded", side_effect=is_downloaded
        ):
            result = settings_dialog._find_comparable_on_disk_whispercpp("small.en", "en-us")
        assert result == "small"


class TestSelectWhispercppModel:
    def test_sets_size_and_specialization_then_applies(self, settings_dialog):
        dialog = Mock()
        dialog._populating_models = False
        dialog._set_combo_active_id_or_first = Mock()
        dialog._populate_whispercpp_variant_options = Mock()
        dialog._sync_language_options_for_selected_model = Mock()
        dialog._update_model_info = Mock()
        dialog._refresh_unused_downloads = Mock()
        dialog._auto_apply_settings = Mock()
        dialog.model_combo = Mock()

        settings_dialog.SettingsDialog._select_whispercpp_model(dialog, "small.en")

        dialog._set_combo_active_id_or_first.assert_called_once_with(dialog.model_combo, "small")
        dialog._populate_whispercpp_variant_options.assert_called_once_with("small", "small.en")
        dialog._auto_apply_settings.assert_called_once()
        assert dialog._populating_models is False


class TestRecommendationClick:
    def test_whisper_cpp_routes_to_select(self, settings_dialog):
        dialog = Mock()
        dialog._initializing = False
        dialog._applying_settings = False
        dialog._populating_models = False
        dialog._recommended_model_id = "small.en"
        dialog._get_selected_engine = Mock(return_value="whisper_cpp")
        dialog._select_whispercpp_model = Mock()

        settings_dialog.SettingsDialog._on_model_recommendation_clicked(dialog, None)

        dialog._select_whispercpp_model.assert_called_once_with("small.en")

    def test_ignores_click_while_populating(self, settings_dialog):
        dialog = Mock()
        dialog._initializing = False
        dialog._applying_settings = False
        dialog._populating_models = True
        dialog._recommended_model_id = "small.en"
        dialog._select_whispercpp_model = Mock()

        settings_dialog.SettingsDialog._on_model_recommendation_clicked(dialog, None)

        dialog._select_whispercpp_model.assert_not_called()


class TestOfferDialogResponses:
    def _run_once(self, settings_dialog, response):
        dialog = Mock()
        message = Mock()
        message.run.return_value = response
        use_btn = Mock()
        use_btn.get_style_context.return_value = Mock()

        def add_button(label, response_id):
            if response_id == settings_dialog.Gtk.ResponseType.ACCEPT:
                return use_btn
            return Mock()

        message.add_button.side_effect = add_button
        with patch.object(settings_dialog.Gtk, "MessageDialog", return_value=message):
            return settings_dialog.SettingsDialog._offer_comparable_on_disk_dialog(
                dialog, "small.en", "small"
            )

    def test_accept_means_use_disk(self, settings_dialog):
        assert (
            self._run_once(settings_dialog, settings_dialog.Gtk.ResponseType.ACCEPT) == "use_disk"
        )

    def test_reject_means_download(self, settings_dialog):
        assert (
            self._run_once(settings_dialog, settings_dialog.Gtk.ResponseType.REJECT) == "download"
        )

    def test_cancel_means_cancel(self, settings_dialog):
        assert self._run_once(settings_dialog, settings_dialog.Gtk.ResponseType.CANCEL) == "cancel"

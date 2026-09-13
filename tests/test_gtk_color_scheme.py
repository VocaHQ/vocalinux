"""OS color-scheme mapping into gtk-application-prefer-dark-theme (#816)."""

from unittest.mock import MagicMock, patch

import pytest

from vocalinux.utils import gtk_color_scheme as gcs


def _portal_proxy(unpacked):
    proxy = MagicMock()
    result = MagicMock()
    result.unpack.return_value = unpacked
    proxy.call_sync.return_value = result
    return proxy


def _gsettings_ok(stdout: str) -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = stdout
    result.stderr = ""
    return result


@pytest.fixture
def patched_gi():
    gtk = MagicMock()
    gio = MagicMock()
    glib = MagicMock()
    settings = MagicMock()
    gtk.Settings.get_default.return_value = settings
    with (
        patch("gi.repository.Gtk", gtk),
        patch("gi.repository.Gio", gio),
        patch("gi.repository.GLib", glib),
        patch("vocalinux.utils.gtk_color_scheme.subprocess.run") as run,
    ):
        yield {
            "gtk": gtk,
            "gio": gio,
            "glib": glib,
            "settings": settings,
            "run": run,
        }


def test_prefer_dark_from_portal_sets_property_true(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.return_value = _portal_proxy((1,))

    gcs.apply_os_color_scheme()

    patched_gi["settings"].set_property.assert_called_once_with(
        "gtk-application-prefer-dark-theme", True
    )
    patched_gi["run"].assert_not_called()


def test_prefer_light_from_portal_sets_property_false(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.return_value = _portal_proxy((2,))

    gcs.apply_os_color_scheme()

    patched_gi["settings"].set_property.assert_called_once_with(
        "gtk-application-prefer-dark-theme", False
    )
    patched_gi["run"].assert_not_called()


def test_portal_miss_gsettings_prefer_dark_sets_property_true(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.side_effect = RuntimeError("no portal")
    patched_gi["run"].return_value = _gsettings_ok("'prefer-dark'\n")

    gcs.apply_os_color_scheme()

    patched_gi["settings"].set_property.assert_called_once_with(
        "gtk-application-prefer-dark-theme", True
    )
    patched_gi["run"].assert_called_once()
    assert patched_gi["run"].call_args.kwargs.get("env") is not None


def test_gtk_theme_env_skips_settings(monkeypatch, patched_gi):
    monkeypatch.setenv("GTK_THEME", "Adwaita:dark")

    gcs.apply_os_color_scheme()

    patched_gi["gtk"].Settings.get_default.assert_not_called()
    patched_gi["gio"].DBusProxy.new_for_bus_sync.assert_not_called()
    patched_gi["run"].assert_not_called()
    patched_gi["settings"].set_property.assert_not_called()


def test_portal_no_preference_falls_back_to_gsettings(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.return_value = _portal_proxy((0,))
    patched_gi["run"].return_value = _gsettings_ok("'prefer-light'\n")

    gcs.apply_os_color_scheme()

    patched_gi["settings"].set_property.assert_called_once_with(
        "gtk-application-prefer-dark-theme", False
    )


def test_unknown_scheme_leaves_gtk_defaults(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.return_value = _portal_proxy((0,))
    patched_gi["run"].return_value = _gsettings_ok("'default'\n")

    gcs.apply_os_color_scheme()

    patched_gi["settings"].set_property.assert_not_called()


def test_nested_portal_variant_unpacks_to_prefer_dark():
    inner = MagicMock()
    inner.unpack.return_value = 1
    assert gcs._unwrap_portal_value(((inner,),)) == 1
    assert gcs._scheme_from_portal_uint(1) == "prefer-dark"
    assert gcs._scheme_from_portal_uint(2) == "prefer-light"
    assert gcs._scheme_from_portal_uint(0) is None
    assert gcs._scheme_from_gsettings_text("'prefer-dark'") == "prefer-dark"
    assert gcs._scheme_from_gsettings_text("prefer-light\n") == "prefer-light"
    assert gcs._scheme_from_gsettings_text("'default'") is None


def test_apply_fail_soft_on_gtk_error(monkeypatch, patched_gi):
    monkeypatch.delenv("GTK_THEME", raising=False)
    patched_gi["gio"].DBusProxy.new_for_bus_sync.return_value = _portal_proxy((1,))
    patched_gi["gtk"].Settings.get_default.side_effect = RuntimeError("no display")

    gcs.apply_os_color_scheme()

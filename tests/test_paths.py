"""Tests for the XDG base-directory helpers in vocalinux.utils.paths."""

import os
from unittest.mock import patch

from vocalinux.utils import paths


class TestXdgHelpers:
    def test_defaults_when_env_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert paths.xdg_config_home() == os.path.expanduser("~/.config")
            assert paths.xdg_data_home() == os.path.expanduser("~/.local/share")
            assert paths.config_dir() == os.path.expanduser("~/.config/vocalinux")
            assert paths.data_dir() == os.path.expanduser("~/.local/share/vocalinux")
            assert paths.models_dir() == os.path.expanduser("~/.local/share/vocalinux/models")

    def test_honours_xdg_environment(self):
        env = {
            "XDG_CONFIG_HOME": "/run/user/1000/cfg",
            "XDG_DATA_HOME": "/run/user/1000/data",
        }
        with patch.dict(os.environ, env, clear=True):
            assert paths.config_dir() == "/run/user/1000/cfg/vocalinux"
            assert paths.data_dir() == "/run/user/1000/data/vocalinux"
            assert paths.models_dir() == "/run/user/1000/data/vocalinux/models"

    def test_empty_env_falls_back_to_default(self):
        # The XDG spec says empty values must be treated as unset.
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "", "XDG_DATA_HOME": ""}, clear=True):
            assert paths.xdg_config_home() == os.path.expanduser("~/.config")
            assert paths.xdg_data_home() == os.path.expanduser("~/.local/share")

    def test_flatpak_style_data_home(self):
        # Flatpak points XDG_DATA_HOME at ~/.var/app/<app-id>/data.
        flatpak_data = "/home/user/.var/app/com.vocalinux.Vocalinux/data"
        with patch.dict(os.environ, {"XDG_DATA_HOME": flatpak_data}, clear=True):
            assert paths.models_dir() == os.path.join(flatpak_data, "vocalinux", "models")

    def test_is_within_directory(self, tmp_path):
        nested = tmp_path / "models" / "ggml-tiny.bin"
        nested.parent.mkdir()
        nested.write_bytes(b"x")

        assert paths.is_within_directory(str(nested), str(tmp_path / "models"))
        assert not paths.is_within_directory(str(tmp_path / "models"), str(tmp_path / "models"))
        assert paths.is_within_directory(
            str(tmp_path / "models"), str(tmp_path / "models"), allow_root=True
        )
        assert not paths.is_within_directory(str(tmp_path / "other"), str(tmp_path / "models"))
        assert not paths.is_within_directory("/etc/passwd", str(tmp_path / "models"))

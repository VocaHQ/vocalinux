"""Tests for the process-wide shared ConfigManager."""

import json
import os

import pytest

from vocalinux.ui import config_manager as cm


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point the config file at a temp dir and reset the shared instance."""
    monkeypatch.setattr(cm, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(cm, "_shared_instance", None)
    yield tmp_path
    cm._shared_instance = None


def test_accessor_returns_one_instance(isolated_config):
    assert cm.get_shared_config_manager() is cm.get_shared_config_manager()


def test_saves_through_the_accessor_do_not_revert_each_other(isolated_config):
    """The failure mode of separate instances, run through the accessor.

    With two ConfigManagers, the second save wins with its stale cache and
    silently reverts the first one's settings. Sharing the instance keeps
    every earlier save in the file.
    """
    json.dump(
        {"speech_recognition": {"engine": "vosk", "model_size": "medium"}},
        open(cm.CONFIG_FILE, "w"),
    )

    first = cm.get_shared_config_manager()
    first.update_speech_recognition_settings({"engine": "whisper_cpp", "model_size": "small"})
    first.save_config()

    second = cm.get_shared_config_manager()
    second.set("general", "autostart", True)
    second.save_config()

    on_disk = json.load(open(cm.CONFIG_FILE))
    assert on_disk["speech_recognition"]["engine"] == "whisper_cpp"
    assert on_disk["speech_recognition"]["model_size"] == "small"
    assert on_disk["general"]["autostart"] is True


def test_application_code_does_not_construct_its_own_instance():
    """Source guard: a direct ConfigManager() anywhere in src reintroduces the
    stale-cache overwrite, so only the defining module may construct one."""
    src_root = os.path.join(os.path.dirname(__file__), "..", "src", "vocalinux")
    offenders = []
    for root, _dirs, files in os.walk(src_root):
        for name in files:
            if not name.endswith(".py") or name == "config_manager.py":
                continue
            path = os.path.join(root, name)
            with open(path, "r") as handle:
                if "ConfigManager()" in handle.read():
                    offenders.append(os.path.relpath(path, src_root))
    assert offenders == []

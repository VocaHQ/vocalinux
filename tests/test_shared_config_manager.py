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


def _seed_config(engine, model_size):
    """Write a config file that both readers will load before any save."""
    with open(cm.CONFIG_FILE, "w") as handle:
        json.dump({"speech_recognition": {"engine": engine, "model_size": model_size}}, handle)


def _read_config():
    with open(cm.CONFIG_FILE) as handle:
        return json.load(handle)


def test_accessor_returns_one_instance(isolated_config):
    assert cm.get_shared_config_manager() is cm.get_shared_config_manager()


def test_saves_through_the_accessor_do_not_revert_each_other(isolated_config):
    """The failure mode of separate instances, run through the accessor.

    Both handles are taken before either save, the way two collaborators
    (tray and audio feedback) grab one at startup. With two ConfigManagers
    the second save would win with its stale cache and revert the first
    one's engine; one shared instance keeps every earlier save in the file.
    """
    _seed_config(engine="vosk", model_size="medium")

    first = cm.get_shared_config_manager()
    second = cm.get_shared_config_manager()
    assert first is second

    first.update_speech_recognition_settings({"engine": "whisper_cpp", "model_size": "small"})
    first.save_config()

    second.set("general", "autostart", True)
    second.save_config()

    on_disk = _read_config()
    assert on_disk["speech_recognition"]["engine"] == "whisper_cpp"
    assert on_disk["speech_recognition"]["model_size"] == "small"
    assert on_disk["general"]["autostart"] is True


def test_two_instances_still_revert_each_other(isolated_config):
    """Characterization of the bug the accessor exists to prevent (#689).

    Constructing ConfigManager directly is still possible, and it still
    loses writes. This is what the production call sites used to do, and
    what a future one would reintroduce.
    """
    _seed_config(engine="vosk", model_size="medium")

    first = cm.ConfigManager()
    second = cm.ConfigManager()

    first.update_speech_recognition_settings({"engine": "whisper_cpp", "model_size": "small"})
    first.save_config()

    second.set("general", "autostart", True)
    second.save_config()

    on_disk = _read_config()
    assert on_disk["speech_recognition"]["engine"] == "vosk"
    assert on_disk["speech_recognition"]["model_size"] == "medium"


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

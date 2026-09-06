"""Layout-aware combo main-key resolution (issue #513)."""

from __future__ import annotations

import threading
import types

import pytest

from vocalinux.ui.keyboard_backends import layout_key_map as lkm
from vocalinux.ui.keyboard_backends.layout_key_map import build_char_to_evdev_map

evdev_backend = pytest.importorskip("vocalinux.ui.keyboard_backends.evdev_backend")

# Minimal AZERTY fr positions for #513 (a ↔ q swap).
AZERTY = {"a": 16, "q": 30}  # KEY_Q, KEY_A


@pytest.fixture(autouse=True)
def _clear_layout_cache():
    lkm.get_active_char_to_evdev_map.cache_clear()
    yield
    lkm.get_active_char_to_evdev_map.cache_clear()


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
class TestAzertyCombo:
    def _event(self, code, value):
        return types.SimpleNamespace(code=code, value=value, type=1)

    def _backend(self, monkeypatch, shortcut="alt+a"):
        monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: AZERTY)
        return evdev_backend.EvdevKeyboardBackend(shortcut=shortcut, mode="toggle")

    def test_alt_a_fires_on_physical_a(self, monkeypatch):
        from evdev import ecodes

        from vocalinux.ui.keyboard_backends.evdev_backend import KEY_LEFTALT

        backend = self._backend(monkeypatch)
        assert backend._combo_main_code == ecodes.KEY_Q
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._handle_key_event(self._event(KEY_LEFTALT, 1), None)
        backend._handle_key_event(self._event(ecodes.KEY_Q, 1), None)
        assert fired.wait(1.0)

    def test_alt_a_does_not_fire_on_key_a(self, monkeypatch):
        from evdev import ecodes

        from vocalinux.ui.keyboard_backends.evdev_backend import KEY_LEFTALT

        backend = self._backend(monkeypatch)
        fired = threading.Event()
        backend.register_toggle_callback(fired.set)
        backend._handle_key_event(self._event(KEY_LEFTALT, 1), None)
        backend._handle_key_event(self._event(ecodes.KEY_A, 1), None)
        assert not fired.wait(0.2)


def test_xkb_fr_a_is_key_q():
    char_map = build_char_to_evdev_map("fr")
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    from evdev import ecodes

    assert char_map["a"] == ecodes.KEY_Q
    assert char_map["q"] == ecodes.KEY_A


def test_xkb_de_neo_v_is_key_w():
    """German Neo v2: Latin v is physical KEY_W=17, KEY_V=47 types p (#787)."""
    char_map = build_char_to_evdev_map("de", "neo")
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    assert char_map["v"] == 17
    assert char_map["p"] == 47
    evdev = pytest.importorskip("evdev")
    assert char_map["v"] == evdev.ecodes.KEY_W
    assert char_map["p"] == evdev.ecodes.KEY_V


# --- layout_key_map coverage: detection, cache, error paths ---


def test_build_empty_layout_returns_none():
    assert build_char_to_evdev_map("") is None


def test_build_without_libxkbcommon(monkeypatch):
    monkeypatch.setattr(lkm, "_load_xkbcommon", lambda: False)
    assert build_char_to_evdev_map("fr") is None


def test_build_context_failure(monkeypatch):
    class Lib:
        def xkb_context_new(self, _flags):
            return None

    monkeypatch.setattr(lkm, "_load_xkbcommon", lambda: Lib())
    assert build_char_to_evdev_map("fr") is None


def test_build_keymap_failure(monkeypatch):
    unref_called = []

    class Lib:
        def xkb_context_new(self, _flags):
            return 1

        def xkb_keymap_new_from_names(self, *_args):
            return None

        def xkb_context_unref(self, ctx):
            unref_called.append(ctx)

    monkeypatch.setattr(lkm, "_load_xkbcommon", lambda: Lib())
    assert build_char_to_evdev_map("fr") is None
    assert unref_called == [1]


def test_load_xkbcommon_oserror(monkeypatch):
    prev = lkm._xkb_lib

    def boom(_name):
        raise OSError("missing lib")

    try:
        lkm._xkb_lib = None
        monkeypatch.setattr(lkm, "CDLL", boom)
        assert lkm._load_xkbcommon() is False
        assert lkm._xkb_lib is False
        # second call hits the cached False branch
        assert lkm._load_xkbcommon() is False
    finally:
        lkm._xkb_lib = prev


def test_detect_gnome_layout_parses_variant(monkeypatch):
    def fake_run(cmd, **_kwargs):
        return types.SimpleNamespace(
            returncode=0,
            stdout="[('xkb', 'fr+oss'), ('xkb', 'us')]\n",
        )

    monkeypatch.setattr(lkm.subprocess, "run", fake_run)
    assert lkm._detect_gnome_layout() == ("fr", "oss")


def test_detect_gnome_layout_falls_back_to_sources(monkeypatch):
    calls = []

    def fake_run(cmd, **_kwargs):
        key = cmd[-1]
        calls.append(key)
        if key == "mru-sources":
            return types.SimpleNamespace(returncode=0, stdout="@as []\n")
        return types.SimpleNamespace(
            returncode=0,
            stdout="[('xkb', 'de')]\n",
        )

    monkeypatch.setattr(lkm.subprocess, "run", fake_run)
    assert lkm._detect_gnome_layout() == ("de", "")
    assert calls == ["mru-sources", "sources"]


def test_detect_gnome_layout_gsettings_missing(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no gsettings")

    monkeypatch.setattr(lkm.subprocess, "run", boom)
    assert lkm._detect_gnome_layout() == ("", "")


def test_detect_gnome_layout_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        lkm.subprocess,
        "run",
        lambda *_a, **_k: types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert lkm._detect_gnome_layout() == ("", "")


def test_detect_kde_layout_current_layout_neo(tmp_path, monkeypatch):
    (tmp_path / "kxkbrc").write_text("[Layout]\nCurrentLayout=de(neo)\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_list_and_index(tmp_path, monkeypatch):
    (tmp_path / "kxkbrc").write_text(
        "[Layout]\nLayoutList=us,de\nVariantList=,neo\nLayoutIndex=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_current_layout_without_variant_uses_lists(tmp_path, monkeypatch):
    (tmp_path / "kxkbrc").write_text(
        "[Layout]\nCurrentLayout=de\nLayoutList=de\nVariantList=neo\nLayoutIndex=0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("", "")


def test_detect_kde_layout_quoted_and_kconfig_suffix(tmp_path, monkeypatch):
    (tmp_path / "kxkbrc").write_text(
        '[Layout]\nCurrentLayout[$i]="de(neo)"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_index_out_of_range(tmp_path, monkeypatch):
    (tmp_path / "kxkbrc").write_text(
        "[Layout]\nLayoutList=de\nVariantList=neo\nLayoutIndex=9\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert lkm._detect_kde_layout() == ("", "")


def test_detect_active_layout_prefers_gnome_over_kde(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", "oss"))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm._detect_active_layout() == ("fr", "oss")


def test_detect_active_layout_falls_back_to_kde(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm._detect_active_layout() == ("de", "neo")


def test_get_active_map_us_is_none(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("us", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_empty_layout(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("", ""))
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_loads_fr(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", ""))
    char_map = lkm.get_active_char_to_evdev_map()
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    from evdev import ecodes

    assert char_map["a"] == ecodes.KEY_Q


def test_get_active_map_when_build_fails(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", ""))
    monkeypatch.setattr(lkm, "build_char_to_evdev_map", lambda *_a, **_k: None)
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_uses_kde_when_gnome_empty(monkeypatch):
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    char_map = lkm.get_active_char_to_evdev_map()
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    assert char_map["v"] == 17
    assert char_map["p"] == 47


def test_build_skips_keys_with_no_levels(monkeypatch):
    """Keys with zero levels are skipped (line covered via stub lib)."""

    class Lib:
        def xkb_context_new(self, _f):
            return 1

        def xkb_keymap_new_from_names(self, *_a):
            return 2

        def xkb_keymap_min_keycode(self, _km):
            return 10

        def xkb_keymap_max_keycode(self, _km):
            return 10

        def xkb_keymap_num_layouts_for_key(self, _km, _kc):
            return 1

        def xkb_keymap_num_levels_for_key(self, _km, _kc, _layout):
            return 0

        def xkb_keymap_unref(self, _km):
            pass

        def xkb_context_unref(self, _ctx):
            pass

    monkeypatch.setattr(lkm, "_load_xkbcommon", lambda: Lib())
    assert build_char_to_evdev_map("fr") is None


# --- evdev_code_for_key branches on the new layout path ---


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
def test_evdev_code_uses_active_layout_map(monkeypatch):
    from evdev import ecodes

    monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: AZERTY)
    assert evdev_backend.evdev_code_for_key("a") == ecodes.KEY_Q
    assert evdev_backend.evdev_code_for_key("q") == ecodes.KEY_A


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
def test_evdev_code_us_fallback_letter(monkeypatch):
    from evdev import ecodes

    monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: None)
    assert evdev_backend.evdev_code_for_key("a") == ecodes.KEY_A


@pytest.mark.skipif(not evdev_backend.EVDEV_AVAILABLE, reason="evdev not available")
def test_evdev_code_named_and_function_keys(monkeypatch):
    from evdev import ecodes

    monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: AZERTY)
    assert evdev_backend.evdev_code_for_key("space") == ecodes.KEY_SPACE
    assert evdev_backend.evdev_code_for_key("f5") == ecodes.KEY_F5
    assert evdev_backend.evdev_code_for_key("") is None
    assert evdev_backend.evdev_code_for_key("notakey") is None
    # single non-alnum char with no layout entry → None (not KEY_*)
    monkeypatch.setattr(evdev_backend, "get_active_char_to_evdev_map", lambda: None)
    assert evdev_backend.evdev_code_for_key("@") is None

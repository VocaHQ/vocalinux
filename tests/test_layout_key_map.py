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


_REALISTIC_KXKBRC = """[Layout]
DisplayNames=,
LayoutList=us,de
VariantList=,neo
Use=true
"""

_NEO_LAYOUT_MEMORY = """<!DOCTYPE LayoutMap>
<LayoutMap version="1.0" SwitchMode="Global">
        <item currentLayout="de(neo)"/>
</LayoutMap>
"""


def _write_kxkbrc(tmp_path, content: str = _REALISTIC_KXKBRC):
    (tmp_path / "kxkbrc").write_text(content, encoding="utf-8")


def _write_layout_memory(tmp_path, xml: str, *, kded: str = "kded6"):
    session = tmp_path / kded / "keyboard" / "session"
    session.mkdir(parents=True, exist_ok=True)
    (session / "layout_memory.xml").write_text(xml, encoding="utf-8")


def _isolate_kde_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(lkm, "_kde_dbus_layout_index", lambda: None)


def _clear_plasma_env(monkeypatch) -> None:
    """Force the GNOME-first detector order; ignore a KDE CI host's session vars."""
    for var in (
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "DESKTOP_SESSION",
        "KDE_FULL_SESSION",
        "GDMSESSION",
    ):
        monkeypatch.delenv(var, raising=False)


def test_match_token_empty_variant_uses_listed_variant():
    """Bare ``de`` must pick the listed neo pair, not parse as de+empty."""
    pairs = [("us", ""), ("de", "neo")]
    assert lkm._match_token_to_listed_pairs("de", pairs) == ("de", "neo")
    assert lkm._match_token_to_listed_pairs("de(neo)", pairs) == ("de", "neo")
    assert lkm._match_token_to_listed_pairs("us", pairs) == ("us", "")


def test_match_token_with_variant_prefers_exact_pair():
    pairs = [("de", "qwertz"), ("de", "neo")]
    assert lkm._match_token_to_listed_pairs("de(neo)", pairs) == ("de", "neo")
    assert lkm._match_token_to_listed_pairs("de(qwertz)", pairs) == ("de", "qwertz")
    assert lkm._match_token_to_listed_pairs("de", pairs) == ("de", "qwertz")


def test_match_token_unique_layout_name_uses_listed_variant():
    pairs = [("fr", "oss"), ("de", "neo")]
    assert lkm._match_token_to_listed_pairs("de", pairs) == ("de", "neo")
    assert lkm._match_token_to_listed_pairs("fr", pairs) == ("fr", "oss")
    assert lkm._match_token_to_listed_pairs("it", pairs) == ("", "")


def test_detect_kde_layout_memory_neo_not_index_zero(tmp_path, monkeypatch):
    """Neo active in layout_memory, but us is LayoutList index 0 (issue #787)."""
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY)
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_memory_bare_de_keeps_neo_variant(tmp_path, monkeypatch):
    """layout_memory currentLayout=de (no (neo)) still resolves VariantList neo."""
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(
        tmp_path,
        '<LayoutMap version="1.0" SwitchMode="Global">' '<item currentLayout="de"/></LayoutMap>\n',
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_get_active_map_kde_neo_from_layout_memory(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("us", ""))
    _write_kxkbrc(tmp_path)
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY)
    char_map = lkm.get_active_char_to_evdev_map()
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    assert char_map["v"] == 17
    assert char_map["p"] == 47


def test_detect_kde_layout_missing_files(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    assert lkm._detect_kde_layout() == ("", "")


def test_detect_kde_layout_quoted_token(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(
        tmp_path,
        '[Layout]\nLayoutList[$i]="us,de"\nVariantList[$i]=",neo"\nUse=true\n',
    )
    _write_layout_memory(
        tmp_path,
        '<LayoutMap version="1.0" SwitchMode="Global">'
        "<item currentLayout=\"'de(neo)'\"/></LayoutMap>\n",
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_memory_without_kxkbrc(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY)
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_ignores_invented_kxkbrc_keys(tmp_path, monkeypatch):
    """CurrentLayout/LayoutIndex are not in keyboardsettings.kcfg; do not use them."""
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(
        tmp_path,
        "[Layout]\nLayoutList=us,de\nVariantList=,neo\n"
        "CurrentLayout=de(neo)\nLayoutIndex=1\nUse=true\n",
    )
    assert lkm._detect_kde_layout() == ("", "")


def test_detect_kde_layout_single_list_entry(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path, "[Layout]\nLayoutList=de\nVariantList=neo\nUse=true\n")
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_kded5_fallback(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY, kded="kded5")
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_prefers_kded6_over_kded5(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(
        tmp_path,
        '<LayoutMap SwitchMode="Global"><item currentLayout="de(neo)"/></LayoutMap>\n',
        kded="kded6",
    )
    _write_layout_memory(
        tmp_path,
        '<LayoutMap SwitchMode="Global"><item currentLayout="us"/></LayoutMap>\n',
        kded="kded5",
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_malformed_memory_falls_through(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(tmp_path, "<not-xml", kded="kded6")
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY, kded="kded5")
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_multi_item_matches_list(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(
        tmp_path,
        """<LayoutMap version="1.0" SwitchMode="WinClass">
            <item currentLayout="fr" ownerKey="unused"/>
            <item currentLayout="de(neo)" ownerKey="konsole"/>
        </LayoutMap>
        """,
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_layout_multi_item_bare_de_keeps_neo(tmp_path, monkeypatch):
    _isolate_kde_files(tmp_path, monkeypatch)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(
        tmp_path,
        """<LayoutMap version="1.0" SwitchMode="WinClass">
            <item currentLayout="fr" ownerKey="unused"/>
            <item currentLayout="de" ownerKey="konsole"/>
        </LayoutMap>
        """,
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_kde_dbus_layout_index_parses_uint32(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[0] == "gdbus"
        assert "--session" in cmd
        assert "org.kde.keyboard" in cmd
        assert "/Layouts" in cmd
        assert "org.kde.KeyboardLayouts.getLayout" in cmd
        assert kwargs.get("timeout") == 2
        assert kwargs.get("env") is not None
        return types.SimpleNamespace(returncode=0, stdout="(uint32 1,)\n")

    monkeypatch.setattr(lkm.subprocess, "run", fake_run)
    assert lkm._kde_dbus_layout_index() == 1


def test_kde_dbus_layout_index_parses_bare_int(monkeypatch):
    monkeypatch.setattr(
        lkm.subprocess,
        "run",
        lambda *_a, **_k: types.SimpleNamespace(returncode=0, stdout="(1,)\n"),
    )
    assert lkm._kde_dbus_layout_index() == 1


def test_kde_dbus_layout_index_missing_gdbus(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("gdbus")

    monkeypatch.setattr(lkm.subprocess, "run", boom)
    assert lkm._kde_dbus_layout_index() is None


def test_kde_dbus_layout_index_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        lkm.subprocess,
        "run",
        lambda *_a, **_k: types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert lkm._kde_dbus_layout_index() is None


def test_detect_kde_prefers_dbus_index_over_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(lkm, "_kde_dbus_layout_index", lambda: 1)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(
        tmp_path,
        '<LayoutMap SwitchMode="Global"><item currentLayout="us"/></LayoutMap>\n',
    )
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_detect_kde_dbus_out_of_range_falls_through_to_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(lkm, "_kde_dbus_layout_index", lambda: 9)
    _write_kxkbrc(tmp_path)
    _write_layout_memory(tmp_path, _NEO_LAYOUT_MEMORY)
    assert lkm._detect_kde_layout() == ("de", "neo")


def test_is_plasma_session_reads_desktop_vars(monkeypatch):
    _clear_plasma_env(monkeypatch)
    assert not lkm._is_plasma_session()
    monkeypatch.setenv("XDG_SESSION_DESKTOP", "plasmawayland")
    assert lkm._is_plasma_session()
    _clear_plasma_env(monkeypatch)
    monkeypatch.setenv("KDE_FULL_SESSION", "true")
    assert lkm._is_plasma_session()


def test_detect_active_layout_prefers_gnome_outside_plasma(monkeypatch):
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", "oss"))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm._detect_active_layout() == ("fr", "oss")


def test_detect_active_layout_plasma_prefers_kde_over_gnome(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("us", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm._detect_active_layout() == ("de", "neo")


def test_detect_active_layout_falls_back_to_kde(monkeypatch):
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm._detect_active_layout() == ("de", "neo")


def test_detect_active_layout_plasma_falls_back_to_gnome(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "plasma")
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", "oss"))
    assert lkm._detect_active_layout() == ("fr", "oss")


def test_get_active_map_us_is_none(monkeypatch):
    """GNOME us → None only outside Plasma (KDE neo must not win this path)."""
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("us", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_plasma_leftover_gnome_us_loses_to_kde_neo(monkeypatch):
    """Leftover GNOME us must not hide Plasma neo (issue #787)."""
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("us", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("de", "neo"))
    char_map = lkm.get_active_char_to_evdev_map()
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    assert char_map["v"] == 17
    assert char_map["p"] == 47


def test_get_active_map_empty_layout(monkeypatch):
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("", ""))
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_loads_fr(monkeypatch):
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("", ""))
    char_map = lkm.get_active_char_to_evdev_map()
    if char_map is None:
        pytest.skip("libxkbcommon or XKB data not available")
    from evdev import ecodes

    assert char_map["a"] == ecodes.KEY_Q


def test_get_active_map_when_build_fails(monkeypatch):
    _clear_plasma_env(monkeypatch)
    monkeypatch.setattr(lkm, "_detect_gnome_layout", lambda: ("fr", ""))
    monkeypatch.setattr(lkm, "_detect_kde_layout", lambda: ("", ""))
    monkeypatch.setattr(lkm, "build_char_to_evdev_map", lambda *_a, **_k: None)
    assert lkm.get_active_char_to_evdev_map() is None


def test_get_active_map_uses_kde_when_gnome_empty(monkeypatch):
    _clear_plasma_env(monkeypatch)
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

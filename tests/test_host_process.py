"""Guards for the environment Vocalinux hands to host binaries.

An AppImage exports its own `LD_LIBRARY_PATH`, `GI_TYPELIB_PATH` and
`PYTHONHOME`, and every child process inherits them. A host `ibus` linked
against a newer GLib than the bundle carries then exits with `undefined symbol:
g_free_sized` before doing anything, which is how dictated text stopped reaching
the focused window.
"""

import ast
from pathlib import Path

from vocalinux.utils.host_process import host_env

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "src" / "vocalinux"
SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def test_outside_a_bundle_the_environment_is_handed_over_unchanged():
    env = {"LD_LIBRARY_PATH": "/usr/lib", "PATH": "/usr/bin"}
    assert host_env(env) == env


def test_bundle_paths_are_stripped_and_host_ones_survive():
    env = {
        "APPDIR": "/tmp/.mount_Vocali1234",
        "LD_LIBRARY_PATH": "/tmp/.mount_Vocali1234/usr/lib:/usr/lib",
        "GI_TYPELIB_PATH": "/tmp/.mount_Vocali1234/usr/lib/girepository-1.0",
        "PYTHONHOME": "/tmp/.mount_Vocali1234/usr",
        "PATH": "/usr/bin:/bin",
        "GTK_THEME": "Adwaita",
    }
    cleaned = host_env(env)

    assert cleaned["LD_LIBRARY_PATH"] == "/usr/lib", "the host half must survive"
    assert "GI_TYPELIB_PATH" not in cleaned, "nothing but bundle paths were in it"
    assert "PYTHONHOME" not in cleaned
    assert cleaned["PATH"] == "/usr/bin:/bin"
    assert cleaned["GTK_THEME"] == "Adwaita", "non-path values are not paths into the bundle"
    assert cleaned["APPDIR"] == env["APPDIR"], "a child may still need to know it came from one"


def test_every_subprocess_call_hands_over_a_host_environment():
    """Nothing we spawn is ours, so no call may inherit the bundle's paths."""
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in SUBPROCESS_FUNCS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                continue
            if not any(keyword.arg == "env" for keyword in node.keywords):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert not offenders, "these inherit the bundle; pass env=host_env():\n" + "\n".join(offenders)

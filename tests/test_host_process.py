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


def _is_subprocess_call(node) -> bool:
    func = getattr(node, "func", None)
    return (
        isinstance(node, ast.Call)
        and isinstance(func, ast.Attribute)
        and func.attr in SUBPROCESS_FUNCS
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
    )


def _spawns_our_interpreter(node) -> bool:
    """True when the command starts with `sys.executable` — our own Python."""
    if not node.args or not isinstance(node.args[0], ast.List) or not node.args[0].elts:
        return False
    first = node.args[0].elts[0]
    return (
        isinstance(first, ast.Attribute)
        and first.attr == "executable"
        and isinstance(first.value, ast.Name)
        and first.value.id == "sys"
    )


def _env_argument(node):
    return next((kw.value for kw in node.keywords if kw.arg == "env"), None)


def _is_host_env_call(value) -> bool:
    return isinstance(value, ast.Call) and getattr(value.func, "id", None) == "host_env"


def test_host_binaries_get_a_stripped_environment_and_our_own_python_does_not():
    """Two mistakes, opposite directions: a host binary that inherits the bundle
    dies on the wrong GLib, and our own interpreter stripped of it cannot find
    its stdlib or GI stack."""
    inherit, stripped = [], []
    for path in sorted(SOURCE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not _is_subprocess_call(node):
                continue
            where = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
            env = _env_argument(node)
            if _spawns_our_interpreter(node):
                if _is_host_env_call(env):
                    stripped.append(where)
            elif not _is_host_env_call(env):
                inherit.append(where)

    assert (
        not inherit
    ), "these hand the bundle to a host binary; pass env=host_env():\n" + "\n".join(inherit)
    assert not stripped, "these strip the bundle from our own interpreter:\n" + "\n".join(stripped)

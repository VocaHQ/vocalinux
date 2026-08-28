"""Environment for the host binaries Vocalinux shells out to.

An AppImage puts its own libraries first on ``LD_LIBRARY_PATH``, and every child
process inherits that. A host tool linked against a newer GLib than the bundle
carries then dies before it does anything: ``ibus`` exits with ``undefined
symbol: g_free_sized``, the engine never switches, and dictated text goes
nowhere. The same applies to ``GI_TYPELIB_PATH``, ``PYTHONHOME`` and the GTK
module paths the AppImage exports.

Nothing we spawn is ours, so strip the bundle out of the environment first.
"""

import os
from typing import Dict, Mapping, Optional

#: Kept so a child can still tell it came from a bundle. Everything else that
#: points inside it is removed.
_KEEP = ("APPDIR", "APPIMAGE")


def _points_into(value: str, appdir: str) -> bool:
    if not value:
        return False
    return value == appdir or value.startswith(appdir + os.sep)


def host_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Return ``base`` (default ``os.environ``) with bundle paths removed.

    Outside a bundle there is nothing to strip and the environment is returned
    as-is, so callers can use this unconditionally.
    """
    env = dict(os.environ if base is None else base)
    appdir = env.get("APPDIR")
    if not appdir:
        return env
    appdir = os.path.realpath(appdir)

    for name, value in list(env.items()):
        if name in _KEEP or not value:
            continue
        entries = value.split(os.pathsep)
        kept = [entry for entry in entries if not _points_into(os.path.realpath(entry), appdir)]
        if len(kept) == len(entries):
            continue
        if kept:
            env[name] = os.pathsep.join(kept)
        else:
            del env[name]
    return env

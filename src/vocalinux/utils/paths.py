"""XDG base-directory helpers (Flatpak-safe via XDG_CONFIG_HOME / XDG_DATA_HOME)."""

import os

APP_DIR_NAME = "vocalinux"


def xdg_config_home() -> str:
    """Return ``$XDG_CONFIG_HOME`` or ``~/.config`` (empty values treated as unset)."""
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def xdg_data_home() -> str:
    """Return ``$XDG_DATA_HOME`` or ``~/.local/share`` (empty values treated as unset)."""
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def config_dir() -> str:
    """Return the Vocalinux configuration directory."""
    return os.path.join(xdg_config_home(), APP_DIR_NAME)


def data_dir() -> str:
    """Return the Vocalinux data directory."""
    return os.path.join(xdg_data_home(), APP_DIR_NAME)


def models_dir() -> str:
    """Return the directory where speech-recognition models are stored."""
    return os.path.join(data_dir(), "models")


def is_within_directory(path: str, directory: str, *, allow_root: bool = False) -> bool:
    """Return whether ``path`` resolves inside ``directory``.

    Symlinks are resolved before the check. The directory itself is included
    only when ``allow_root`` is true.
    """
    real_path = os.path.realpath(path)
    real_dir = os.path.realpath(directory)
    try:
        rel = os.path.relpath(real_path, real_dir)
    except ValueError:
        return False
    if os.path.isabs(rel) or rel == ".." or rel.startswith(".." + os.sep):
        return False
    if rel == ".":
        return allow_root
    return True

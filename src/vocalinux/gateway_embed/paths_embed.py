"""XDG paths for the embedded gateway checkout and secrets."""

from __future__ import annotations

import os
import re
import secrets

from vocalinux.utils.paths import config_dir

# Keep pin explicit: never float on latest.
GATEWAY_RELEASE_TAG = "v0.1.0"
GATEWAY_GIT_URL = "https://github.com/VocaHQ/vocagateway.git"
COMPOSE_PROJECT = "vocagateway"
DEFAULT_PORT = 8765

# Bootstrap tokens are hex; refuse unbounded or hostile token files.
MAX_TOKEN_FILE_BYTES = 4096
_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32,2048}$")


def xdg_cache_home() -> str:
    return os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")


def gateway_cache_dir() -> str:
    return os.path.join(xdg_cache_home(), "vocalinux", f"vocagateway-{GATEWAY_RELEASE_TAG}")


def gateway_embed_config_dir() -> str:
    return os.path.join(config_dir(), "gateway_embed")


def token_file_path() -> str:
    return os.path.join(gateway_embed_config_dir(), "token")


def env_file_path() -> str:
    return os.path.join(gateway_embed_config_dir(), ".env")


def ensure_token_file(path: str | None = None) -> str:
    """Create a mode-600 bootstrap token if missing; return the token string."""
    token_path = path or token_file_path()
    os.makedirs(os.path.dirname(token_path), mode=0o700, exist_ok=True)
    if os.path.isfile(token_path):
        with open(token_path, "rb") as handle:
            raw = handle.read(MAX_TOKEN_FILE_BYTES + 1)
        if len(raw) <= MAX_TOKEN_FILE_BYTES:
            existing = raw.decode("utf-8", errors="replace").strip()
            if _TOKEN_RE.fullmatch(existing):
                return existing
    token = secrets.token_hex(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(token_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
        handle.write("\n")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return token

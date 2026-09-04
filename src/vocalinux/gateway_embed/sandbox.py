"""Sandbox / packaging detection for container socket access."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxState:
    """Whether the desktop process can reach a host container engine."""

    blocked: bool
    kind: str  # "", "flatpak", "appimage"
    hint: str = ""


def detect_sandbox(
    environ: dict[str, str] | None = None,
) -> SandboxState:
    """Fail closed inside Flatpak; warn for AppImage with a docs hint.

    Flatpak cannot see the host podman/docker socket unless the user has
    explicitly granted filesystem/socket permissions. We do not try to
    smuggle a daemon into the sandbox.
    """
    env = environ if environ is not None else os.environ
    flatpak_id = (env.get("FLATPAK_ID") or "").strip()
    if flatpak_id:
        return SandboxState(
            blocked=True,
            kind="flatpak",
            hint=(
                "Vocalinux is running as a Flatpak and cannot reach the host "
                "podman/docker socket. Run Vocalinux from the native package or "
                "AppImage, or start VocaGateway on the host and point Remote "
                "Server at it. See docs/GATEWAY_EMBED.md."
            ),
        )

    appimage = (env.get("APPIMAGE") or "").strip()
    if appimage:
        # AppImage often can reach the host socket; still surface honesty.
        return SandboxState(
            blocked=False,
            kind="appimage",
            hint=(
                "Running from an AppImage. Local VocaGateway uses the host "
                "podman/docker socket when available; the AppImage does not "
                "bundle a container engine."
            ),
        )

    return SandboxState(blocked=False, kind="", hint="")

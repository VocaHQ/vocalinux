"""Detect a usable container runtime (podman first, then docker)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from vocalinux.utils.host_process import host_env

logger = logging.getLogger(__name__)


class ContainerRuntime(str, Enum):
    PODMAN = "podman"
    DOCKER = "docker"
    NONE = "none"


@dataclass(frozen=True)
class RuntimeInfo:
    kind: ContainerRuntime
    binary: Optional[str] = None
    compose_args: tuple[str, ...] = ()
    hint: str = ""


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _run_ok(argv: Sequence[str], *, timeout: float = 3.0) -> bool:
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            capture_output=True,
            timeout=timeout,
            env=host_env(),
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _compose_argv(
    binary: str,
    kind: ContainerRuntime,
    *,
    path_lookup: Callable[[str], Optional[str]],
    probe: Callable[..., bool],
) -> tuple[str, ...]:
    if probe([binary, "compose", "version"]):
        return (binary, "compose")
    legacy = "podman-compose" if kind is ContainerRuntime.PODMAN else "docker-compose"
    legacy_path = path_lookup(legacy)
    if legacy_path and probe([legacy_path, "version"]):
        return (legacy_path,)
    return (binary, "compose")


def detect_container_runtime(
    *,
    path_lookup: Callable[[str], Optional[str]] = _which,
    probe: Callable[..., bool] = _run_ok,
) -> RuntimeInfo:
    """Prefer podman, fall back to docker, else none with an install hint."""
    podman = path_lookup("podman")
    if podman and (probe([podman, "info"]) or probe([podman, "version"])):
        return RuntimeInfo(
            kind=ContainerRuntime.PODMAN,
            binary=podman,
            compose_args=_compose_argv(
                podman, ContainerRuntime.PODMAN, path_lookup=path_lookup, probe=probe
            ),
        )

    docker = path_lookup("docker")
    if docker and (probe([docker, "info"]) or probe([docker, "version"])):
        return RuntimeInfo(
            kind=ContainerRuntime.DOCKER,
            binary=docker,
            compose_args=_compose_argv(
                docker, ContainerRuntime.DOCKER, path_lookup=path_lookup, probe=probe
            ),
        )

    if podman:
        return RuntimeInfo(
            kind=ContainerRuntime.NONE,
            binary=None,
            hint=(
                "podman is installed but not usable right now. "
                "Start the podman service or check permissions, then reopen Settings."
            ),
        )
    if docker:
        return RuntimeInfo(
            kind=ContainerRuntime.NONE,
            binary=None,
            hint=(
                "docker is installed but not usable right now. "
                "Start the docker service or add your user to the docker group, "
                "then reopen Settings."
            ),
        )

    return RuntimeInfo(
        kind=ContainerRuntime.NONE,
        binary=None,
        hint=(
            "Install podman (preferred) or docker to run a local VocaGateway. "
            "Vocalinux does not bundle a container engine in the AppImage."
        ),
    )


def resolve_runtime_info() -> RuntimeInfo:
    """Production entry point."""
    return detect_container_runtime()

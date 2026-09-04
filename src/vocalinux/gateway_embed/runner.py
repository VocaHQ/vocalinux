"""Compose lifecycle for project ``vocagateway`` pinned to release v0.1.0."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from vocalinux.utils.host_process import host_env

from .paths_embed import (
    COMPOSE_PROJECT,
    DEFAULT_PORT,
    GATEWAY_GIT_URL,
    GATEWAY_RELEASE_TAG,
    ensure_token_file,
    env_file_path,
    gateway_cache_dir,
)
from .runtime import ContainerRuntime, RuntimeInfo, resolve_runtime_info
from .sandbox import SandboxState, detect_sandbox

DEFAULT_IMAGE = "vocagateway:v0.1.0"
# Compose --profile cpu: selects a future cpu profile if present; on v0.1.0
# the unprofiled gateway service still starts, while cuda/vulkan/native stay off.


def _default_run(*args, **kwargs):
    """Run a host binary with AppImage library paths stripped."""
    env = kwargs.pop("env", None)
    return subprocess.run(*args, env=host_env(env), **kwargs)


logger = logging.getLogger(__name__)


@dataclass
class RunnerResult:
    ok: bool
    message: str = ""
    returncode: int = 0


def write_env_file(
    *,
    token: str,
    lan_publish: bool,
    public_url: str | None = None,
    path: str | None = None,
) -> str:
    """Write compose ``.env`` (mode 600). Never log the token."""
    env_path = path or env_file_path()
    os.makedirs(os.path.dirname(env_path), mode=0o700, exist_ok=True)
    publish_host = "0.0.0.0" if lan_publish else "127.0.0.1"
    image = (os.environ.get("VOCAGATEWAY_IMAGE") or DEFAULT_IMAGE).strip()
    if not image or image.endswith(":latest") or image == "latest":
        image = DEFAULT_IMAGE
    lines = [
        f"VOCAGATEWAY_TOKEN={token}",
        f"VOCAGATEWAY_PUBLISH_HOST={publish_host}",
        f"VOCAGATEWAY_PUBLISH_PORT={DEFAULT_PORT}",
        f"VOCAGATEWAY_PORT={DEFAULT_PORT}",
        # Pin image; v0.1.0 release has no published GHCR assets yet, so the
        # first start builds locally into this tag (or VOCAGATEWAY_IMAGE).
        f"VOCAGATEWAY_IMAGE={image}",
    ]
    if public_url:
        lines.append(f"VOCAGATEWAY_PUBLIC_URL={public_url}")
        lines.append(f"VOCAGATEWAY_PAIRING_URL={public_url}")
    content = "\n".join(lines) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(env_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    return env_path


def ensure_gateway_checkout(
    *,
    cache_dir: str | None = None,
    run: Callable[..., subprocess.CompletedProcess] = _default_run,
) -> str:
    """Clone or fetch vocagateway @ v0.1.0 into the XDG cache."""
    dest = cache_dir or gateway_cache_dir()
    os.makedirs(os.path.dirname(dest), mode=0o755, exist_ok=True)
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is required to fetch VocaGateway v0.1.0 compose sources")

    if os.path.isdir(os.path.join(dest, ".git")):
        run(
            [git, "-C", dest, "fetch", "--tags", "--force", "origin", GATEWAY_RELEASE_TAG],
            check=False,
            capture_output=True,
            timeout=120,
        )
        completed = run(
            [git, "-C", dest, "checkout", "-f", GATEWAY_RELEASE_TAG],
            check=False,
            capture_output=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"failed to checkout {GATEWAY_RELEASE_TAG} in {dest}")
        return dest

    if os.path.exists(dest):
        shutil.rmtree(dest)

    completed = run(
        [
            git,
            "clone",
            "--depth",
            "1",
            "--branch",
            GATEWAY_RELEASE_TAG,
            GATEWAY_GIT_URL,
            dest,
        ],
        check=False,
        capture_output=True,
        timeout=180,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"git clone of vocagateway {GATEWAY_RELEASE_TAG} failed: {stderr}")
    return dest


class GatewayRunner:
    """Start/stop the compose project without wiping volumes."""

    def __init__(
        self,
        runtime: RuntimeInfo | None = None,
        sandbox: SandboxState | None = None,
        *,
        run: Callable[..., subprocess.CompletedProcess] = _default_run,
    ):
        self.runtime = runtime or resolve_runtime_info()
        self.sandbox = sandbox if sandbox is not None else detect_sandbox()
        self._run = run
        self._lock = threading.RLock()
        self.managed_by_us = False
        self.last_error = ""
        self._checkout: Optional[str] = None

    @property
    def available(self) -> bool:
        return (
            not self.sandbox.blocked
            and self.runtime.kind is not ContainerRuntime.NONE
            and bool(self.runtime.compose_args)
        )

    @property
    def unavailable_hint(self) -> str:
        if self.sandbox.blocked:
            return self.sandbox.hint
        if self.runtime.hint:
            return self.runtime.hint
        return "No container runtime available."

    def local_base_url(self) -> str:
        return f"http://127.0.0.1:{DEFAULT_PORT}"

    def _compose(
        self,
        args: Sequence[str],
        *,
        cwd: str,
        env_file: str,
        extra_env: Mapping[str, str] | None = None,
        timeout: float = 600,
    ) -> subprocess.CompletedProcess:
        argv = list(self.runtime.compose_args) + ["--env-file", env_file, "-p", COMPOSE_PROJECT]
        argv.extend(args)
        env = host_env()
        if extra_env:
            env.update(extra_env)
        logger.info(
            "gateway compose: %s (cwd=%s)",
            " ".join(argv[:6] + ["…"] if len(argv) > 6 else argv),
            cwd,
        )
        return self._run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            timeout=timeout,
        )

    def prepare(self, *, lan_publish: bool, public_url: str | None = None) -> tuple[str, str, str]:
        """Ensure checkout + token + env. Returns (checkout, token, env_path)."""
        with self._lock:
            if self.sandbox.blocked:
                raise RuntimeError(self.sandbox.hint)
            if not self.available:
                raise RuntimeError(self.unavailable_hint)
            checkout = ensure_gateway_checkout(run=self._run)
            self._checkout = checkout
            token = ensure_token_file()
            env_path = write_env_file(
                token=token,
                lan_publish=lan_publish,
                public_url=public_url,
            )
            compose_file = os.path.join(checkout, "compose.yaml")
            if not os.path.isfile(compose_file):
                raise RuntimeError(f"compose.yaml missing in {checkout}")
            return checkout, token, env_path

    def start(self, *, lan_publish: bool = False, public_url: str | None = None) -> RunnerResult:
        """``compose --profile cpu up -d`` for service gateway (builds if needed)."""
        with self._lock:
            try:
                checkout, _token, env_path = self.prepare(
                    lan_publish=lan_publish, public_url=public_url
                )
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                return RunnerResult(ok=False, message=str(exc), returncode=1)

            completed = self._compose(
                [
                    "-f",
                    "compose.yaml",
                    "--profile",
                    "cpu",
                    "up",
                    "-d",
                    "--build",
                    "gateway",
                ],
                cwd=checkout,
                env_file=env_path,
                timeout=900,
            )
            if completed.returncode != 0:
                stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
                # Never include .env contents; stderr from compose is OK to trim.
                message = stderr.strip()[-800:] or "compose up failed"
                self.last_error = message
                self.managed_by_us = False
                return RunnerResult(ok=False, message=message, returncode=completed.returncode)

            self.managed_by_us = True
            self.last_error = ""
            return RunnerResult(ok=True, message="started", returncode=0)

    def stop(self, *, wipe_volumes: bool = False) -> RunnerResult:
        """``compose down`` without ``-v`` by default (preserve models/token volume)."""
        with self._lock:
            if wipe_volumes:
                # Explicitly refused in v1 UI path; keep for tests only.
                raise RuntimeError("volume wipe is not allowed from the desktop UI")
            checkout = self._checkout or gateway_cache_dir()
            env_path = env_file_path()
            if not os.path.isdir(checkout) or not self.runtime.compose_args:
                self.managed_by_us = False
                return RunnerResult(ok=True, message="nothing to stop")
            if not os.path.isfile(env_path):
                # Still try down with a throwaway env so project name matches.
                token = ensure_token_file()
                env_path = write_env_file(token=token, lan_publish=False)

            completed = self._compose(
                ["-f", "compose.yaml", "--profile", "cpu", "down"],
                cwd=checkout,
                env_file=env_path,
                timeout=180,
            )
            self.managed_by_us = False
            if completed.returncode != 0:
                stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
                message = stderr.strip()[-800:] or "compose down failed"
                self.last_error = message
                return RunnerResult(ok=False, message=message, returncode=completed.returncode)
            self.last_error = ""
            return RunnerResult(ok=True, message="stopped", returncode=0)

    def is_compose_running(self) -> bool:
        """Best-effort ``compose ps -q gateway``."""
        checkout = self._checkout or gateway_cache_dir()
        env_path = env_file_path()
        if not os.path.isdir(checkout) or not os.path.isfile(env_path):
            return False
        if not self.runtime.compose_args:
            return False
        try:
            completed = self._compose(
                ["-f", "compose.yaml", "--profile", "cpu", "ps", "-q", "gateway"],
                cwd=checkout,
                env_file=env_path,
                timeout=30,
            )
        except Exception:  # noqa: BLE001
            return False
        out = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
        return completed.returncode == 0 and bool(out)

"""Session-scoped manager shared by Settings and the tray."""

from __future__ import annotations

import logging
import socket
import threading
from typing import Callable, List, Optional

from .health import probe_health
from .pairing import PairingInfo, fetch_pairing
from .preset import apply_remote_api_preset, remote_api_preset_from_pairing
from .runner import GatewayRunner
from .status import GatewayStatus
from .urls import reject_loopback_url

logger = logging.getLogger(__name__)

StatusListener = Callable[[GatewayStatus, str], None]


def _guess_lan_url(port: int = 8765) -> Optional[str]:
    """Best-effort LAN IPv4 for PUBLIC_URL when user opts into LAN publish."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return None
    if not ip or ip.startswith("127."):
        return None
    candidate = f"http://{ip}:{port}"
    return reject_loopback_url(candidate)


class GatewayEmbedManager:
    """Owns start/stop, health polling, and managed-by-us tray visibility."""

    def __init__(self, runner: GatewayRunner | None = None):
        self.runner = runner or GatewayRunner()
        self._status = GatewayStatus.STOPPED
        self._status_detail = ""
        self._pairing: Optional[PairingInfo] = None
        self._token: str = ""
        self._listeners: List[StatusListener] = []
        self._lock = threading.RLock()
        self._poll_stop = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self.lan_publish = False
        # What compose was last started/republished with (pairing uses this).
        self._compose_lan_publish: Optional[bool] = None
        self._runtime_detect_started = False
        self._republish_started = False
        if not self.runner.runtime_ready:
            self.begin_runtime_detection()

    # ------------------------------------------------------------------
    # listeners (GTK should register wrappers that idle_add into UI)
    # ------------------------------------------------------------------
    def add_listener(self, callback: StatusListener) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: StatusListener) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _emit(self, status: GatewayStatus, detail: str = "") -> None:
        self._status = status
        self._status_detail = detail
        listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(status, detail)
            except Exception:  # noqa: BLE001
                logger.exception("gateway status listener failed")

    @property
    def status(self) -> GatewayStatus:
        return self._status

    @property
    def status_detail(self) -> str:
        return self._status_detail

    @property
    def pairing(self) -> Optional[PairingInfo]:
        return self._pairing

    @property
    def managed_by_us(self) -> bool:
        return bool(self.runner.managed_by_us)

    @property
    def available(self) -> bool:
        return self.runner.available

    @property
    def unavailable_hint(self) -> str:
        return self.runner.unavailable_hint

    @property
    def runtime_ready(self) -> bool:
        return self.runner.runtime_ready

    def begin_runtime_detection(self) -> None:
        """Probe podman/docker off the GTK main thread."""
        if self.runner.runtime_ready:
            return
        with self._lock:
            if self._runtime_detect_started:
                return
            self._runtime_detect_started = True

        def _worker() -> None:
            try:
                self.runner.ensure_runtime()
            except Exception:  # noqa: BLE001
                logger.exception("container runtime detection failed")
            detail = ""
            if not self.runner.available:
                detail = self.runner.unavailable_hint
            self._emit(self._status, detail)

        threading.Thread(
            target=_worker,
            name="vocalinux-gateway-runtime",
            daemon=True,
        ).start()

    def start_async(self, *, lan_publish: bool = False) -> None:
        self.lan_publish = lan_publish
        thread = threading.Thread(
            target=self._start_worker,
            name="vocalinux-gateway-start",
            daemon=True,
        )
        thread.start()

    def stop_async(self) -> None:
        thread = threading.Thread(
            target=self._stop_worker,
            name="vocalinux-gateway-stop",
            daemon=True,
        )
        thread.start()

    def apply_lan_publish(self, lan_publish: bool) -> None:
        """Persist desired LAN flag; republish compose when we manage it.

        Until republish finishes, pairing stays non-Pairable so QR never claims
        LAN while still bound to 127.0.0.1 (or the previous publish mode).
        """
        self.lan_publish = bool(lan_publish)
        if not self.runner.managed_by_us:
            # Next Run will pick up lan_publish; clear stale QR if any.
            if (
                self._compose_lan_publish is not None
                and self._compose_lan_publish != self.lan_publish
            ):
                self._pairing = None
            return
        if self._compose_lan_publish == self.lan_publish:
            return
        # Drop Pairable immediately; republish worker restores it when safe.
        self._pairing = None
        with self._lock:
            if self._republish_started:
                return
            self._republish_started = True
        thread = threading.Thread(
            target=self._republish_worker,
            name="vocalinux-gateway-republish",
            daemon=True,
        )
        thread.start()

    def _republish_worker(self) -> None:
        try:
            with self._lock:
                self._emit(
                    GatewayStatus.STARTING,
                    "Updating LAN publish so the pairing URL matches…",
                )
            public_url = _guess_lan_url() if self.lan_publish else None
            if self.lan_publish and not public_url:
                logger.info("LAN republish enabled but LAN IP could not be guessed")
            result = self.runner.republish(lan_publish=self.lan_publish, public_url=public_url)
            if not result.ok:
                self._emit(
                    GatewayStatus.ERROR,
                    result.message or "Could not update LAN publish. Stop and Run again.",
                )
                return
            self._compose_lan_publish = self.lan_publish
            self._pairing = None
            self.refresh_status()
        finally:
            with self._lock:
                self._republish_started = False

    def _effective_lan_for_pairing(self) -> bool:
        """True only when desired LAN matches what compose actually published."""
        return bool(self.lan_publish) and self._compose_lan_publish is True

    def _start_worker(self) -> None:
        with self._lock:
            self._emit(GatewayStatus.STARTING, "Fetching VocaGateway v0.1.0 and starting compose…")
        public_url = _guess_lan_url() if self.lan_publish else None
        if self.lan_publish and not public_url:
            # Still start with 0.0.0.0 publish; user can set PUBLIC_URL later.
            logger.info("LAN publish enabled but LAN IP could not be guessed")

        try:
            from .paths_embed import ensure_token_file

            self.runner.ensure_runtime()
            self._token = ensure_token_file()
            result = self.runner.start(lan_publish=self.lan_publish, public_url=public_url)
        except Exception as exc:  # noqa: BLE001
            self.runner.managed_by_us = False
            self._emit(GatewayStatus.ERROR, str(exc))
            return

        if not result.ok:
            self._emit(GatewayStatus.ERROR, result.message)
            return

        self._compose_lan_publish = self.lan_publish
        self._start_polling()
        self.refresh_status()

    def _stop_worker(self) -> None:
        self._stop_polling()
        with self._lock:
            self._emit(GatewayStatus.STARTING, "Stopping local VocaGateway…")
        result = self.runner.stop(wipe_volumes=False)
        self._pairing = None
        self._compose_lan_publish = None
        if not result.ok:
            self._emit(GatewayStatus.ERROR, result.message)
            return
        self._emit(GatewayStatus.STOPPED, "")

    def _start_polling(self) -> None:
        self._stop_polling()
        self._poll_stop = threading.Event()

        def _loop() -> None:
            while not self._poll_stop.wait(2.0):
                try:
                    self.refresh_status()
                except Exception:  # noqa: BLE001
                    logger.exception("gateway poll failed")

        self._poll_thread = threading.Thread(
            target=_loop, name="vocalinux-gateway-poll", daemon=True
        )
        self._poll_thread.start()

    def _stop_polling(self) -> None:
        self._poll_stop.set()
        self._poll_thread = None

    def refresh_status(self) -> GatewayStatus:
        """Probe health (+ pairing when live) and emit status."""
        if self._status is GatewayStatus.STARTING and not self.runner.managed_by_us:
            # Mid start/stop worker; leave label alone unless we have live.
            pass

        health = probe_health(self.runner.local_base_url())
        running = self.runner.managed_by_us or self.runner.is_compose_running()

        pairable = False
        if health.live and self._token:
            try:
                public = _guess_lan_url() if self._effective_lan_for_pairing() else None
                # Avoid re-downloading QR SVG every poll (hot-path memory churn).
                need_qr = True
                cached = self._pairing
                if cached is not None and cached.qr_svg and cached.display_url:
                    need_qr = False
                info = fetch_pairing(
                    self.runner.local_base_url(),
                    self._token,
                    public_url=public,
                    fetch_qr=need_qr,
                )
                if (
                    not info.qr_svg
                    and cached is not None
                    and cached.qr_svg
                    and cached.display_url == info.display_url
                ):
                    info = PairingInfo(
                        version=info.version,
                        url=info.url,
                        token=info.token,
                        display_url=info.display_url,
                        raw_payload=info.raw_payload,
                        qr_svg=cached.qr_svg,
                    )
                self._pairing = info
                pairable = info.pairable
            except Exception as exc:  # noqa: BLE001
                # Live but pairing endpoint not ready / auth mismatch.
                logger.info("pairing fetch failed: %s", type(exc).__name__)
                # If LAN publish is off, loopback URL is expected: not Pairable.
                pairable = False

        status = GatewayStatus.from_health(
            live=health.live,
            ready=health.ready,
            pairable=pairable,
            error=False,
            starting=running and not health.live,
            running=running,
        )
        detail = ""
        if status is GatewayStatus.LIVE:
            if self.lan_publish and self._compose_lan_publish is not True:
                detail = (
                    "LAN is on in settings, but publish still needs a restart. "
                    "Stop and Run again (or wait for republish) before pairing a phone."
                )
            else:
                detail = "Gateway process is up. Download a model in the WebUI to become Ready."
        elif status is GatewayStatus.PAIRABLE:
            detail = "Phone can pair. Dictation Ready still needs a selected model."
        elif status is GatewayStatus.READY:
            detail = "Ready for dictation."
        elif status is GatewayStatus.STARTING:
            detail = self._status_detail or "Starting…"
        elif status is GatewayStatus.STOPPED and health.error and running:
            detail = health.error
            status = GatewayStatus.ERROR

        self._emit(status, detail)
        return status

    def use_this_gateway(self, config_manager) -> dict[str, str]:
        """Fill remote_api_* from the current pairing (Ready or Pairable)."""
        info = self._pairing
        if info is None or not info.token:
            raise RuntimeError("No pairing info yet. Wait until status is Pairable or Ready.")

        # Prefer non-loopback; for desktop-only use, allow loopback URL in remote_api
        # (phone QR still rejects loopback separately).
        url = info.display_url or info.url
        if self._effective_lan_for_pairing():
            guessed = _guess_lan_url()
            if guessed:
                url = guessed
        # Desktop "Use this Gateway" may legitimately use 127.0.0.1 when LAN is off.
        if not url:
            raise RuntimeError("Gateway URL missing from pairing payload.")

        preset = remote_api_preset_from_pairing(
            url=url,
            token=info.token,
            prefer_public=bool(reject_loopback_url(url)),
        )
        # When prefer_public rejected loopback, still allow explicit loopback for desktop.
        if not reject_loopback_url(url):
            preset = remote_api_preset_from_pairing(
                url=url,
                token=info.token,
                prefer_public=False,
            )
        apply_remote_api_preset(config_manager, preset)
        return dict(preset)


_MANAGER: Optional[GatewayEmbedManager] = None
_MANAGER_LOCK = threading.Lock()


def get_gateway_embed_manager() -> GatewayEmbedManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = GatewayEmbedManager()
        return _MANAGER


def reset_gateway_embed_manager_for_tests() -> None:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is not None:
            _MANAGER._stop_polling()
        _MANAGER = None

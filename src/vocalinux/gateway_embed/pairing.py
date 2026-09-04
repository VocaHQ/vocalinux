"""Fetch pairing payload and optional QR SVG from a local VocaGateway."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from .urls import is_loopback_url, reject_loopback_url

logger = logging.getLogger(__name__)

# Adversarial: never pull an unbounded SVG into the desktop process.
MAX_QR_SVG_BYTES = 512 * 1024
MAX_PAIRING_JSON_BYTES = 64 * 1024
DEFAULT_TIMEOUT = 3.0


@dataclass(frozen=True)
class PairingInfo:
    """Decoded vocaphone-pair-v1 style payload."""

    version: int
    url: str
    token: str
    display_url: Optional[str]
    raw_payload: dict[str, Any]
    qr_svg: Optional[bytes] = None

    @property
    def pairable(self) -> bool:
        """True when a non-loopback phone URL and token are present."""
        return bool(self.display_url and self.token)


def _read_capped(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        piece = response.read(min(65536, limit - total + 1))
        if not piece:
            break
        total += len(piece)
        if total > limit:
            raise ValueError(f"response exceeded {limit} byte cap")
        chunks.append(piece)
    return b"".join(chunks)


def _authorized_get(
    url: str,
    token: str,
    *,
    timeout: float,
    limit: int,
) -> bytes:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return _read_capped(response, limit)


def decode_pairing_payload(data: dict[str, Any] | str) -> PairingInfo:
    """Decode gateway pairing JSON.

    Accepts either the gateway envelope ``{"payload": {...}}`` / ``{"payload":
    "<json-string>"}`` or a bare ``{v,url,token}`` object.
    """
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        raise ValueError("pairing response must be an object")

    payload = data.get("payload", data)
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("pairing payload must be an object")

    version = int(payload.get("v") or payload.get("version") or 1)
    url = str(payload.get("url") or "").strip()
    token = str(payload.get("token") or "").strip()
    if not url or not token:
        raise ValueError("pairing payload missing url or token")

    display = reject_loopback_url(url)
    return PairingInfo(
        version=version,
        url=url,
        token=token,
        display_url=display,
        raw_payload=dict(payload),
    )


def fetch_pairing(
    base_url: str,
    bearer_token: str,
    *,
    public_url: str | None = None,
    fetch_qr: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> PairingInfo:
    """GET ``/v1/admin/pairing`` and optionally ``/qr.svg``."""
    root = base_url.rstrip("/")
    query = ""
    if public_url and not is_loopback_url(public_url):
        from urllib.parse import quote

        query = f"?url={quote(public_url, safe=':/')}"

    body = _authorized_get(
        f"{root}/v1/admin/pairing{query}",
        bearer_token,
        timeout=timeout,
        limit=MAX_PAIRING_JSON_BYTES,
    )
    info = decode_pairing_payload(json.loads(body.decode("utf-8")))

    qr_svg: Optional[bytes] = None
    if fetch_qr and info.display_url:
        try:
            qr_svg = _authorized_get(
                f"{root}/v1/admin/pairing/qr.svg{query}",
                bearer_token,
                timeout=timeout,
                limit=MAX_QR_SVG_BYTES,
            )
        except Exception as exc:  # noqa: BLE001
            # Soft failure: UI falls back to URL+token text.
            logger.info("QR SVG unavailable: %s", type(exc).__name__)

    return PairingInfo(
        version=info.version,
        url=info.url,
        token=info.token,
        display_url=info.display_url,
        raw_payload=info.raw_payload,
        qr_svg=qr_svg,
    )

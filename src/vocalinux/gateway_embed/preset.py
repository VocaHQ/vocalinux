"""Map a paired local gateway onto Vocalinux remote_api settings."""

from __future__ import annotations

from typing import Mapping

from .urls import reject_loopback_url

GATEWAY_TRANSCRIPTIONS_ENDPOINT = "/v1/audio/transcriptions"


def remote_api_preset_from_pairing(
    *,
    url: str,
    token: str,
    prefer_public: bool = True,
) -> dict[str, str]:
    """Return speech_recognition keys for "Use this Gateway".

    Matches docs/HTTP_REMOTE.md / Gateway docs/configuration.md:
    engine ``remote_api``, OpenAI-compatible transcriptions path, bearer key.
    """
    cleaned = (url or "").strip().rstrip("/")
    if prefer_public:
        display = reject_loopback_url(cleaned)
        if display:
            cleaned = display.rstrip("/")
    if not cleaned:
        raise ValueError("gateway URL is required")
    if not (token or "").strip():
        raise ValueError("gateway token is required")

    return {
        "engine": "remote_api",
        "remote_api_url": cleaned,
        "remote_api_key": token.strip(),
        "remote_api_endpoint": GATEWAY_TRANSCRIPTIONS_ENDPOINT,
        "remote_api_model": "whisper-1",
    }


def apply_remote_api_preset(config_manager, preset: Mapping[str, str]) -> None:
    """Write *preset* into an existing ConfigManager and save."""
    for key, value in preset.items():
        config_manager.set("speech_recognition", key, value)
    config_manager.save_config()

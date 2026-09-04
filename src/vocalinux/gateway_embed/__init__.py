"""Optional local VocaGateway lifecycle helpers for Vocalinux.

This is an opt-in path for power users who want to run
https://github.com/VocaHQ/vocagateway on the same Linux box via podman
(or docker). It is not on-device processing: audio still leaves the
desktop client and goes to the local gateway container.
"""

from .manager import GatewayEmbedManager, get_gateway_embed_manager
from .preset import remote_api_preset_from_pairing
from .runtime import ContainerRuntime, detect_container_runtime
from .status import GatewayStatus
from .urls import is_loopback_url, reject_loopback_url

__all__ = [
    "ContainerRuntime",
    "GatewayEmbedManager",
    "GatewayStatus",
    "detect_container_runtime",
    "get_gateway_embed_manager",
    "is_loopback_url",
    "reject_loopback_url",
    "remote_api_preset_from_pairing",
]

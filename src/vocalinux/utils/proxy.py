"""Outbound-proxy configuration shared by Vocalinux network calls.

Model downloads and update checks read the ``proxy`` section of config.json
through this module so every outbound path honors the same setting:

- ``off`` — connect directly, even when the environment declares a proxy.
- ``system`` — inherit the ``*_proxy`` environment variables (the requests and
  urllib default), falling back to the GNOME ``org.gnome.system.proxy`` manual
  configuration when the environment declares none. GNOME PAC ("auto") mode
  is out of scope.
- ``manual`` — the protocol/host/port (and optional credentials) configured on
  the Settings Proxy page. ``socks5`` is routed as ``socks5h`` so DNS resolves
  at the proxy — local lookups are poisoned or censored in exactly the regions
  this feature serves. ``https`` follows the GNOME/Firefox "HTTPS proxy"
  convention: a plain HTTP CONNECT proxy carrying HTTPS traffic, expressed as
  an ``http://`` proxy URL applied to http and https targets.
"""

import logging
import os
import subprocess
from typing import Any, Dict, Mapping, Optional
from urllib.parse import quote
from urllib.request import ProxyHandler

from .host_process import host_env

logger = logging.getLogger(__name__)

PROXY_MODES = ("off", "system", "manual")
PROXY_PROTOCOLS = ("socks5", "https")

#: "system" preserves the behavior the app has always had: requests and urllib
#: already honor the *_proxy environment variables.
DEFAULT_PROXY_MODE = "system"
DEFAULT_PROXY_PROTOCOL = "socks5"

#: Conventional ports: Settings seeds these and a saved config missing a port
#: falls back to them.
DEFAULT_SOCKS5_PORT = 1080
DEFAULT_HTTPS_PROXY_PORT = 8080

_PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "all_proxy",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
)


def normalize_proxy_mode(value: Any) -> str:
    """Return a supported proxy mode id; unknown or missing becomes the default."""
    if isinstance(value, str) and value.strip().casefold() in PROXY_MODES:
        return value.strip().casefold()
    return DEFAULT_PROXY_MODE


def normalize_proxy_protocol(value: Any) -> str:
    """Return a supported manual protocol id; unknown or missing becomes socks5."""
    if isinstance(value, str) and value.strip().casefold() in PROXY_PROTOCOLS:
        return value.strip().casefold()
    return DEFAULT_PROXY_PROTOCOL


def _saved_proxy_section() -> Mapping[str, Any]:
    """Return the saved ``proxy`` config section, or an empty mapping.

    The shared manager is consulted lazily so this module stays importable
    without the GTK stack, and so tests can bypass it by passing a config
    mapping explicitly.
    """
    try:
        from ..ui.config_manager import get_shared_config_manager
    except ImportError:  # pragma: no cover - defensive
        return {}
    try:
        section = get_shared_config_manager().get_settings().get("proxy", {})
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        logger.debug("Saved proxy configuration is not readable: %s", exc)
        return {}
    return section if isinstance(section, Mapping) else {}


def effective_proxy_config(config: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return normalized proxy settings.

    ``config`` is the raw ``proxy`` config section; when omitted, the saved
    section of the shared ConfigManager is used.
    """
    raw = dict(config) if isinstance(config, Mapping) else dict(_saved_proxy_section())
    try:
        port = int(raw.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if port < 0 or port > 65535:
        port = 0
    return {
        "mode": normalize_proxy_mode(raw.get("mode")),
        "protocol": normalize_proxy_protocol(raw.get("protocol")),
        "host": str(raw.get("host") or "").strip(),
        "port": port,
        "username": str(raw.get("username") or ""),
        "password": str(raw.get("password") or ""),
    }


def default_port_for_protocol(protocol: Any) -> int:
    """Return the conventional listen port for a manual protocol."""
    if normalize_proxy_protocol(protocol) == "socks5":
        return DEFAULT_SOCKS5_PORT
    return DEFAULT_HTTPS_PROXY_PORT


def _bracket_ipv6_host(host: str) -> str:
    """Wrap a bare IPv6 literal in brackets for URL building.

    ``::1`` must become ``[::1]`` before ``:port`` is appended; hostnames and
    already-bracketed literals pass through.
    """
    if host.startswith("[") or ":" not in host:
        return host
    return f"[{host}]"


def manual_proxy_url(config: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Return the manual proxy URL, or None when no host is configured.

    Credentials are percent-encoded into the URL when a username is set.
    """
    cfg = effective_proxy_config(config)
    if not cfg["host"]:
        return None
    scheme = "socks5h" if cfg["protocol"] == "socks5" else "http"
    auth = ""
    if cfg["username"]:
        auth = quote(cfg["username"], safe="")
        if cfg["password"]:
            auth += ":" + quote(cfg["password"], safe="")
        auth += "@"
    port = cfg["port"] or default_port_for_protocol(cfg["protocol"])
    host = _bracket_ipv6_host(cfg["host"])
    return f"{scheme}://{auth}{host}:{port}"


def _env_declares_proxy(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether the environment already declares an HTTP-family proxy."""
    source = os.environ if env is None else env
    return any(
        source.get(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    )


def _gsettings_proxy_values() -> Dict[tuple, str]:
    """Dump ``org.gnome.system.proxy`` as ``{(schema, key): raw_value}``."""
    try:
        result = subprocess.run(
            ["gsettings", "list-recursively", "org.gnome.system.proxy"],
            capture_output=True,
            text=True,
            timeout=5,
            env=host_env(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("GNOME proxy lookup via gsettings failed: %s", exc)
        return {}
    if result.returncode != 0 or not result.stdout:
        return {}
    values: Dict[tuple, str] = {}
    for line in result.stdout.splitlines():
        schema, _, rest = line.partition(" ")
        key, _, raw = rest.partition(" ")
        if schema and key:
            values[(schema, key)] = raw.strip()
    return values


def _unquote_gvariant(value: str) -> str:
    """Strip the single quotes gsettings puts around string values."""
    value = value.strip()
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _gnome_string_list(value: str) -> list:
    """Parse a gsettings ``['a', 'b']`` string list into Python strings."""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    return [item for item in (_unquote_gvariant(part) for part in value[1:-1].split(",")) if item]


def _gnome_system_proxy() -> Optional[Dict[str, Any]]:
    """Return GNOME's manual proxy as ``{"url": ..., "no_proxy": ...}``, or None.

    Only ``mode = 'manual'`` maps onto one URL; PAC ("auto") needs a JS engine
    to evaluate and stays out of scope. The HTTPS pair wins (our downloads are
    HTTPS), then HTTP — which GNOME also applies to HTTPS targets under
    use-same-proxy — then SOCKS.
    """
    values = _gsettings_proxy_values()
    base = "org.gnome.system.proxy"
    if _unquote_gvariant(values.get((base, "mode"), "")) != "manual":
        return None

    def _host_port(child: str) -> tuple:
        host = _unquote_gvariant(values.get((f"{base}.{child}", "host"), ""))
        try:
            port = int(values.get((f"{base}.{child}", "port"), "0"))
        except ValueError:
            port = 0
        return host, port

    no_proxy = ",".join(_gnome_string_list(values.get((base, "ignore-hosts"), "")))

    https_host, https_port = _host_port("https")
    if https_host:
        host = _bracket_ipv6_host(https_host)
        return {"url": f"http://{host}:{https_port}", "no_proxy": no_proxy}

    http_host, http_port = _host_port("http")
    if http_host:
        auth = ""
        # The GNOME schema carries credentials only on the http pair.
        if values.get((f"{base}.http", "use-authentication"), "").strip() == "true":
            user = _unquote_gvariant(values.get((f"{base}.http", "authentication-user"), ""))
            password = _unquote_gvariant(
                values.get((f"{base}.http", "authentication-password"), "")
            )
            if user:
                auth = quote(user, safe="")
                if password:
                    auth += ":" + quote(password, safe="")
                auth += "@"
        host = _bracket_ipv6_host(http_host)
        return {"url": f"http://{auth}{host}:{http_port}", "no_proxy": no_proxy}

    socks_host, socks_port = _host_port("socks")
    if socks_host:
        host = _bracket_ipv6_host(socks_host)
        return {"url": f"socks5h://{host}:{socks_port}", "no_proxy": no_proxy}
    return None


def _system_proxy() -> Optional[Dict[str, Any]]:
    """System-mode proxy: env vars when present, else the GNOME manual config."""
    if _env_declares_proxy():
        # requests and urllib pick the variables up on their own.
        return None
    return _gnome_system_proxy()


def requests_proxies(
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    """Return the ``proxies=`` argument for a ``requests`` call under the mode.

    - ``off``: ``{"no_proxy": "*"}``, a bypass that wins even over proxy
      variables merged in from the environment.
    - ``system``: ``None`` when the environment declares proxies (requests
      honors them natively); an explicit map when only GNOME settings do.
    - ``manual``: the configured URL applied to both schemes; a missing host
      means a direct connection rather than silently falling back to env.
    """
    cfg = effective_proxy_config(config)
    if cfg["mode"] == "off":
        return {"no_proxy": "*"}
    if cfg["mode"] == "manual":
        url = manual_proxy_url(cfg)
        if url is None:
            logger.warning("Manual proxy mode is enabled without a host; connecting directly")
            return {"no_proxy": "*"}
        return {"http": url, "https": url}
    system = _system_proxy()
    if system is None:
        return None
    proxies: Dict[str, str] = {"http": system["url"], "https": system["url"]}
    if system.get("no_proxy"):
        proxies["no_proxy"] = system["no_proxy"]
    return proxies


def urllib_proxy_handler(config: Optional[Mapping[str, Any]] = None) -> ProxyHandler:
    """Return a ``urllib.request.ProxyHandler`` honoring the saved mode.

    ``off`` maps to ``ProxyHandler({})`` — the documented way to disable even
    environment-declared proxies; ``system`` maps to ``ProxyHandler()`` with an
    explicit GNOME map when needed; ``manual`` maps to the configured URL.
    urllib cannot speak SOCKS, so a manual socks5 URL still fails for callers
    that use this handler; the requests paths are the primary network surface.
    """
    cfg = effective_proxy_config(config)
    if cfg["mode"] == "off":
        return ProxyHandler({})
    if cfg["mode"] == "manual":
        url = manual_proxy_url(cfg)
        if url is None:
            logger.warning("Manual proxy mode is enabled without a host; connecting directly")
            return ProxyHandler({})
        return ProxyHandler({"http": url, "https": url})
    system = _system_proxy()
    if system is None:
        return ProxyHandler()
    return ProxyHandler({"http": system["url"], "https": system["url"]})


def proxy_env_vars(config: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
    """Return the ``*_proxy`` environment variables implied by the saved mode.

    Only ``manual`` returns a mapping: the conventional upper- and lowercase
    variables set to the configured URL, so env-reading libraries and spawned
    subprocesses see the same proxy. ``system`` returns empty (inherit the
    process environment as-is) and ``off``/hostless ``manual`` return empty
    (callers strip inherited proxy variables so nothing leaks through).
    """
    cfg = effective_proxy_config(config)
    if cfg["mode"] != "manual":
        return {}
    url = manual_proxy_url(cfg)
    if url is None:
        return {}
    return {
        "HTTP_PROXY": url,
        "HTTPS_PROXY": url,
        "ALL_PROXY": url,
        "http_proxy": url,
        "https_proxy": url,
        "all_proxy": url,
    }


def proxy_env(
    base: Optional[Mapping[str, str]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Return a copy of ``base`` (default ``os.environ``) with proxy vars applied.

    ``off`` strips inherited proxy variables; ``manual`` replaces them with the
    configured URL; ``system`` leaves the environment untouched. ``os.environ``
    itself is never mutated — pass the result to subprocess ``env=``.
    """
    env = dict(os.environ if base is None else base)
    cfg = effective_proxy_config(config)
    if cfg["mode"] == "system":
        return env
    for name in _PROXY_ENV_VARS:
        env.pop(name, None)
    env.update(proxy_env_vars(cfg))
    return env

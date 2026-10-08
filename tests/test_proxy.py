"""Tests for the proxy resolution layer (#655)."""

import os
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from vocalinux.utils.proxy import (
    DEFAULT_HTTPS_PROXY_PORT,
    DEFAULT_PROXY_MODE,
    DEFAULT_PROXY_PROTOCOL,
    DEFAULT_SOCKS5_PORT,
    default_port_for_protocol,
    effective_proxy_config,
    manual_proxy_url,
    normalize_proxy_mode,
    normalize_proxy_protocol,
    proxy_env,
    proxy_env_vars,
    requests_proxies,
    urllib_proxy_handler,
)


def _manual_config(**overrides: Any) -> Dict[str, Any]:
    """Build a manual-mode proxy config dict with sensible defaults."""
    config: Dict[str, Any] = {
        "mode": "manual",
        "protocol": "socks5",
        "host": "proxy.example.com",
        "port": 1080,
        "username": "",
        "password": "",
    }
    config.update(overrides)
    return config


class TestModeAndProtocolParsing:
    def test_default_mode_is_system(self) -> None:
        assert DEFAULT_PROXY_MODE == "system"
        assert normalize_proxy_mode(None) == "system"
        assert normalize_proxy_mode("") == "system"

    def test_mode_normalization(self) -> None:
        assert normalize_proxy_mode("Off") == "off"
        assert normalize_proxy_mode(" MANUAL ") == "manual"
        assert normalize_proxy_mode("bogus") == "system"

    def test_default_protocol_is_socks5(self) -> None:
        assert DEFAULT_PROXY_PROTOCOL == "socks5"
        assert normalize_proxy_protocol(None) == "socks5"
        assert normalize_proxy_protocol("") == "socks5"

    def test_protocol_normalization(self) -> None:
        assert normalize_proxy_protocol("HTTPS") == "https"
        assert normalize_proxy_protocol("bogus") == "socks5"

    def test_default_ports(self) -> None:
        assert default_port_for_protocol("socks5") == DEFAULT_SOCKS5_PORT
        assert default_port_for_protocol("https") == DEFAULT_HTTPS_PROXY_PORT
        assert default_port_for_protocol("bogus") == DEFAULT_SOCKS5_PORT


class TestManualProxyUrl:
    def test_socks5_uses_remote_dns_scheme(self) -> None:
        url = manual_proxy_url(_manual_config())
        assert url == "socks5h://proxy.example.com:1080"

    def test_https_uses_http_connect_scheme(self) -> None:
        url = manual_proxy_url(_manual_config(protocol="https", port=8080))
        assert url == "http://proxy.example.com:8080"

    def test_auth_is_url_encoded(self) -> None:
        url = manual_proxy_url(_manual_config(username="us er", password="p@ss:word"))
        assert url == "socks5h://us%20er:p%40ss%3Aword@proxy.example.com:1080"

    def test_username_without_password(self) -> None:
        url = manual_proxy_url(_manual_config(username="alice"))
        assert url == "socks5h://alice@proxy.example.com:1080"

    def test_password_without_username_is_ignored(self) -> None:
        # Proxy auth always needs a user; a bare password must not produce
        # a "user-less" authority component.
        url = manual_proxy_url(_manual_config(password="secret"))
        assert url == "socks5h://proxy.example.com:1080"

    def test_missing_host_returns_none(self) -> None:
        assert manual_proxy_url(_manual_config(host="")) is None
        assert manual_proxy_url(_manual_config(host="   ")) is None

    def test_invalid_port_falls_back_to_default(self) -> None:
        url = manual_proxy_url(_manual_config(port="abc"))
        assert url == "socks5h://proxy.example.com:1080"

    def test_out_of_range_port_falls_back(self) -> None:
        url = manual_proxy_url(_manual_config(port=99999))
        assert url == "socks5h://proxy.example.com:1080"

    def test_ipv6_host_is_bracketed(self) -> None:
        url = manual_proxy_url(_manual_config(host="::1"))
        assert url == "socks5h://[::1]:1080"

    def test_ipv6_host_already_bracketed_passes_through(self) -> None:
        url = manual_proxy_url(_manual_config(host="[2001:db8::1]"))
        assert url == "socks5h://[2001:db8::1]:1080"


class TestEffectiveProxyConfig:
    def test_reads_saved_section(self) -> None:
        saved = {"proxy": {"mode": "manual", "host": "h", "port": 3128}}
        with patch(
            "vocalinux.utils.proxy._saved_proxy_section",
            return_value=dict(saved["proxy"]),
        ):
            cfg = effective_proxy_config()
        assert cfg["mode"] == "manual"
        assert cfg["host"] == "h"
        assert cfg["port"] == 3128

    def test_passed_config_wins_over_saved(self) -> None:
        with patch(
            "vocalinux.utils.proxy._saved_proxy_section",
            return_value={"mode": "off", "host": "x"},
        ):
            cfg = effective_proxy_config({"mode": "manual", "host": "h"})
        assert cfg["mode"] == "manual"
        assert cfg["host"] == "h"

    def test_saved_values_are_normalized(self) -> None:
        with patch(
            "vocalinux.utils.proxy._saved_proxy_section",
            return_value={"mode": "MANUAL", "protocol": "HTTPS", "host": " h "},
        ):
            cfg = effective_proxy_config()
        assert cfg["mode"] == "manual"
        assert cfg["protocol"] == "https"
        assert cfg["host"] == "h"


class TestRequestsProxies:
    def test_off_bypasses_env_proxies(self) -> None:
        # {"no_proxy": "*"} is how requests is told to connect directly even
        # when *_proxy environment variables are set.
        proxies = requests_proxies({"mode": "off"})
        assert proxies == {"no_proxy": "*"}

    def test_system_with_env_returns_none(self) -> None:
        # requests already honors the environment; None means "do that".
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://10.0.0.1:3128"}, clear=False):
            assert requests_proxies({"mode": "system"}) is None

    def test_system_without_env_reads_gnome(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "vocalinux.utils.proxy._gnome_system_proxy",
                return_value={"url": "http://g:8080", "no_proxy": "localhost"},
            ),
        ):
            proxies = requests_proxies({"mode": "system"})
        assert proxies == {
            "http": "http://g:8080",
            "https": "http://g:8080",
            "no_proxy": "localhost",
        }

    def test_system_without_env_or_gnome_is_direct(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("vocalinux.utils.proxy._gnome_system_proxy", return_value=None),
        ):
            assert requests_proxies({"mode": "system"}) is None

    def test_manual_returns_http_and_https(self) -> None:
        proxies = requests_proxies(_manual_config())
        assert proxies == {
            "http": "socks5h://proxy.example.com:1080",
            "https": "socks5h://proxy.example.com:1080",
        }

    def test_manual_without_host_goes_direct(self) -> None:
        # A saved manual mode with an empty host must not silently fall back
        # to env proxies the user meant to bypass.
        proxies = requests_proxies(_manual_config(host=""))
        assert proxies == {"no_proxy": "*"}


class TestUrllibProxyHandler:
    def test_off_disables_proxies(self) -> None:
        handler = urllib_proxy_handler({"mode": "off"})
        assert handler.proxies == {}

    def test_system_uses_environment(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("vocalinux.utils.proxy._gnome_system_proxy", return_value=None),
        ):
            handler = urllib_proxy_handler({"mode": "system"})
        # No proxies kwarg means urllib reads the environment itself.
        assert handler.proxies == {}

    def test_manual_maps_to_http_and_https(self) -> None:
        handler = urllib_proxy_handler(_manual_config(protocol="https", port=8080))
        assert handler.proxies == {
            "http": "http://proxy.example.com:8080",
            "https": "http://proxy.example.com:8080",
        }


class TestProxyEnv:
    def test_manual_sets_upper_and_lower_vars(self) -> None:
        env = proxy_env_vars(_manual_config())
        url = "socks5h://proxy.example.com:1080"
        assert env == {
            "HTTP_PROXY": url,
            "HTTPS_PROXY": url,
            "ALL_PROXY": url,
            "http_proxy": url,
            "https_proxy": url,
            "all_proxy": url,
        }

    def test_off_and_system_set_nothing(self) -> None:
        assert proxy_env_vars({"mode": "off"}) == {}
        assert proxy_env_vars({"mode": "system", "host": "h"}) == {}

    def test_manual_without_host_sets_nothing(self) -> None:
        assert proxy_env_vars(_manual_config(host="")) == {}

    def test_proxy_env_never_mutates_os_environ(self) -> None:
        base = {"PATH": "/bin", "HTTP_PROXY": "http://old:1"}
        with patch.dict(os.environ, {}, clear=True):
            merged = proxy_env(base, _manual_config())
            # The process environment is untouched: callers pass the returned
            # copy to subprocess env= instead of mutating os.environ.
            assert os.environ == {}
        assert base["HTTP_PROXY"] == "http://old:1"
        assert merged["PATH"] == "/bin"
        assert merged["HTTP_PROXY"] == "socks5h://proxy.example.com:1080"


class TestGnomeSystemProxy:
    """GNOME org.gnome.system.proxy parsing (manual mode only)."""

    def _run_proxy(
        self, stdout: str, env: Optional[Dict[str, str]] = None
    ) -> Optional[Dict[str, str]]:
        from vocalinux.utils.proxy import _gnome_system_proxy

        fake = MagicMock()
        fake.returncode = 0
        fake.stdout = stdout
        with patch("vocalinux.utils.proxy.subprocess.run", return_value=fake):
            return _gnome_system_proxy()

    def test_none_mode_returns_none(self) -> None:
        proxies = self._run_proxy("org.gnome.system.proxy mode 'none'\n")
        assert proxies is None

    def test_auto_mode_is_unsupported(self) -> None:
        proxies = self._run_proxy("org.gnome.system.proxy mode 'auto'\n")
        assert proxies is None

    def test_manual_mode_builds_url(self) -> None:
        stdout = (
            "org.gnome.system.proxy mode 'manual'\n"
            "org.gnome.system.proxy.http host 'g.proxy'\n"
            "org.gnome.system.proxy.http port 8080\n"
            "org.gnome.system.proxy.http enabled true\n"
            "org.gnome.system.proxy.https host ''\n"
            "org.gnome.system.proxy.https port 0\n"
            "org.gnome.system.proxy.socks host ''\n"
            "org.gnome.system.proxy.socks port 0\n"
            "org.gnome.system.proxy ignore-hosts ['localhost', '127.0.0.1']\n"
        )
        proxies = self._run_proxy(stdout)
        assert proxies == {
            "url": "http://g.proxy:8080",
            "no_proxy": "localhost,127.0.0.1",
        }

    def test_gsettings_failure_returns_none(self) -> None:
        from vocalinux.utils.proxy import _gnome_system_proxy

        with patch(
            "vocalinux.utils.proxy.subprocess.run",
            side_effect=OSError("gsettings not found"),
        ):
            assert _gnome_system_proxy() is None

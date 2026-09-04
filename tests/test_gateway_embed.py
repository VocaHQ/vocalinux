"""Unit tests for local VocaGateway embed helpers (no real containers)."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vocalinux.gateway_embed.pairing import (
    MAX_QR_SVG_BYTES,
    decode_pairing_payload,
)
from vocalinux.gateway_embed.preset import (
    GATEWAY_TRANSCRIPTIONS_ENDPOINT,
    remote_api_preset_from_pairing,
)
from vocalinux.gateway_embed.runtime import ContainerRuntime, detect_container_runtime
from vocalinux.gateway_embed.sandbox import detect_sandbox
from vocalinux.gateway_embed.status import GatewayStatus
from vocalinux.gateway_embed.urls import is_loopback_url, reject_loopback_url
from vocalinux.ui.config_manager import DEFAULT_CONFIG


class TestLoopbackRejection(unittest.TestCase):
    def test_rejects_localhost_variants(self):
        for url in (
            "http://127.0.0.1:8765",
            "http://localhost:8765",
            "http://[::1]:8765",
            "https://127.0.0.1/",
            "",
            None,
        ):
            self.assertTrue(is_loopback_url(url), url)
            self.assertIsNone(reject_loopback_url(url))

    def test_accepts_lan(self):
        url = "http://192.168.1.20:8765"
        self.assertFalse(is_loopback_url(url))
        self.assertEqual(reject_loopback_url(url), url)


class TestRuntimeDetector(unittest.TestCase):
    def test_prefers_podman(self):
        def lookup(name):
            return {
                "podman": "/usr/bin/podman",
                "docker": "/usr/bin/docker",
            }.get(name)

        def probe(argv, **_kwargs):
            return argv[0] in {"/usr/bin/podman", "/usr/bin/docker"} and argv[1] in {
                "info",
                "version",
                "compose",
            }

        info = detect_container_runtime(path_lookup=lookup, probe=probe)
        self.assertEqual(info.kind, ContainerRuntime.PODMAN)
        self.assertEqual(info.binary, "/usr/bin/podman")

    def test_falls_back_to_docker(self):
        def lookup(name):
            return {"docker": "/usr/bin/docker"}.get(name)

        def probe(argv, **_kwargs):
            return argv[0] == "/usr/bin/docker"

        info = detect_container_runtime(path_lookup=lookup, probe=probe)
        self.assertEqual(info.kind, ContainerRuntime.DOCKER)

    def test_none_with_hint(self):
        info = detect_container_runtime(path_lookup=lambda _n: None, probe=lambda *_a, **_k: False)
        self.assertEqual(info.kind, ContainerRuntime.NONE)
        self.assertIn("podman", info.hint.lower())


class TestStatusMachine(unittest.TestCase):
    def test_ready_beats_pairable(self):
        self.assertEqual(
            GatewayStatus.from_health(live=True, ready=True, pairable=True, running=True),
            GatewayStatus.READY,
        )

    def test_pairable_before_ready(self):
        self.assertEqual(
            GatewayStatus.from_health(live=True, ready=False, pairable=True, running=True),
            GatewayStatus.PAIRABLE,
        )

    def test_live_only(self):
        self.assertEqual(
            GatewayStatus.from_health(live=True, ready=False, pairable=False, running=True),
            GatewayStatus.LIVE,
        )

    def test_starting(self):
        self.assertEqual(
            GatewayStatus.from_health(
                live=False, ready=False, pairable=False, running=True, starting=True
            ),
            GatewayStatus.STARTING,
        )

    def test_stopped(self):
        self.assertEqual(
            GatewayStatus.from_health(live=False, ready=False, pairable=False, running=False),
            GatewayStatus.STOPPED,
        )

    def test_error(self):
        self.assertEqual(
            GatewayStatus.from_health(
                live=False, ready=False, pairable=False, error=True, running=False
            ),
            GatewayStatus.ERROR,
        )


class TestRemoteApiPreset(unittest.TestCase):
    def test_maps_openai_path(self):
        preset = remote_api_preset_from_pairing(
            url="http://192.168.1.20:8765",
            token="a" * 32,
        )
        self.assertEqual(preset["engine"], "remote_api")
        self.assertEqual(preset["remote_api_url"], "http://192.168.1.20:8765")
        self.assertEqual(preset["remote_api_key"], "a" * 32)
        self.assertEqual(preset["remote_api_endpoint"], GATEWAY_TRANSCRIPTIONS_ENDPOINT)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            remote_api_preset_from_pairing(url="", token="x" * 32)


class TestPairingDecode(unittest.TestCase):
    def test_payload_object(self):
        info = decode_pairing_payload(
            {
                "payload": {
                    "v": 1,
                    "url": "http://10.0.0.5:8765",
                    "token": "tokentokentokentokentokentoken12",
                }
            }
        )
        self.assertEqual(info.display_url, "http://10.0.0.5:8765")
        self.assertTrue(info.pairable)

    def test_payload_string_and_loopback_hidden(self):
        raw = json.dumps({"v": 1, "url": "http://127.0.0.1:8765", "token": "t" * 32})
        info = decode_pairing_payload({"payload": raw})
        self.assertIsNone(info.display_url)
        self.assertFalse(info.pairable)

    def test_qr_download_capped(self):
        from vocalinux.gateway_embed.pairing import _read_capped

        class FakeResp:
            def __init__(self, payload: bytes):
                self._buf = io.BytesIO(payload)

            def read(self, n=-1):
                return self._buf.read(n if n is not None else -1)

        huge = b"x" * (MAX_QR_SVG_BYTES + 10)
        with self.assertRaises(ValueError):
            _read_capped(FakeResp(huge), MAX_QR_SVG_BYTES)


class TestSandbox(unittest.TestCase):
    def test_flatpak_fails_closed(self):
        state = detect_sandbox({"FLATPAK_ID": "com.vocahq.Vocalinux"})
        self.assertTrue(state.blocked)
        self.assertEqual(state.kind, "flatpak")
        self.assertIn("Flatpak", state.hint)

    def test_host_ok(self):
        state = detect_sandbox({})
        self.assertFalse(state.blocked)


class TestDefaultEngineUnchanged(unittest.TestCase):
    def test_default_still_whisper_cpp(self):
        self.assertEqual(DEFAULT_CONFIG["speech_recognition"]["engine"], "whisper_cpp")
        self.assertIn("gateway_embed", DEFAULT_CONFIG)
        self.assertFalse(DEFAULT_CONFIG["gateway_embed"]["lan_publish"])


class TestRunnerNoVolumeWipe(unittest.TestCase):
    def test_stop_refuses_wipe_flag(self):
        from vocalinux.gateway_embed.runner import GatewayRunner
        from vocalinux.gateway_embed.runtime import RuntimeInfo

        runner = GatewayRunner(
            runtime=RuntimeInfo(
                kind=ContainerRuntime.PODMAN,
                binary="/usr/bin/podman",
                compose_args=("/usr/bin/podman", "compose"),
            ),
            sandbox=detect_sandbox({}),
            run=MagicMock(),
        )
        with self.assertRaises(RuntimeError):
            runner.stop(wipe_volumes=True)


class TestComposeUpArgs(unittest.TestCase):
    def test_start_uses_default_gateway_service(self):
        from vocalinux.gateway_embed.runner import GatewayRunner
        from vocalinux.gateway_embed.runtime import RuntimeInfo

        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            completed = MagicMock()
            completed.returncode = 0
            completed.stdout = b""
            completed.stderr = b""
            return completed

        runner = GatewayRunner(
            runtime=RuntimeInfo(
                kind=ContainerRuntime.PODMAN,
                binary="/usr/bin/podman",
                compose_args=("/usr/bin/podman", "compose"),
            ),
            sandbox=detect_sandbox({}),
            run=fake_run,
        )
        with patch.object(runner, "prepare", return_value=("/tmp/gw", "t" * 32, "/tmp/.env")):
            result = runner.start(lan_publish=False)
        self.assertTrue(result.ok)
        compose_calls = [c for c in calls if c[:2] == ["/usr/bin/podman", "compose"]]
        self.assertTrue(compose_calls)
        argv = compose_calls[0]
        self.assertNotIn("--profile", argv)
        self.assertIn("up", argv)
        self.assertIn("-d", argv)
        self.assertIn("gateway", argv)


class TestImagePin(unittest.TestCase):
    def test_rejects_latest_override(self):
        import tempfile

        from vocalinux.gateway_embed.runner import write_env_file

        with tempfile.TemporaryDirectory() as tmp:
            env_path = f"{tmp}/.env"
            with patch.dict("os.environ", {"VOCAGATEWAY_IMAGE": "vocagateway:latest"}):
                write_env_file(token="a" * 32, lan_publish=False, path=env_path)
            body = Path(env_path).read_text(encoding="utf-8")
            self.assertIn("VOCAGATEWAY_IMAGE=vocagateway:v0.1.0", body)
            self.assertNotIn(":latest", body)


if __name__ == "__main__":
    unittest.main()

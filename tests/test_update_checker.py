"""Tests for the GitHub Releases update checker."""

import logging
from unittest.mock import MagicMock, patch

from vocalinux.utils.update_checker import (
    ReleaseInfo,
    fetch_latest_release,
    format_release_notes,
    is_newer_version,
    is_trusted_release_url,
    is_update_available,
    normalize_channel,
    normalize_version,
)


class TestNormalizeAndCompare:
    def test_normalize_version_strips_v_prefix(self):
        assert normalize_version("v0.15.0") == "0.15.0"
        assert normalize_version("V0.15.0") == "0.15.0"

    def test_equal_versions_are_not_newer(self):
        assert not is_newer_version("0.15.0", "0.15.0")
        assert not is_newer_version("v0.15.0", "0.15.0")

    def test_numeric_ordering(self):
        assert is_newer_version("0.9.0", "0.10.0")
        assert is_newer_version("0.15.0", "0.15.1")
        assert not is_newer_version("1.0.0", "0.99.0")

    def test_stable_outranks_prerelease(self):
        assert is_newer_version("0.15.0-beta", "0.15.0")
        assert not is_newer_version("0.15.0", "0.15.0-beta")

    def test_dot_prerelease_suffix(self):
        assert is_newer_version("0.15.0.rc1", "0.15.0")
        assert not is_newer_version("0.15.0", "0.15.0.rc1")

    def test_build_metadata_ignored(self):
        assert not is_newer_version("0.15.0+flatpak", "0.15.0")


class TestChannels:
    def test_normalize_channel(self):
        assert normalize_channel("stable") == "stable"
        assert normalize_channel("NIGHTLY") == "nightly"
        assert normalize_channel("nope") == "stable"

    def test_stable_update_uses_semver(self):
        release = ReleaseInfo(
            tag_name="v0.15.0",
            version="0.15.0",
            name="v0.15.0",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0",
            body="",
            published_at="2026-08-02T00:00:00Z",
            prerelease=False,
            channel="stable",
        )
        assert is_update_available("0.14.0", release, "stable")
        assert not is_update_available("0.15.0", release, "stable")

    def test_nightly_update_compares_dates(self):
        release = ReleaseInfo(
            tag_name="nightly-2026-08-02",
            version="nightly-2026-08-02",
            name="Nightly Build - 0.14.2.dev20260802+27ecf88",
            html_url="https://github.com/VocaHQ/vocalinux/releases/tag/nightly-2026-08-02",
            body="",
            published_at="2026-08-02T00:00:00Z",
            prerelease=True,
            channel="nightly",
        )
        assert is_update_available("nightly-2026-08-01", release, "nightly")
        assert not is_update_available("nightly-2026-08-02", release, "nightly")
        # Installed nightlies use .devYYYYMMDD[+sha], not the GitHub tag name.
        assert not is_update_available("0.14.2.dev20260802+27ecf88", release, "nightly")
        assert is_update_available("0.14.2.dev20260801+aaaaaaa", release, "nightly")
        # Stable installs following nightly should be offered the latest nightly.
        assert is_update_available("0.15.0", release, "nightly")


class TestTrustedUrls:
    def test_accepts_project_urls(self):
        assert is_trusted_release_url("https://github.com/VocaHQ/vocalinux")
        assert is_trusted_release_url("https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0")
        # Pre-transfer URLs still redirect and must stay trusted.
        assert is_trusted_release_url("https://github.com/jatinkrmalik/vocalinux")
        assert is_trusted_release_url(
            "https://github.com/jatinkrmalik/vocalinux/releases/tag/v0.15.0"
        )

    def test_rejects_untrusted_urls(self):
        assert not is_trusted_release_url("https://evil.example/payload")
        assert not is_trusted_release_url("http://github.com/VocaHQ/vocalinux")
        assert not is_trusted_release_url("https://github.com/evil/vocalinux")
        assert not is_trusted_release_url("")


class TestFormatReleaseNotes:
    def test_empty_body(self):
        assert "No release notes" in format_release_notes("")

    def test_keeps_code_block_contents(self):
        body = "Install with:\n```bash\ncurl -fsSL https://example.com | bash\n```\nDone"
        notes = format_release_notes(body)
        assert "curl -fsSL https://example.com | bash" in notes
        assert "```" not in notes

    def test_strips_images_and_keeps_links(self):
        body = 'See [docs](https://example.com) <img src="x.png" alt="x" />'
        notes = format_release_notes(body)
        assert "docs (https://example.com)" in notes
        assert "<img" not in notes


class TestFetchLatestRelease:
    def test_returns_none_on_network_error(self):
        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("offline")
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            assert fetch_latest_release() is None

    def test_parses_release_payload(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v0.15.0",
            "name": "v0.15.0",
            "html_url": "https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0",
            "body": "Notes",
            "published_at": "2026-08-02T22:29:58Z",
            "prerelease": False,
        }
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            release = fetch_latest_release()

        assert isinstance(release, ReleaseInfo)
        assert release.version == "0.15.0"
        assert release.html_url.endswith("/v0.15.0")
        mock_requests.get.assert_called_once()
        api_url = mock_requests.get.call_args[0][0]
        assert api_url == "https://api.github.com/repos/VocaHQ/vocalinux/releases/latest"

    def test_drops_untrusted_html_url(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v0.15.0",
            "name": "v0.15.0",
            "html_url": "https://evil.example/download",
            "body": "Notes",
            "published_at": "2026-08-02T22:29:58Z",
            "prerelease": False,
        }
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            release = fetch_latest_release()

        assert release is not None
        assert release.html_url == ""

    def test_nightly_channel_picks_nightly_tag(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "v0.15.0",
                "name": "v0.15.0",
                "html_url": "https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0",
                "body": "Stable",
                "published_at": "2026-08-02T22:29:58Z",
                "prerelease": False,
                "draft": False,
            },
            {
                "tag_name": "nightly-2026-08-02",
                "name": "nightly-2026-08-02",
                "html_url": "https://github.com/VocaHQ/vocalinux/releases/tag/nightly-2026-08-02",
                "body": "Nightly",
                "published_at": "2026-08-02T05:00:00Z",
                "prerelease": True,
                "draft": False,
            },
        ]
        mock_requests = MagicMock()
        mock_requests.get.return_value = mock_response
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            release = fetch_latest_release(channel="nightly")

        assert release is not None
        assert release.tag_name == "nightly-2026-08-02"
        assert release.channel == "nightly"
        mock_requests.get.assert_called_once()
        assert mock_requests.get.call_args[0][0].endswith("/releases")

    def test_nightly_channel_pages_past_non_nightly_releases(self):
        """Newest nightly can sit beyond the first /releases page."""
        page1 = [
            {
                "tag_name": f"v0.15.{i}",
                "name": f"v0.15.{i}",
                "html_url": f"https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.{i}",
                "body": "",
                "published_at": "2026-08-03T00:00:00Z",
                "prerelease": False,
                "draft": False,
            }
            for i in range(30, 0, -1)
        ]
        page2 = [
            {
                "tag_name": "nightly-2026-08-01",
                "name": "nightly-2026-08-01",
                "html_url": ("https://github.com/VocaHQ/vocalinux/releases/tag/nightly-2026-08-01"),
                "body": "Nightly",
                "published_at": "2026-08-01T05:00:00Z",
                "prerelease": True,
                "draft": False,
            }
        ]
        responses = []
        for payload in (page1, page2):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = payload
            responses.append(mock_response)

        mock_requests = MagicMock()
        mock_requests.get.side_effect = responses
        mock_requests.exceptions.RequestException = Exception

        with patch.dict("sys.modules", {"requests": mock_requests}):
            release = fetch_latest_release(channel="nightly")

        assert release is not None
        assert release.tag_name == "nightly-2026-08-01"
        assert mock_requests.get.call_count == 2
        assert mock_requests.get.call_args_list[0].kwargs["params"]["page"] == 1
        assert mock_requests.get.call_args_list[1].kwargs["params"]["page"] == 2

    def test_stable_api_403_uses_html_fallback(self, caplog):
        release = self._fetch_stable_with_rate_limit(403, caplog)
        assert isinstance(release, ReleaseInfo)
        assert release.version == "0.17.0"
        assert release.channel == "stable"
        assert release.html_url == "https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0"

    def test_stable_api_429_uses_html_fallback(self, caplog):
        release = self._fetch_stable_with_rate_limit(429, caplog)
        assert isinstance(release, ReleaseInfo)
        assert release.version == "0.17.0"
        assert release.channel == "stable"
        assert release.html_url == "https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0"

    def test_stable_api_403_fallback_failures_return_none_quietly(self, caplog):
        api_response = _mock_response(403)
        failures = [
            _mock_response(
                500,
                url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0",
            ),
            Exception("offline"),
            _mock_response(
                200,
                json_value=["not", "a", "dict"],
                url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0",
            ),
            _mock_response(
                200,
                json_value={"update_url": "/VocaHQ/vocalinux/releases/tag/v0.17.0"},
                url="https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0",
            ),
        ]
        caplog.set_level(logging.WARNING, logger="vocalinux.utils.update_checker")
        for failure in failures:
            mock_requests = _requests_mock([api_response, failure])
            with patch.dict("sys.modules", {"requests": mock_requests}):
                assert fetch_latest_release() is None
            assert _checker_warnings(caplog) == []
            caplog.clear()

    def test_evil_update_url_does_not_become_html_url(self, caplog):
        tag_url = "https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0"
        evil_paths = [
            "/evil/vocalinux/releases/tag/v9",
            "https://evil.example/x",
            "/VocaHQ/vocalinux/releases/../evil",
        ]
        caplog.set_level(logging.WARNING, logger="vocalinux.utils.update_checker")
        for update_url in evil_paths:
            api_response = _mock_response(403)
            fallback = _mock_response(
                200,
                json_value={"tag_name": "v0.17.0", "update_url": update_url},
                url=tag_url,
            )
            mock_requests = _requests_mock([api_response, fallback])
            with patch.dict("sys.modules", {"requests": mock_requests}):
                release = fetch_latest_release()
            assert release is not None
            assert release.version == "0.17.0"
            assert release.html_url == ""
            assert _checker_warnings(caplog) == []
            caplog.clear()

    def test_untrusted_fallback_final_url_is_rejected(self, caplog):
        payload = {
            "tag_name": "v0.17.0",
            "update_url": "/VocaHQ/vocalinux/releases/tag/v0.17.0",
        }
        untrusted_urls = (
            "https://evil.example/VocaHQ/vocalinux/releases/tag/v0.17.0",
            "https://github.com/evil/vocalinux/releases/tag/v0.17.0",
            "http://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0",
        )
        caplog.set_level(logging.WARNING, logger="vocalinux.utils.update_checker")
        for final_url in untrusted_urls:
            api_response = _mock_response(403)
            fallback = _mock_response(200, json_value=payload, url=final_url)
            mock_requests = _requests_mock([api_response, fallback])
            with patch.dict("sys.modules", {"requests": mock_requests}):
                assert fetch_latest_release() is None
            assert _checker_warnings(caplog) == []
            caplog.clear()

    def test_nightly_api_403_returns_none_without_html_fallback(self, caplog):
        api_response = _mock_response(403)
        mock_requests = _requests_mock([api_response])
        caplog.set_level(logging.WARNING, logger="vocalinux.utils.update_checker")
        with patch.dict("sys.modules", {"requests": mock_requests}):
            assert fetch_latest_release(channel="nightly") is None
        mock_requests.get.assert_called_once()
        requested = mock_requests.get.call_args[0][0]
        assert requested == "https://api.github.com/repos/VocaHQ/vocalinux/releases"
        assert _checker_warnings(caplog) == []

    def _fetch_stable_with_rate_limit(self, status_code: int, caplog):
        tag_url = "https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0"
        api_response = _mock_response(status_code)
        fallback = _mock_response(
            200,
            json_value={
                "tag_name": "v0.17.0",
                "update_url": "/VocaHQ/vocalinux/releases/tag/v0.17.0",
                "id": 1,
                "edit_url": "/VocaHQ/vocalinux/releases/tag/v0.17.0/edit",
                "delete_url": "/VocaHQ/vocalinux/releases/tag/v0.17.0",
                "update_authenticity_token": "csrf-update",
                "delete_authenticity_token": "csrf-delete",
            },
            url=tag_url,
        )
        mock_requests = _requests_mock([api_response, fallback])
        caplog.set_level(logging.WARNING, logger="vocalinux.utils.update_checker")
        with patch.dict("sys.modules", {"requests": mock_requests}):
            release = fetch_latest_release()

        assert mock_requests.get.call_count == 2
        first, second = mock_requests.get.call_args_list
        assert first[0][0] == "https://api.github.com/repos/VocaHQ/vocalinux/releases/latest"
        assert first.kwargs["headers"]["Accept"] == "application/vnd.github+json"
        assert first.kwargs["headers"]["User-Agent"] == "Vocalinux-UpdateChecker"
        assert "Authorization" not in first.kwargs["headers"]
        assert second[0][0] == "https://github.com/VocaHQ/vocalinux/releases/latest"
        assert second.kwargs["headers"]["Accept"] == "application/json"
        assert second.kwargs["headers"]["User-Agent"] == "Vocalinux-UpdateChecker"
        assert "Authorization" not in second.kwargs["headers"]
        assert fallback.url == tag_url
        assert _checker_warnings(caplog) == []
        assert release is not None
        assert "csrf-update" not in repr(release)
        assert "csrf-delete" not in repr(release)
        return release


def _mock_response(status_code, json_value=None, url=""):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.url = url
    mock_response.json.return_value = json_value
    return mock_response


def _requests_mock(side_effect):
    mock_requests = MagicMock()
    mock_requests.get.side_effect = side_effect
    mock_requests.exceptions.RequestException = Exception
    return mock_requests


def _checker_warnings(caplog):
    return [
        record
        for record in caplog.records
        if record.name == "vocalinux.utils.update_checker" and record.levelno >= logging.WARNING
    ]

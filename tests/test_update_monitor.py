"""Tests for the background GitHub update monitor."""

from unittest.mock import MagicMock, patch

from vocalinux.utils.update_checker import ReleaseInfo
from vocalinux.utils.update_monitor import UpdateMonitor


def _release(tag: str = "v0.99.0") -> ReleaseInfo:
    return ReleaseInfo(
        tag_name=tag,
        version=tag.lstrip("v"),
        name=tag,
        html_url=f"https://github.com/VocaHQ/vocalinux/releases/tag/{tag}",
        body="Notes",
        published_at="2026-08-06T00:00:00Z",
        prerelease=False,
        channel="stable",
    )


class TestUpdateMonitor:
    def test_start_is_idempotent(self):
        monitor = UpdateMonitor(
            get_channel=lambda: "stable",
            on_result=MagicMock(),
            use_glib=False,
        )
        monitor.start()
        monitor.start()
        assert monitor._running
        monitor.stop()
        assert not monitor._running

    def test_reports_available_update(self):
        on_result = MagicMock()
        release = _release("v0.99.0")
        monitor = UpdateMonitor(get_channel=lambda: "stable", on_result=on_result, use_glib=False)
        monitor.start()

        with (
            patch(
                "vocalinux.utils.update_monitor.fetch_latest_release",
                return_value=release,
            ),
            patch("vocalinux.utils.update_monitor.__version__", "0.15.0"),
        ):
            monitor._worker("stable", "0.15.0", monitor._generation)

        on_result.assert_called_once_with(True, release)
        monitor.stop()

    def test_reports_up_to_date(self):
        on_result = MagicMock()
        release = _release("v0.15.0")
        monitor = UpdateMonitor(get_channel=lambda: "stable", on_result=on_result, use_glib=False)
        monitor.start()

        with patch(
            "vocalinux.utils.update_monitor.fetch_latest_release",
            return_value=release,
        ):
            monitor._worker("stable", "0.15.0", monitor._generation)

        on_result.assert_called_once_with(False, None)
        monitor.stop()

    def test_failed_fetch_keeps_prior_callback_state(self):
        on_result = MagicMock()
        release = _release("v0.99.0")
        monitor = UpdateMonitor(get_channel=lambda: "stable", on_result=on_result, use_glib=False)
        monitor.start()

        with patch(
            "vocalinux.utils.update_monitor.fetch_latest_release",
            return_value=release,
        ):
            monitor._worker("stable", "0.15.0", monitor._generation)
        on_result.reset_mock()

        with patch(
            "vocalinux.utils.update_monitor.fetch_latest_release",
            return_value=None,
        ):
            monitor._worker("stable", "0.15.0", monitor._generation)

        on_result.assert_not_called()
        monitor.stop()

    def test_stale_generation_is_ignored(self):
        on_result = MagicMock()
        monitor = UpdateMonitor(get_channel=lambda: "stable", on_result=on_result, use_glib=False)
        monitor.start()
        stale = monitor._generation
        monitor._generation += 1

        with patch(
            "vocalinux.utils.update_monitor.fetch_latest_release",
            return_value=_release(),
        ):
            monitor._worker("stable", "0.15.0", stale)

        on_result.assert_not_called()
        monitor.stop()

    def test_stale_channel_result_is_ignored_and_rechecks(self):
        """A result for an earlier channel must not update the tray."""
        on_result = MagicMock()
        channel = {"value": "stable"}
        monitor = UpdateMonitor(
            get_channel=lambda: channel["value"],
            on_result=on_result,
            use_glib=False,
        )
        monitor.start()
        generation = monitor._generation

        channel["value"] = "nightly"
        with (
            patch(
                "vocalinux.utils.update_monitor.fetch_latest_release",
                return_value=_release(),
            ) as fetch_mock,
            patch.object(monitor, "_run_check") as run_check,
        ):
            monitor._worker("stable", "0.15.0", generation)

        on_result.assert_not_called()
        run_check.assert_called_once_with()
        # Worker itself should not have re-fetched for nightly — only the
        # deferred _run_check path does that.
        fetch_mock.assert_called_once_with(channel="stable")
        monitor.stop()

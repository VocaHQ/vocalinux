"""Tests for the background GitHub update monitor."""

from unittest.mock import MagicMock, patch

import pytest

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
    def test_default_channel_follows_running_build(self) -> None:
        cases = (
            ("0.18.3", "stable", _release("v0.99.0")),
            (
                "0.18.3.dev20261019+abc1234",
                "nightly",
                _release("nightly-2026-10-20"),
            ),
        )
        for version, expected_channel, release in cases:
            on_result = MagicMock()
            monitor = UpdateMonitor(
                get_channel=None,
                on_result=on_result,
                use_glib=False,
            )
            monitor.start()
            thread_factory = MagicMock()

            def start_inline() -> None:
                call_args = thread_factory.call_args.kwargs
                call_args["target"](*call_args["args"])

            thread_factory.return_value.start.side_effect = start_inline
            with (
                patch("vocalinux.utils.update_monitor.__version__", version),
                patch(
                    "vocalinux.utils.update_monitor.fetch_latest_release",
                    return_value=release,
                ) as fetch_mock,
                patch("vocalinux.utils.update_monitor.threading.Thread", thread_factory),
            ):
                monitor._run_check()

            fetch_mock.assert_called_once_with(channel=expected_channel)
            on_result.assert_called_once_with(True, release)
            monitor.stop()

    def test_disabled_check_does_not_start_worker_or_callback(self) -> None:
        on_result = MagicMock()
        monitor = UpdateMonitor(
            get_enabled=lambda: False,
            on_result=on_result,
            use_glib=False,
        )
        monitor.start()

        with (
            patch("vocalinux.utils.update_monitor.fetch_latest_release") as fetch_mock,
            patch("vocalinux.utils.update_monitor.threading.Thread") as thread_mock,
            patch.object(monitor, "_schedule") as schedule_mock,
        ):
            monitor._run_check()

        fetch_mock.assert_not_called()
        thread_mock.assert_not_called()
        on_result.assert_not_called()
        schedule_mock.assert_called_once_with(monitor._check_interval)
        assert not monitor._check_in_progress
        monitor.stop()

    def test_disabled_after_fetch_drops_result(self) -> None:
        enabled = {"value": True}
        on_result = MagicMock()
        monitor = UpdateMonitor(
            get_enabled=lambda: enabled["value"],
            on_result=on_result,
            use_glib=False,
        )
        monitor.start()
        monitor._check_in_progress = True
        enabled["value"] = False

        with patch.object(monitor, "_schedule") as schedule_mock:
            monitor._finish_check(
                monitor._generation,
                "stable",
                callback=True,
                available=True,
                release=_release(),
            )

        on_result.assert_not_called()
        schedule_mock.assert_called_once_with(monitor._check_interval)
        assert not monitor._check_in_progress
        monitor.stop()

    def test_enabled_getter_error_defaults_to_enabled(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def broken_getter() -> bool:
            raise RuntimeError("config unavailable")

        monitor = UpdateMonitor(get_enabled=broken_getter, use_glib=False)
        monitor.start()

        with patch("vocalinux.utils.update_monitor.threading.Thread") as thread_mock:
            monitor._run_check()

        thread_mock.assert_called_once()
        thread_mock.return_value.start.assert_called_once()
        assert "Failed to read automatic update setting" in caplog.text
        assert caplog.records[0].exc_info is not None
        monitor.stop()

    def test_check_now_requires_running_and_enabled_monitor(self) -> None:
        stopped = UpdateMonitor(use_glib=False)
        with patch.object(stopped, "_run_check") as run_check:
            stopped.check_now()
        run_check.assert_not_called()

        disabled = UpdateMonitor(get_enabled=lambda: False, use_glib=False)
        disabled.start()
        with patch.object(disabled, "_run_check") as run_check:
            disabled.check_now()
        run_check.assert_not_called()
        disabled.stop()

        running = UpdateMonitor(use_glib=False)
        running.start()
        running._check_in_progress = True
        running._timeout_id = 456
        with patch.object(running, "_run_check") as run_check:
            running.check_now()
        run_check.assert_not_called()
        assert running._timeout_id == 456

        running._check_in_progress = False
        running._timeout_id = 123
        with patch.object(running, "_run_check") as run_check:
            running.check_now()
        run_check.assert_called_once_with()
        assert running._timeout_id is None
        running.stop()

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

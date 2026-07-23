#!/usr/bin/env python3
"""Focused CLI and alert-path contracts for cron_health_monitor."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import cron_health_monitor


class CronHealthMonitorTests(unittest.TestCase):
    def test_help_exits_zero_without_registry_or_network_access(self) -> None:
        registry = Mock()
        registry.exists.side_effect = AssertionError("registry accessed during --help")
        stdout = io.StringIO()

        with (
            patch.object(cron_health_monitor, "REGISTRY_FILE", registry),
            patch.object(cron_health_monitor.urllib.request, "Request") as request,
            patch.object(cron_health_monitor.urllib.request, "urlopen") as urlopen,
            redirect_stdout(stdout),
            self.assertRaises(SystemExit) as raised,
        ):
            cron_health_monitor.main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("usage:", stdout.getvalue())
        registry.exists.assert_not_called()
        request.assert_not_called()
        urlopen.assert_not_called()

    def test_dry_run_preserves_unhealthy_report_and_skips_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "cron_registry.json"
            registry.write_text(
                json.dumps(
                    [
                        {
                            "name": "missing-job",
                            "expected_interval_hours": 1,
                            "marker_file_path": "data/missing.marker",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with (
                patch.object(cron_health_monitor, "ROOT", root),
                patch.object(cron_health_monitor, "REGISTRY_FILE", registry),
                patch.object(
                    cron_health_monitor,
                    "DISCORD_WEBHOOK_URL",
                    "https://example.invalid/webhook",
                ),
                patch.object(cron_health_monitor, "DISCORD_BOT_TOKEN", ""),
                patch.object(cron_health_monitor.urllib.request, "Request") as request,
                patch.object(cron_health_monitor.urllib.request, "urlopen") as urlopen,
                redirect_stdout(stdout),
            ):
                status = cron_health_monitor.main(["--dry-run"])

        self.assertEqual(status, 1)
        self.assertIn("Cron Health Report", stdout.getvalue())
        self.assertIn("missing-job", stdout.getvalue())
        request.assert_not_called()
        urlopen.assert_not_called()

    def test_unresolved_webhook_is_unconfigured_before_request_construction(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(
                cron_health_monitor,
                "DISCORD_WEBHOOK_URL",
                "${DISCORD_PIPELINE_WEBHOOK}",
            ),
            patch.object(cron_health_monitor, "DISCORD_BOT_TOKEN", ""),
            patch.object(cron_health_monitor.urllib.request, "Request") as request,
            patch.object(cron_health_monitor.urllib.request, "urlopen") as urlopen,
            redirect_stderr(stderr),
        ):
            result = cron_health_monitor.post_to_discord("safe test")

        self.assertFalse(result)
        self.assertIn("Missing Discord webhook and bot token", stderr.getvalue())
        request.assert_not_called()
        urlopen.assert_not_called()

    def test_unresolved_webhook_preserves_valid_bot_token_fallback(self) -> None:
        request_object = object()
        with (
            patch.object(
                cron_health_monitor,
                "DISCORD_WEBHOOK_URL",
                "${DISCORD_PIPELINE_WEBHOOK}",
            ),
            patch.object(cron_health_monitor, "DISCORD_BOT_TOKEN", "valid-fake-token"),
            patch.object(
                cron_health_monitor.urllib.request,
                "Request",
                return_value=request_object,
            ) as request,
            patch.object(
                cron_health_monitor.urllib.request,
                "urlopen",
                return_value=object(),
            ) as urlopen,
        ):
            result = cron_health_monitor.post_to_discord("safe test")

        self.assertTrue(result)
        request_url, _, headers = request.call_args.args
        self.assertEqual(
            request_url,
            "https://discord.com/api/v10/channels/"
            f"{cron_health_monitor.OPERATIONS_CHANNEL}/messages",
        )
        self.assertEqual(headers["Authorization"], "Bot valid-fake-token")
        self.assertEqual(headers["User-Agent"], cron_health_monitor.DISCORD_HTTP_USER_AGENT)
        urlopen.assert_called_once_with(request_object, timeout=15)


if __name__ == "__main__":
    unittest.main()

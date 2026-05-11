import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import rss_health


class RssHealthDryRunTests(unittest.TestCase):
    def _result(self, score=rss_health.SCORE_FRESH):
        return [{
            "name": "Example Feed",
            "url": "https://example.test/rss.xml",
            "language": "fi",
            "http_status": 200,
            "http_status_normalized": 200,
            "entry_count": 1,
            "newest_date": "2026-05-11T19:00:00+00:00",
            "age_hours": 0.1,
            "score": score,
            "checked_at": "2026-05-11T19:00:00+00:00",
        }]

    def test_dry_run_does_not_write_health_unified_or_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            health = tmp / "rss-health.json"
            unified = tmp / "rss-feed-health.json"
            state = tmp / "rss-health-state.json"
            ext_state = tmp / "rss-health-extended.json"
            scanner = tmp / "scanner.py"
            original = "sentinel"
            for path in (health, unified, state, ext_state, scanner):
                path.write_text(original, encoding="utf-8")

            with mock.patch.object(rss_health, "HEALTH_FILE", health), \
                 mock.patch.object(rss_health, "UNIFIED_FEED_HEALTH_FILE", unified), \
                 mock.patch.object(rss_health, "STATE_FILE", state), \
                 mock.patch.object(rss_health, "EXTENDED_STATE_FILE", ext_state), \
                 mock.patch.object(rss_health, "SCANNER_FILE", scanner), \
                 mock.patch.object(rss_health, "check_feeds", return_value=self._result()), \
                 mock.patch.object(rss_health, "_post_discord") as post_discord:
                exit_code = rss_health.run_health_check(dry_run=True)

            self.assertEqual(exit_code, 0)
            post_discord.assert_not_called()
            for path in (health, unified, state, ext_state, scanner):
                self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_real_run_writes_health_unified_and_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            health = tmp / "rss-health.json"
            unified = tmp / "rss-feed-health.json"
            state = tmp / "rss-health-state.json"

            with mock.patch.object(rss_health, "HEALTH_FILE", health), \
                 mock.patch.object(rss_health, "UNIFIED_FEED_HEALTH_FILE", unified), \
                 mock.patch.object(rss_health, "STATE_FILE", state), \
                 mock.patch.object(rss_health, "check_feeds", return_value=self._result()), \
                 mock.patch.object(rss_health, "WEBHOOK", ""), \
                 mock.patch.object(rss_health, "_post_discord"):
                exit_code = rss_health.run_health_check(dry_run=False)

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(health.read_text(encoding="utf-8"))[0]["name"], "Example Feed")
            unified_payload = json.loads(unified.read_text(encoding="utf-8"))
            self.assertEqual(unified_payload["schema"], "uutistenlukija.rss_feed_health.v1")
            self.assertEqual(unified_payload["counts"][rss_health.SCORE_FRESH], 1)
            self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {"Example Feed": rss_health.SCORE_FRESH})


if __name__ == "__main__":
    unittest.main()

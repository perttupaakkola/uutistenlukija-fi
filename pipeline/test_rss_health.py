import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from . import rss_health
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import rss_health


class RssHealthDryRunTests(unittest.TestCase):
    def _result(self):
        return [{
            "name": "Yle Uutiset",
            "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
            "language": "fi",
            "http_status": 200,
            "http_status_normalized": 200,
            "entry_count": 1,
            "newest_date": "2026-05-11T19:00:00+00:00",
            "age_hours": 0.1,
            "score": rss_health.SCORE_FRESH,
            "checked_at": "2026-05-11T19:00:00+00:00",
        }]

    def test_dry_run_main_does_not_write_artifacts_or_state(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(rss_health, "HEALTH_FILE", Path(tmp) / "rss-health.json"), \
             mock.patch.object(rss_health, "UNIFIED_FEED_HEALTH_FILE", Path(tmp) / "rss-feed-health.json"), \
             mock.patch.object(rss_health, "STATE_FILE", Path(tmp) / "rss-health-state.json"), \
             mock.patch.object(rss_health, "EXTENDED_STATE_FILE", Path(tmp) / "rss-health-extended.json"), \
             mock.patch.object(rss_health, "check_feeds", return_value=self._result()), \
             mock.patch("sys.argv", ["rss_health.py", "--dry-run"]):
            rc = rss_health.main()
            written = list(Path(tmp).glob("*"))

        self.assertEqual(rc, 0)
        self.assertEqual(written, [])

    def test_non_dry_run_writes_artifacts_and_state(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(rss_health, "HEALTH_FILE", Path(tmp) / "rss-health.json"), \
             mock.patch.object(rss_health, "UNIFIED_FEED_HEALTH_FILE", Path(tmp) / "rss-feed-health.json"), \
             mock.patch.object(rss_health, "STATE_FILE", Path(tmp) / "rss-health-state.json"), \
             mock.patch.object(rss_health, "WEBHOOK", ""), \
             mock.patch.object(rss_health, "check_feeds", return_value=self._result()), \
             mock.patch("sys.argv", ["rss_health.py"]):
            rc = rss_health.main()
            health_file = Path(tmp) / "rss-health.json"
            unified_file = Path(tmp) / "rss-feed-health.json"
            state_file = Path(tmp) / "rss-health-state.json"

            self.assertEqual(rc, 0)
            self.assertTrue(health_file.exists())
            self.assertTrue(unified_file.exists())
            self.assertTrue(state_file.exists())
            self.assertEqual(json.loads(state_file.read_text()), {"Yle Uutiset": rss_health.SCORE_FRESH})


if __name__ == "__main__":
    unittest.main()

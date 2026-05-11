import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

try:
    from . import feed_health_report
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import feed_health_report


class FeedHealthReportCanonicalTests(unittest.TestCase):
    def test_canonical_rss_health_overrides_zero_contribution_false_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            api_path = Path(tmp) / "rss-feed-health.json"
            api_path.write_text(json.dumps({
                "generated_at": "2026-05-11T05:00:00+00:00",
                "schema": "uutistenlukija.rss_feed_health.v1",
                "counts": {"fresh": 1, "stale": 0, "dead": 0, "unreachable": 0},
                "feeds": [{
                    "name": "Yle Uutiset",
                    "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
                    "score": "fresh",
                    "checked_at": "2026-05-11T05:00:01+00:00",
                    "http_status": 200,
                    "entries": 30,
                    "newest_age_h": 0.1,
                }],
            }), encoding="utf-8")
            state_path = Path(tmp) / "feed-health-state.json"
            with mock.patch.object(feed_health_report, "RSS_HEALTH_API", api_path), \
                 mock.patch.object(feed_health_report, "RSS_HEALTH_LOG", Path(tmp) / "missing-rss-health.json"), \
                 mock.patch.object(feed_health_report, "STATE_FILE", state_path), \
                 mock.patch.object(feed_health_report, "RSS_FEEDS", [{
                     "name": "Yle Uutiset",
                     "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
                     "language": "fi",
                 }]), \
                 mock.patch.object(feed_health_report, "count_from_metrics_json", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_metrics_jsonl", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_scan_logs", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_content", return_value=Counter()):
                report = feed_health_report.build_report()

        self.assertEqual(report["summary"], {"total": 1, "healthy": 1, "stale": 0, "dead": 0, "disabled": 0})
        self.assertEqual(report["canonical_source"], feed_health_report.CANONICAL_GENERATOR)
        feed = report["feeds"][0]
        self.assertEqual(feed["status"], "healthy")
        self.assertEqual(feed["contrib_7d"], 0)
        self.assertEqual(feed["rss_score"], "fresh")
        self.assertEqual(feed["canonical_source"], feed_health_report.CANONICAL_GENERATOR)
        self.assertEqual(feed["last_success"], "2026-05-11T05:00:01+00:00")

    def test_dry_run_report_build_can_skip_state_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "feed-health-state.json"
            with mock.patch.object(feed_health_report, "RSS_HEALTH_API", Path(tmp) / "missing-api.json"), \
                 mock.patch.object(feed_health_report, "RSS_HEALTH_LOG", Path(tmp) / "missing-log.json"), \
                 mock.patch.object(feed_health_report, "STATE_FILE", state_path), \
                 mock.patch.object(feed_health_report, "RSS_FEEDS", [{
                     "name": "Yle Uutiset",
                     "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
                     "language": "fi",
                 }]), \
                 mock.patch.object(feed_health_report, "count_from_metrics_json", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_metrics_jsonl", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_scan_logs", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_content", return_value=Counter()):
                report = feed_health_report.build_report(save_state=False)

        self.assertEqual(report["summary"]["total"], 1)
        self.assertFalse(state_path.exists())

    def test_refresh_report_writes_static_facade_without_dead_alert_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "feed-health.json"
            state_path = Path(tmp) / "feed-health-state.json"
            api_path = Path(tmp) / "rss-feed-health.json"
            api_path.write_text(json.dumps({
                "generated_at": "2026-05-11T19:40:00+00:00",
                "schema": "uutistenlukija.rss_feed_health.v1",
                "counts": {"fresh": 1, "stale": 0, "dead": 0, "unreachable": 0},
                "feeds": [{
                    "name": "Yle Uutiset",
                    "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
                    "score": "fresh",
                    "checked_at": "2026-05-11T19:40:01+00:00",
                    "http_status": 200,
                    "entries": 30,
                    "newest_age_h": 0.1,
                }],
            }), encoding="utf-8")
            with mock.patch.object(feed_health_report, "RSS_HEALTH_API", api_path), \
                 mock.patch.object(feed_health_report, "RSS_HEALTH_LOG", Path(tmp) / "missing-log.json"), \
                 mock.patch.object(feed_health_report, "STATE_FILE", state_path), \
                 mock.patch.object(feed_health_report, "RSS_FEEDS", [{
                     "name": "Yle Uutiset",
                     "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET",
                     "language": "fi",
                 }]), \
                 mock.patch.object(feed_health_report, "count_from_metrics_json", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_metrics_jsonl", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_scan_logs", return_value=Counter()), \
                 mock.patch.object(feed_health_report, "count_from_content", return_value=Counter()):
                report = feed_health_report.refresh_report(out_file=out_path)

            self.assertTrue(out_path.exists())
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["canonical_generated_at"], "2026-05-11T19:40:00+00:00")
            self.assertEqual(payload["summary"]["healthy"], 1)
            self.assertEqual(report["canonical_generated_at"], payload["canonical_generated_at"])
            self.assertTrue(state_path.exists())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression tests for analytics freshness status classification."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("analytics_freshness_evidence.py")


def load_module():
    spec = importlib.util.spec_from_file_location("analytics_freshness_evidence_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AnalyticsFreshnessEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.module = load_module()
        self.module.PROJECT_DIR = self.project
        self.module.DEFAULT_OUTPUT = self.project / "analytics" / "post-reauth-freshness-evidence.json"
        self.module.DEFAULT_STATIC_OUTPUT = self.project / "static" / "api" / "analytics-freshness-status.json"
        self.module.DAILY_REPORT = self.project / "analytics" / "daily-report.json"
        self.module.SEARCH_CONSOLE_REPORT = self.project / "static" / "api" / "search-console-data.json"
        self.module.OAUTH_SENTINEL = self.project / "analytics" / "oauth-failure-sentinel.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, payload: dict, *, mtime: datetime) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        ts = mtime.timestamp()
        os.utime(path, (ts, ts))

    def write_reports(self, *, report_time: datetime, sentinel_time: datetime) -> None:
        self.write_json(
            self.module.DAILY_REPORT,
            {
                "generated_at": report_time.date().isoformat(),
                "property_id": "529369568",
                "site": "sc-domain:uutistenlukija.fi",
                "daily_pageviews": [{"date": report_time.date().isoformat(), "screenPageViews": "1"}],
                "top_pages_7d": [{"path": "/"}],
                "traffic_sources_7d": [{"source": "google"}],
                "search_console": {"top_queries": [{"query": "uutiset"}]},
            },
            mtime=report_time,
        )
        self.write_json(
            self.module.SEARCH_CONSOLE_REPORT,
            {
                "generated_at": report_time.isoformat(),
                "site": "sc-domain:uutistenlukija.fi",
                "days": 28,
                "rows": [{"keys": ["uutiset"]}],
                "row_count": 1,
            },
            mtime=report_time,
        )
        self.write_json(
            self.module.OAUTH_SENTINEL,
            {
                "status": "blocked_human_reauthorization_required",
                "checked_at": sentinel_time.isoformat(),
                "blocked_by": "OPE-133",
                "services": [{"service": "ga4", "status": "blocked_human_reauthorization_required"}],
            },
            mtime=sentinel_time,
        )

    def test_fresh_validation_supersedes_older_oauth_sentinel(self) -> None:
        sentinel_time = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc)
        report_time = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
        self.write_reports(report_time=report_time, sentinel_time=sentinel_time)

        payload = self.module.build_payload(max_age_hours=30, source_command="test")

        self.assertEqual(payload["status"], "fresh")
        self.assertIsNone(payload["blocked_by"])
        oauth = payload["artifacts"]["oauth_blocker"]
        self.assertFalse(oauth["blocked"])
        self.assertTrue(oauth["superseded_by_fresh_validation"])

    def test_newer_oauth_sentinel_still_blocks(self) -> None:
        report_time = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc)
        sentinel_time = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)
        self.write_reports(report_time=report_time, sentinel_time=sentinel_time)

        payload = self.module.build_payload(max_age_hours=30, source_command="test")

        self.assertEqual(payload["status"], "blocked_oauth_reauthorization_required")
        self.assertEqual(payload["blocked_by"], "OPE-133")
        oauth = payload["artifacts"]["oauth_blocker"]
        self.assertTrue(oauth["blocked"])
        self.assertFalse(oauth["superseded_by_fresh_validation"])


if __name__ == "__main__":
    unittest.main()

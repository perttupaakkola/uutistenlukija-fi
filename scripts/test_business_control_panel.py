#!/usr/bin/env python3
"""Regression tests for the public business control-panel JSON."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().with_name("business_control_panel.py")
spec = importlib.util.spec_from_file_location("business_control_panel", MODULE_PATH)
assert spec and spec.loader
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


class BusinessControlPanelReportingTest(unittest.TestCase):
    def test_last_24h_article_count_uses_published_content_when_scanner_metrics_are_zero(self) -> None:
        """Fresh published posts must not be reported as 0 articles in the 24h business summary."""
        now = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content_dir = root / "content" / "posts"
            log_dir = root / "pipeline" / "logs"
            content_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            for idx in range(2):
                published = now - timedelta(hours=idx + 1)
                (content_dir / f"article-{idx}.md").write_text(
                    "---\n"
                    f"title: Article {idx}\n"
                    f"date: {published.isoformat()}\n"
                    "categories:\n"
                    "  - Kotimaa\n"
                    "---\nBody\n",
                    encoding="utf-8",
                )
            (log_dir / "metrics.json").write_text(
                '[{"timestamp":"2026-05-24T11:50:00+00:00","success":true,"article_count":0,"errors":[]}]',
                encoding="utf-8",
            )
            with patch.object(panel, "PROJECT_DIR", root), patch.object(panel, "CONTENT_DIR", content_dir), patch.object(panel, "PIPELINE_DIR", root / "pipeline"), patch.object(panel, "LOG_DIR", log_dir), patch.object(panel, "QUEUE_DIR", root / "pipeline" / "queues"):
                data = panel.build_panel(now)

        self.assertEqual(data["content"]["published_last_24h_local"], 2)
        self.assertEqual(data["pipeline"]["last_24h"]["generated_article_count"], 0)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count"], 2)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count_source"], "content/posts frontmatter")

    def test_fresh_analytics_evidence_supersedes_stale_log_errors(self) -> None:
        """Fresh redacted GA4/GSC evidence must not be reported as blocked because old log tails contain errors."""
        now = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "pipeline" / "logs"
            status_path = root / "static" / "api" / "analytics-freshness-status.json"
            log_dir.mkdir(parents=True)
            status_path.parent.mkdir(parents=True)
            (log_dir / "daily-traffic-card.log").write_text("old invalid_grant error\nnewer run ok\n", encoding="utf-8")
            (log_dir / "fetch-search-console.log").write_text("old refresh failed\nnewer run got rows\n", encoding="utf-8")
            status_path.write_text(
                '{'
                '"status":"fresh",'
                '"checked_at":"2026-06-01T07:55:00+00:00",'
                '"source_command":"SECRETS_DIR=/home/pertt/.openclaw/workspace/.secrets bash pipeline/check-analytics.sh",'
                '"artifacts":{'
                '"daily_report":{"artifact":"analytics/daily-report.json","fresh":true,"property_id":"529369568","counts":{"daily_pageview_rows":1,"top_pages_7d":10,"search_console_top_queries":10}},'
                '"search_console":{"artifact":"static/api/search-console-data.json","fresh":true,"site":"sc-domain:uutistenlukija.fi","row_count":293},'
                '"oauth_blocker":{"blocked":false}'
                '}'
                '}',
                encoding="utf-8",
            )

            with patch.object(panel, "PROJECT_DIR", root), patch.object(panel, "LOG_DIR", log_dir):
                analytics = panel.analytics_status(now)

        self.assertEqual(analytics["freshness"]["status"], "fresh")
        self.assertEqual(analytics["ga4"]["status"], "fresh")
        self.assertEqual(analytics["gsc"]["status"], "fresh")
        self.assertEqual(analytics["ga4"]["reason"], "fresh GA4 validation artifact present")
        self.assertEqual(analytics["gsc"]["reason"], "fresh Search Console validation artifact present")


if __name__ == "__main__":
    unittest.main()

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from . import generate_health
except ImportError:  # pragma: no cover
    import generate_health


class GenerateHealthTests(unittest.TestCase):
    def test_published_today_prefers_recent_frontmatter_over_partial_metrics(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        post_dates = [
            now - timedelta(hours=1),
            now - timedelta(hours=2),
            now - timedelta(hours=23, minutes=59),
            now - timedelta(hours=25),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "publish-metrics.json"
            metrics_path.write_text(
                json.dumps({"ts": now.isoformat(), "published": 1}) + "\n",
                encoding="utf-8",
            )

            with patch.object(generate_health, "PUBLISH_METRICS", metrics_path):
                stats = generate_health.pipeline_stats(post_dates)

        self.assertEqual(stats["publishedToday"], 3)

    def test_published_today_uses_metrics_when_frontmatter_dates_are_unavailable(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)

        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = Path(tmp) / "publish-metrics.json"
            metrics_path.write_text(
                "\n".join(
                    [
                        json.dumps({"ts": now.isoformat(), "published": 2}),
                        json.dumps({"ts": (now - timedelta(days=1)).isoformat(), "published": 5}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(generate_health, "PUBLISH_METRICS", metrics_path):
                stats = generate_health.pipeline_stats([])

        self.assertEqual(stats["publishedToday"], 2)


if __name__ == "__main__":
    unittest.main()

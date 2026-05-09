import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import source_stats


class SourceStatsStagedPublishedTests(unittest.TestCase):
    def test_loads_staged_published_artifacts_as_source_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged_dir = Path(tmp)
            now = datetime.now(timezone.utc)
            (staged_dir / "packet.json").write_text(
                json.dumps(
                    {
                        "published_at": now.isoformat(),
                        "article": {"source": "Yle Uutiset"},
                        "packet": {"source_names": ["Should not win"]},
                    }
                ),
                encoding="utf-8",
            )
            (staged_dir / "old.json").write_text(
                json.dumps(
                    {
                        "published_at": (now - timedelta(days=10)).isoformat(),
                        "article": {"source": "Old Source"},
                    }
                ),
                encoding="utf-8",
            )

            entries = source_stats.load_staged_published_entries(days=7, staged_dir=staged_dir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["sources"], {"Yle Uutiset": 1})
            self.assertEqual(entries[0]["metric_source"], "staged_published")

            report = source_stats.compute_stats(entries, stale_days=3)
            self.assertEqual(report["total_articles"], 1)
            self.assertEqual(report["source_count"], 1)
            self.assertEqual(report["stale_count"], 0)
            self.assertEqual(report["sources"][0]["source"], "Yle Uutiset")
            self.assertIn("staged_published", report["metric_sources"])

    def test_staged_source_falls_back_to_url_host(self):
        artifact = {"packet": {"link": "https://www.kauppalehti.fi/uutiset/example"}}
        self.assertEqual(source_stats._staged_source_name(artifact), "kauppalehti.fi")


if __name__ == "__main__":
    unittest.main()

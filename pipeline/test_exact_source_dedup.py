#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from . import dedup, staged_publish
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import dedup
    import staged_publish


class FixedDateTime(datetime):
    current = datetime(2026, 7, 16, 3, 11, 20, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz else cls.current.replace(tzinfo=None)


class ExactSourceDedupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fingerprints = self.root / "published_fingerprints.json"
        self.url_hashes = self.root / "published_url_hashes.json"
        self.fingerprints.write_text("{}", encoding="utf-8")
        seen_at = (FixedDateTime.current - timedelta(days=7, minutes=2)).isoformat()
        self.url_hashes.write_text(json.dumps({"same-source-hash": seen_at}), encoding="utf-8")
        self.patches = [
            patch.object(dedup, "DEDUP_FILE", str(self.fingerprints)),
            patch.object(dedup, "URL_HASH_FILE", str(self.url_hashes)),
            patch.object(dedup, "datetime", FixedDateTime),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    @staticmethod
    def articles() -> list[dict]:
        return [
            {
                "title": "Repeated exact source",
                "fingerprint": "new-title-fingerprint",
                "_url_hash": "same-source-hash",
                "source_url": "https://example.test/same-story",
                "monica_packet_id": "duplicate-packet",
                "category": "Kotimaa",
                "content": "artikkelisana " * 220,
            },
            {
                "title": "Distinct source and facts",
                "fingerprint": "distinct-title-fingerprint",
                "_url_hash": "distinct-source-hash",
                "source_url": "https://different.test/new-facts",
                "monica_packet_id": "distinct-packet",
                "category": "Kotimaa",
                "content": "artikkelisana " * 220,
            },
        ]

    def test_seven_day_two_minute_exact_source_is_rejected_before_writing(self) -> None:
        kept = dedup.filter_new_articles(self.articles())

        self.assertEqual([article["monica_packet_id"] for article in kept], ["distinct-packet"])

    def test_publish_rechecks_exact_source_and_quarantines_duplicate(self) -> None:
        queue_root = self.root / "staged"
        outbox = queue_root / "outbox"
        failed = queue_root / "failed"
        outbox.mkdir(parents=True)
        failed.mkdir()
        items = []
        for article in self.articles():
            path = outbox / f'{article["monica_packet_id"]}.json'
            data = {
                "packet": {
                    "packet_id": article["monica_packet_id"],
                    "category": "Kotimaa",
                    "clean_source_blocks": [
                        {
                            "source": "Testi",
                            "source_url": article["source_url"],
                            "text": "lähdesana " * 220,
                        }
                    ],
                },
                "payload": {"category": "Kotimaa"},
                "article": article,
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            items.append((path, data))

        gate = SimpleNamespace(passed=[data["article"] for _, data in items], rejected=[])
        args = SimpleNamespace(max_articles=2, dedup_window=48, dry_run=False, git_push=False)
        with patch.object(staged_publish, "STAGED_ROOT", queue_root), \
             patch.object(staged_publish, "load_outbox", return_value=items), \
             patch.object(staged_publish, "run_quality_gate", return_value=gate), \
             patch.object(staged_publish, "filter_new_articles", side_effect=dedup.filter_new_articles), \
             patch.object(staged_publish, "check_published_duplicates", side_effect=lambda articles, window_hours: articles), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
             patch.object(staged_publish, "enrich_images_for_articles", return_value={"images": 0, "total": 1}), \
             patch.object(staged_publish, "publish_articles", return_value=[]):
            result = staged_publish.cmd_publish(args)

        self.assertEqual(result, 0)
        self.assertTrue((failed / "duplicate-packet.json").is_file())
        self.assertTrue((outbox / "distinct-packet.json").is_file())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

try:
    from . import staged_publish
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import staged_publish


def _record(title: str, source_words: int, blocks: int = 1) -> dict:
    research = "\n\n".join(f"[Lähde: Testi]\n{'sana ' * max(1, source_words // max(1, blocks))}" for _ in range(blocks))
    return {
        "schema": "uutistenlukija.staged_packet.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "digest": title[:10],
        "packet": {
            "packet_id": title,
            "headline_seed": title,
            "source_text": research,
            "category_hint": "Kotimaa",
        },
        "original_article": {
            "title": title,
            "description": "kuvaus",
            "research": research,
            "category_hint": "Kotimaa",
        },
    }


class StagedPublishMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for box in ["ready", "writing", "outbox", "published", "failed"]:
            (self.root / box).mkdir(parents=True, exist_ok=True)
        self.patch = patch.object(staged_publish, "STAGED_ROOT", self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _write(self, box: str, name: str, data: dict, age_hours: float = 0) -> Path:
        path = self.root / box / f"{name}.json"
        created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        data = {**data, "created_at": created.isoformat()}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        ts = created.timestamp()
        path.touch()
        import os
        os.utime(path, (ts, ts))
        return path

    def test_failure_reason_normalization(self) -> None:
        self.assertEqual(staged_publish.normalize_failure_reason("content too short: 233 words"), "content_too_short")
        self.assertEqual(staged_publish.normalize_failure_reason("Lähdeaineisto on liian niukka"), "insufficient_confidence")
        self.assertEqual(staged_publish.normalize_failure_reason("Context overflow from Monica"), "writer_runtime")
        self.assertEqual(staged_publish.normalize_failure_reason("quality gate unsourced_numbers"), "quality_gate")
        self.assertEqual(staged_publish.normalize_failure_reason("duplicate article"), "duplicate")

    def test_verbose_status_contains_age_source_and_failure_buckets(self) -> None:
        self._write("ready", "old-rich", _record("old-rich", source_words=360, blocks=2), age_hours=12)
        self._write("ready", "new-thin", _record("new-thin", source_words=40, blocks=1), age_hours=1)
        self._write("failed", "short", {**_record("short", 100), "failure": "content too short: 220 words"}, age_hours=2)
        self._write("failed", "runtime", {**_record("runtime", 200), "failure": "timed out"}, age_hours=3)

        now = datetime.now(timezone.utc)
        ready_status = staged_publish.queue_box_status("ready", list((self.root / "ready").glob("*.json")), now)
        failed_status = staged_publish.queue_box_status("failed", list((self.root / "failed").glob("*.json")), now)

        self.assertEqual(ready_status["count"], 2)
        self.assertGreaterEqual(ready_status["oldest_age_hours"], 11.9)
        self.assertIn("source_words_median", ready_status)
        self.assertEqual(failed_status["failure_reason_buckets"]["content_too_short"], 1)
        self.assertEqual(failed_status["failure_reason_buckets"]["writer_runtime"], 1)

    def test_priority_prefers_promising_packet_over_old_thin_fifo(self) -> None:
        thin_old = self._write("ready", "thin-old", _record("thin-old", source_words=45, blocks=1), age_hours=30)
        rich_newer = self._write("ready", "rich-newer", _record("rich-newer", source_words=420, blocks=3), age_hours=10)

        ordered = staged_publish.prioritized_ready_packets()

        self.assertEqual(ordered[0], rich_newer)
        self.assertIn(thin_old, ordered)

    def test_ready_sample_is_dry_run_metadata_only(self) -> None:
        path = self._write("ready", "sample", _record("sample", source_words=250, blocks=2), age_hours=5)

        sample = staged_publish.ready_sample(path)

        self.assertEqual(sample["file"], "sample.json")
        self.assertEqual(sample["packet_id"], "sample")
        self.assertGreater(sample["priority_score"], 0)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()

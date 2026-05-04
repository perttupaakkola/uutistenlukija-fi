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
        self.assertEqual(staged_publish.normalize_failure_reason("stale_low_confidence_expired age_h=120.0"), "stale_low_confidence_expired")
        self.assertEqual(staged_publish.normalize_failure_reason("stale_ready_expired age_h=10.1 max_age_h=10.0"), "stale_ready_expired")

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
        self.assertEqual(failed_status["alert_summary"]["runtime_failure_total"], 2)
        self.assertEqual(failed_status["failure_alert_buckets"]["quality"], 1)
        self.assertEqual(failed_status["failure_alert_buckets"]["writer_runtime"], 1)

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

    def test_failed_status_extracts_nested_failure_reason_and_cleanup_bucket(self) -> None:
        self._write("failed", "expired", {**_record("expired", 100), "failure": {"reason": "stale_ready_expired age_h=10.1 max_age_h=10.0"}}, age_hours=12)

        failed_status = staged_publish.queue_box_status("failed", list((self.root / "failed").glob("*.json")), datetime.now(timezone.utc))

        self.assertEqual(failed_status["failure_reason_buckets"]["stale_ready_expired"], 1)
        self.assertEqual(failed_status["failure_alert_buckets"]["expected_cleanup"], 1)

    def test_cleanup_failed_queue_dry_run_matches_old_stale_ready_only(self) -> None:
        self._write("failed", "old-expired", {**_record("old-expired", 100), "failure": "stale_ready_expired age_h=40.0 max_age_h=10.0"}, age_hours=200)
        self._write("failed", "new-expired", {**_record("new-expired", 100), "failure": "stale_ready_expired age_h=10.0 max_age_h=10.0"}, age_hours=2)
        self._write("failed", "runtime", {**_record("runtime", 100), "failure": "timed out"}, age_hours=200)

        summary = staged_publish.cleanup_failed_queue(max_age_hours=168, dry_run=True)

        self.assertEqual(summary["matched"], 1)
        self.assertTrue((self.root / "failed" / "old-expired.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())

    def test_cleanup_failed_queue_deletes_old_stale_ready_only(self) -> None:
        self._write("failed", "old-expired", {**_record("old-expired", 100), "failure": "stale_ready_expired age_h=40.0 max_age_h=10.0"}, age_hours=200)
        self._write("failed", "runtime", {**_record("runtime", 100), "failure": "timed out"}, age_hours=200)

        summary = staged_publish.cleanup_failed_queue(max_age_hours=168, dry_run=False)

        self.assertEqual(summary["deleted"], 1)
        self.assertFalse((self.root / "failed" / "old-expired.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())


class StagedPublishBacklogAuditTests(unittest.TestCase):
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
        import os
        os.utime(path, (created.timestamp(), created.timestamp()))
        return path

    def test_audit_ready_dry_run_identifies_stale_low_confidence_without_moving(self) -> None:
        self._write("ready", "stale-thin", _record("stale-thin", source_words=55, blocks=1), age_hours=60)
        self._write("ready", "fresh-rich", _record("fresh-rich", source_words=420, blocks=2), age_hours=4)

        summary = staged_publish.audit_ready_backlog(dry_run=True, demote_after_hours=48, expire_after_hours=96)

        self.assertEqual(summary["scanned"], 2)
        self.assertEqual(summary["demoted"], 1)
        self.assertEqual(summary["expired"], 0)
        self.assertTrue((self.root / "ready" / "stale-thin.json").exists())
        self.assertFalse((self.root / "failed" / "stale-thin.json").exists())

    def test_audit_ready_moves_expired_packet_to_failed_with_reason(self) -> None:
        self._write("ready", "expired-thin", _record("expired-thin", source_words=55, blocks=1), age_hours=120)

        summary = staged_publish.audit_ready_backlog(dry_run=False, demote_after_hours=48, expire_after_hours=96)

        self.assertEqual(summary["expired"], 1)
        self.assertFalse((self.root / "ready" / "expired-thin.json").exists())
        failed = json.loads((self.root / "failed" / "expired-thin.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["backlog_audit_action"], "expire")
        self.assertIn("stale_low_confidence_expired", failed["failure"])

    def test_status_reports_ready_audit_candidates(self) -> None:
        self._write("ready", "stale-thin", _record("stale-thin", source_words=55, blocks=1), age_hours=60)
        self._write("ready", "fresh-rich", _record("fresh-rich", source_words=420, blocks=2), age_hours=4)

        status = staged_publish.queue_box_status("ready", list((self.root / "ready").glob("*.json")), datetime.now(timezone.utc))

        self.assertEqual(status["audit"]["stale_low_confidence"], 1)
        self.assertEqual(status["audit"]["demote_candidates_48h"], 1)
        self.assertEqual(status["audit"]["expire_candidates_96h"], 0)


class StagedPublishFailedHygieneTests(unittest.TestCase):
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

    def _write_failed(self, name: str, failure: str, age_hours: float) -> Path:
        path = self.root / "failed" / f"{name}.json"
        created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        data = {**_record(name, 100), "failed_at": created.isoformat(), "failure": failure}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        import os
        os.utime(path, (created.timestamp(), created.timestamp()))
        return path

    def test_failed_alert_summary_separates_intentional_cleanup_from_runtime(self) -> None:
        summary = staged_publish.failed_runtime_alert_summary({
            "stale_ready_expired": 10,
            "content_too_short": 2,
            "writer_runtime": 1,
        })

        self.assertEqual(summary["intentional_cleanup_total"], 10)
        self.assertEqual(summary["runtime_failure_total"], 3)
        self.assertEqual(summary["runtime_failure_buckets"], {"content_too_short": 2, "writer_runtime": 1})

    def test_prune_failed_dry_run_keeps_recent_bucket_and_reports_old_excess(self) -> None:
        self._write_failed("old-a", "stale_ready_expired age_h=240 max_age_h=10", age_hours=240)
        self._write_failed("old-b", "stale_ready_expired age_h=230 max_age_h=10", age_hours=230)
        self._write_failed("runtime", "timed out", age_hours=240)

        summary = staged_publish.prune_failed_backlog(dry_run=True, keep_days=7, keep_recent=1)

        self.assertEqual(summary["pruned"], 1)
        self.assertEqual(summary["kept"], 2)
        self.assertTrue((self.root / "failed" / "old-a.json").exists())
        self.assertTrue((self.root / "failed" / "old-b.json").exists())
        self.assertTrue((self.root / "failed" / "runtime.json").exists())

    def test_prune_failed_non_dry_removes_only_old_excess_bucket(self) -> None:
        self._write_failed("old-a", "stale_ready_expired age_h=240 max_age_h=10", age_hours=240)
        self._write_failed("old-b", "stale_ready_expired age_h=230 max_age_h=10", age_hours=230)
        self._write_failed("runtime", "timed out", age_hours=240)

        summary = staged_publish.prune_failed_backlog(dry_run=False, keep_days=7, keep_recent=1)

        self.assertEqual(summary["pruned"], 1)
        self.assertEqual(len(list((self.root / "failed").glob("*.json"))), 2)
        self.assertTrue((self.root / "failed" / "runtime.json").exists())


if __name__ == "__main__":
    unittest.main()


class RssSourcePolicyTests(unittest.TestCase):
    def test_scanner_policy_skips_dead_and_unreachable_feeds(self) -> None:
        from pipeline import scanner
        policy = {"AP News": {"policy": "disable_or_replace", "reason": "http_403_or_known_block"}}
        allowed, reason = scanner._scanner_policy_allows_feed({"name": "AP News"}, policy)
        self.assertFalse(allowed)
        self.assertEqual(reason, "http_403_or_known_block")

    def test_scanner_policy_marks_stale_articles_not_fresh_quota_eligible(self) -> None:
        from pipeline import scanner
        article = {"source": "Yle Tiede"}
        scanner._apply_source_policy_metadata(article, {"Yle Tiede": {"policy": "stale_source", "fresh_quota_eligible": False}})
        self.assertEqual(article["source_policy"], "stale_source")
        self.assertFalse(article["fresh_source_quota_eligible"])
        self.assertTrue(article["stale_source"])

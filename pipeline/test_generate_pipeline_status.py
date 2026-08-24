#!/usr/bin/env python3
"""Focused contracts for the staged queue runway status."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pipeline import dashboard, generate_pipeline_status


def _words(count: int, prefix: str) -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _outbox_record(action: str, index: int) -> dict:
    if action not in {"publish", "monica_review", "reject"}:
        raise ValueError(f"unsupported fixture action: {action}")
    source_words = 100 if action == "monica_review" else 220
    packet_category = "Kotimaa" if action == "reject" else "Ulkomaat"
    source_url = f"https://example.test/story-{index}"
    return {
        "packet": {
            "packet_id": f"packet-{index}",
            "category": packet_category,
            "clean_source_blocks": [
                {
                    "source": "Example News",
                    "source_url": source_url,
                    "source_domain": "example.test",
                    "text": _words(source_words, f"source{index}-"),
                    "word_count": source_words,
                }
            ],
        },
        "payload": {"category": "Ulkomaat"},
        "article": {
            "title": f"Testiuutinen {index}",
            "category": "Ulkomaat",
            "content": _words(220, f"article{index}-"),
            "source_url": source_url,
        },
    }


class StagedQueueRunwayTests(unittest.TestCase):
    def build_fixture(
        self,
        root: Path,
        *,
        outbox_count: int,
        publisher_enabled: bool,
        scanner_enabled: bool,
        worker_enabled: bool = False,
        ready_count: int = 0,
        writing_count: int = 0,
        outbox_actions: list[str] | None = None,
    ) -> None:
        ready = root / "pipeline/queues/staged/ready"
        writing = root / "pipeline/queues/staged/writing"
        outbox = root / "pipeline/queues/staged/outbox"
        ready.mkdir(parents=True)
        writing.mkdir(parents=True)
        outbox.mkdir(parents=True)
        for index in range(ready_count):
            (ready / f"{index:03d}.json").write_text("{}", encoding="utf-8")
        for index in range(writing_count):
            (writing / f"{index:03d}.json").write_text("{}", encoding="utf-8")
        actions = outbox_actions or ["publish"] * outbox_count
        if len(actions) != outbox_count:
            raise ValueError("outbox_actions must match outbox_count")
        for index, action in enumerate(actions):
            (outbox / f"{index:03d}.json").write_text(
                json.dumps(_outbox_record(action, index)),
                encoding="utf-8",
            )
        if publisher_enabled:
            (root / "pipeline/actions-publish.enabled").touch()
        if scanner_enabled:
            (root / "pipeline/actions-scan.enabled").touch()
        if worker_enabled:
            (root / "pipeline/monica-worker.enabled").touch()

    def test_publisher_without_scanner_uses_exact_boundaries_and_ceiling(self) -> None:
        cases = (
            (0, "critical", 0),
            (6, "critical", 2),
            (7, "warning", 3),
            (12, "warning", 4),
            (13, "ok", 5),
        )
        for outbox_count, severity, remaining_cycles in cases:
            with self.subTest(outbox_count=outbox_count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.build_fixture(
                    root,
                    outbox_count=outbox_count,
                    publisher_enabled=True,
                    scanner_enabled=False,
                )

                runway = generate_pipeline_status.build_staged_queue_runway(root)

                self.assertEqual(runway["readyCount"], 0)
                self.assertEqual(runway["writingCount"], 0)
                self.assertEqual(runway["outboxCount"], outbox_count)
                self.assertTrue(runway["publisherEnabled"])
                self.assertFalse(runway["scannerEnabled"])
                self.assertFalse(runway["workerEnabled"])
                self.assertEqual(runway["maxPacketsPerCycle"], 3)
                self.assertEqual(runway["rawOutboxRemainingCycles"], remaining_cycles)
                self.assertEqual(runway["publishableRemainingCycles"], remaining_cycles)
                self.assertEqual(runway["worstCaseRemainingCycles"], remaining_cycles)
                self.assertEqual(runway["replenishmentState"], "disabled")
                self.assertEqual(runway["severity"], severity)
                self.assertEqual(
                    runway["reasons"],
                    [
                        "publisher_enabled",
                        "scanner_disabled",
                        "worker_disabled",
                        f"eligible_supply_{severity}",
                    ],
                )

    def test_partial_cycle_counts_round_up(self) -> None:
        for outbox_count, remaining_cycles in ((1, 1), (4, 2), (8, 3)):
            with self.subTest(outbox_count=outbox_count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.build_fixture(
                    root,
                    outbox_count=outbox_count,
                    publisher_enabled=True,
                    scanner_enabled=False,
                )
                runway = generate_pipeline_status.build_staged_queue_runway(root)
                self.assertEqual(runway["worstCaseRemainingCycles"], remaining_cycles)

    def test_marker_combinations_fail_closed_without_complete_replenishment(self) -> None:
        cases = (
            (False, False, False, "inactive", "disabled", []),
            (
                False,
                True,
                False,
                "inactive",
                "scanner_enabled_writer_unverified",
                ["writer_unverified"],
            ),
            (
                True,
                True,
                False,
                "critical",
                "scanner_enabled_writer_unverified",
                ["writer_unverified", "eligible_supply_critical"],
            ),
            (
                True,
                False,
                True,
                "critical",
                "worker_enabled_scanner_disabled",
                ["scanner_replenishment_disabled", "eligible_supply_critical"],
            ),
            (
                False,
                True,
                True,
                "inactive",
                "scanner_worker_enabled_publisher_disabled",
                ["publisher_delivery_disabled"],
            ),
        )
        for (
            publisher_enabled,
            scanner_enabled,
            worker_enabled,
            severity,
            replenishment,
            extra_reasons,
        ) in cases:
            with (
                self.subTest(
                    publisher_enabled=publisher_enabled,
                    scanner_enabled=scanner_enabled,
                    worker_enabled=worker_enabled,
                ),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                self.build_fixture(
                    root,
                    outbox_count=0,
                    publisher_enabled=publisher_enabled,
                    scanner_enabled=scanner_enabled,
                    worker_enabled=worker_enabled,
                )
                runway = generate_pipeline_status.build_staged_queue_runway(root)
                self.assertEqual(runway["severity"], severity)
                self.assertEqual(runway["replenishmentState"], replenishment)
                self.assertEqual(
                    runway["reasons"],
                    [
                        "publisher_enabled" if publisher_enabled else "publisher_disabled",
                        "scanner_enabled" if scanner_enabled else "scanner_disabled",
                        "worker_enabled" if worker_enabled else "worker_disabled",
                        *extra_reasons,
                    ],
                )

    def test_scanner_without_worker_marker_remains_critical_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_fixture(
                root,
                outbox_count=0,
                publisher_enabled=True,
                scanner_enabled=True,
            )
            runway = generate_pipeline_status.build_staged_queue_runway(root)

            self.assertEqual(runway["outboxCount"], 0)
            self.assertEqual(runway["publishEligibleCount"], 0)
            self.assertEqual(runway["monicaReviewCount"], 0)
            self.assertEqual(runway["rejectCount"], 0)
            self.assertEqual(runway["rawOutboxRemainingCycles"], 0)
            self.assertEqual(runway["publishableRemainingCycles"], 0)
            self.assertEqual(runway["worstCaseRemainingCycles"], 0)
            self.assertEqual(
                runway["replenishmentState"],
                "scanner_enabled_writer_unverified",
            )
            self.assertEqual(runway["severity"], "critical")
            self.assertEqual(
                runway["reasons"],
                [
                    "publisher_enabled",
                    "scanner_enabled",
                    "worker_disabled",
                    "writer_unverified",
                    "eligible_supply_critical",
                ],
            )

            summary = root / "summary.md"
            output = io.StringIO()
            with redirect_stdout(output):
                generate_pipeline_status.write_actions_summary(runway, summary)

            rendered = summary.read_text(encoding="utf-8")
            self.assertIn("## Staged queue runway", rendered)
            self.assertIn("| Ready packets | 0 |", rendered)
            self.assertIn("| Writing packets | 0 |", rendered)
            self.assertIn("| Raw outbox cycles | 0 |", rendered)
            self.assertIn("| Publishable remaining cycles | 0 |", rendered)
            self.assertIn("| Monica worker marker | disabled |", rendered)
            self.assertIn(
                "| Replenishment | scanner_enabled_writer_unverified |",
                rendered,
            )
            self.assertNotIn("hour", rendered.lower())
            self.assertIn("::warning title=Staged queue runway critical::", output.getvalue())
            self.assertNotIn("::error", output.getvalue())

    def test_all_markers_make_an_idle_caught_up_queue_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_fixture(
                root,
                outbox_count=0,
                publisher_enabled=True,
                scanner_enabled=True,
                worker_enabled=True,
            )

            runway = generate_pipeline_status.build_staged_queue_runway(root)

            self.assertEqual(runway["replenishmentState"], "end_to_end_enabled")
            self.assertEqual(runway["severity"], "ok")
            self.assertEqual(
                runway["reasons"],
                ["publisher_enabled", "scanner_enabled", "worker_enabled", "queue_idle"],
            )

    def test_all_markers_report_nonempty_queue_as_active_and_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_fixture(
                root,
                outbox_count=1,
                publisher_enabled=True,
                scanner_enabled=True,
                worker_enabled=True,
                ready_count=1,
                writing_count=1,
            )

            runway = generate_pipeline_status.build_staged_queue_runway(root)

            self.assertEqual(runway["readyCount"], 1)
            self.assertEqual(runway["writingCount"], 1)
            self.assertEqual(runway["outboxCount"], 1)
            self.assertEqual(runway["severity"], "ok")
            self.assertIn("queue_active", runway["reasons"])

    def test_zero_eligible_is_critical_without_recent_natural_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_fixture(
                root,
                outbox_count=35,
                outbox_actions=["monica_review"] * 16 + ["reject"] * 19,
                publisher_enabled=True,
                scanner_enabled=True,
                worker_enabled=True,
            )

            runway = generate_pipeline_status.build_staged_queue_runway(root)

            self.assertEqual(runway["outboxCount"], 35)
            self.assertEqual(runway["publishEligibleCount"], 0)
            self.assertEqual(runway["monicaReviewCount"], 16)
            self.assertEqual(runway["rejectCount"], 19)
            self.assertEqual(runway["rawOutboxRemainingCycles"], 12)
            self.assertEqual(runway["publishableRemainingCycles"], 0)
            self.assertEqual(runway["worstCaseRemainingCycles"], 0)
            self.assertEqual(runway["severity"], "critical")
            self.assertEqual(runway["recentPublishedPackets"], 0)
            self.assertIn("eligible_supply_stalled", runway["reasons"])

    def test_zero_eligible_is_post_drain_after_two_recent_natural_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_fixture(
                root,
                outbox_count=35,
                outbox_actions=["monica_review"] * 16 + ["reject"] * 19,
                publisher_enabled=True,
                scanner_enabled=True,
                worker_enabled=True,
            )

            runway = generate_pipeline_status.build_staged_queue_runway(
                root,
                recent_published_packets=2,
            )

            self.assertEqual(runway["publishEligibleCount"], 0)
            self.assertEqual(runway["recentPublishedPackets"], 2)
            self.assertEqual(runway["severity"], "ok")
            self.assertIn("eligible_supply_post_drain", runway["reasons"])
            for action, expected in (
                ("publish", 0),
                ("monica_review", 16),
                ("reject", 19),
            ):
                self.assertEqual(
                    sum(runway["preflightPrimaryReasonBuckets"][action].values()),
                    expected,
                )

    def test_multiple_writing_packets_are_always_critical(self) -> None:
        for publisher_enabled in (False, True):
            for scanner_enabled in (False, True):
                for worker_enabled in (False, True):
                    with (
                        self.subTest(
                            publisher_enabled=publisher_enabled,
                            scanner_enabled=scanner_enabled,
                            worker_enabled=worker_enabled,
                        ),
                        tempfile.TemporaryDirectory() as tmp,
                    ):
                        root = Path(tmp)
                        self.build_fixture(
                            root,
                            outbox_count=0,
                            publisher_enabled=publisher_enabled,
                            scanner_enabled=scanner_enabled,
                            worker_enabled=worker_enabled,
                            writing_count=2,
                        )

                        runway = generate_pipeline_status.build_staged_queue_runway(root)

                        self.assertEqual(runway["writingCount"], 2)
                        self.assertEqual(runway["severity"], "critical")
                        self.assertIn("multiple_writing_packets", runway["reasons"])

    def test_main_adds_runway_to_the_canonical_status_json(self) -> None:
        runway = {
            "readyCount": 0,
            "writingCount": 0,
            "outboxCount": 13,
            "publishEligibleCount": 13,
            "monicaReviewCount": 0,
            "rejectCount": 0,
            "preflightPrimaryReasonBuckets": {},
            "preflightReasonBuckets": {},
            "publisherEnabled": True,
            "scannerEnabled": False,
            "workerEnabled": False,
            "maxPacketsPerCycle": 3,
            "rawOutboxRemainingCycles": 5,
            "publishableRemainingCycles": 5,
            "worstCaseRemainingCycles": 5,
            "replenishmentState": "disabled",
            "severity": "ok",
            "reasons": [
                "publisher_enabled",
                "scanner_disabled",
                "worker_disabled",
                "eligible_supply_ok",
            ],
        }
        fake_dashboard = types.ModuleType("dashboard")
        fake_dashboard.build_dashboard = lambda hours, actions_cycle_path=None: {
            "hours": hours,
            "articles": {"published": 0},
            "runs": {"total": 0},
        }
        fake_dashboard.recent_post_dates = lambda hours: []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "static/api/pipeline-status.json"
            with (
                patch.dict(sys.modules, {"dashboard": fake_dashboard}),
                patch.object(generate_pipeline_status, "PROJECT_DIR", root),
                patch.object(generate_pipeline_status, "OUT_FILE", output),
                patch.object(
                    generate_pipeline_status,
                    "build_staged_queue_runway",
                    return_value=runway,
                ),
            ):
                generate_pipeline_status.main([])

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["stagedQueueRunway"], runway)

    def test_main_keeps_rolling_article_truth_separate_from_latest_publish_cycle(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        published_dates = [now - timedelta(hours=hours) for hours in (3, 2, 1)]
        cycle = {
            "schema": dashboard.PUBLISH_CYCLE_SCHEMA,
            "cycle_id": "github:536:1",
            "ts": now.isoformat(),
            "admitted": True,
            "outcome": "ok",
            "result": "published",
            "attempted": 1,
            "published": 1,
            "supply": {
                "raw_outbox": 3,
                "action_counts": {
                    "publish": 1,
                    "monica_review": 1,
                    "reject": 1,
                },
            },
        }
        runway = {"severity": "critical", "publishableRemainingCycles": 0}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_dir = root / "pipeline"
            pipeline_dir.mkdir()
            posts_dir = root / "content/posts"
            posts_dir.mkdir(parents=True)
            for index, published_at in enumerate(published_dates):
                (posts_dir / f"article-{index}.md").write_text(
                    "---\n"
                    f"title: Article {index}\n"
                    f"date: {published_at.isoformat()}\n"
                    "---\nBody\n",
                    encoding="utf-8",
                )
            outcome = root / "runner/staged-publish-cycle.json"
            outcome.parent.mkdir()
            outcome.write_text(json.dumps(cycle), encoding="utf-8")
            output = root / "static/api/pipeline-status.json"
            with (
                patch.dict(sys.modules, {"dashboard": dashboard}),
                patch.object(dashboard, "SCRIPT_DIR", pipeline_dir),
                patch.object(dashboard, "REPO_ROOT", root),
                patch.object(generate_pipeline_status, "PROJECT_DIR", root),
                patch.object(generate_pipeline_status, "OUT_FILE", output),
                patch.object(
                    generate_pipeline_status,
                    "build_staged_queue_runway",
                    return_value=runway,
                ),
            ):
                generate_pipeline_status.main(["--cycle-outcome", str(outcome)])

            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["articles"]["published"], len(published_dates))
        self.assertEqual(
            data["articles"]["last_published_ts"],
            published_dates[-1].isoformat(),
        )
        self.assertEqual(
            data["articles"]["production_truth_scope"],
            "rolling_24h_published_content",
        )
        self.assertEqual(
            data["stagedPublishCycles"]["scope"],
            "observed_cycle_records",
        )
        self.assertEqual(data["stagedPublishCycles"]["latest"]["published"], 1)

    def test_main_consumes_actions_cycle_without_local_metrics_log(self) -> None:
        runway = {
            "readyCount": 0,
            "writingCount": 0,
            "outboxCount": 2,
            "publishEligibleCount": 0,
            "monicaReviewCount": 1,
            "rejectCount": 1,
            "preflightPrimaryReasonBuckets": {},
            "preflightReasonBuckets": {},
            "publisherEnabled": True,
            "scannerEnabled": True,
            "workerEnabled": True,
            "maxPacketsPerCycle": 3,
            "rawOutboxRemainingCycles": 1,
            "publishableRemainingCycles": 0,
            "worstCaseRemainingCycles": 0,
            "replenishmentState": "end_to_end_enabled",
            "severity": "critical",
            "reasons": [
                "publisher_enabled",
                "scanner_enabled",
                "worker_enabled",
                "queue_active",
                "eligible_supply_empty",
            ],
        }
        cycle = {
            "schema": dashboard.PUBLISH_CYCLE_SCHEMA,
            "cycle_id": "github:123:1",
            "ts": datetime.now(timezone.utc).isoformat(),
            "admitted": True,
            "outcome": "skip",
            "result": "no_publish_eligible_supply",
            "attempted": 0,
            "published": 0,
            "supply": {
                "raw_outbox": 2,
                "action_counts": {
                    "publish": 0,
                    "monica_review": 1,
                    "reject": 1,
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline_dir = root / "pipeline"
            pipeline_dir.mkdir()
            outcome = root / "runner/staged-publish-cycle.json"
            outcome.parent.mkdir()
            outcome.write_text(json.dumps(cycle), encoding="utf-8")
            output = root / "static/api/pipeline-status.json"
            self.assertFalse((pipeline_dir / "logs/publish-metrics.json").exists())
            with (
                patch.dict(sys.modules, {"dashboard": dashboard}),
                patch.object(dashboard, "SCRIPT_DIR", pipeline_dir),
                patch.object(dashboard, "REPO_ROOT", root),
                patch.object(generate_pipeline_status, "PROJECT_DIR", root),
                patch.object(generate_pipeline_status, "OUT_FILE", output),
                patch.object(
                    generate_pipeline_status,
                    "build_staged_queue_runway",
                    return_value=runway,
                ),
            ):
                generate_pipeline_status.main(["--cycle-outcome", str(outcome)])

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["runs"]["total"], 1)
            self.assertEqual(data["runs"]["admitted"], 1)
            self.assertEqual(data["stagedPublishCycles"]["total"], 1)
            self.assertEqual(data["stagedPublishCycles"]["monicaReview"], 1)
            self.assertEqual(data["stagedPublishCycles"]["reject"], 1)
            self.assertEqual(
                data["stagedPublishCycles"]["latest"]["cycleId"],
                "github:123:1",
            )


if __name__ == "__main__":
    unittest.main()

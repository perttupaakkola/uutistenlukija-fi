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
from pathlib import Path
from unittest.mock import patch

from pipeline import generate_pipeline_status


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
        for index in range(outbox_count):
            (outbox / f"{index:03d}.json").write_text("{}", encoding="utf-8")
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
                self.assertEqual(runway["worstCaseRemainingCycles"], remaining_cycles)
                self.assertEqual(runway["replenishmentState"], "disabled")
                self.assertEqual(runway["severity"], severity)
                self.assertEqual(
                    runway["reasons"],
                    [
                        "publisher_enabled",
                        "scanner_disabled",
                        "worker_disabled",
                        f"outbox_{severity}",
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
                ["writer_unverified", "outbox_critical"],
            ),
            (
                True,
                False,
                True,
                "critical",
                "worker_enabled_scanner_disabled",
                ["scanner_replenishment_disabled", "outbox_critical"],
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

            self.assertEqual(
                runway,
                {
                    "readyCount": 0,
                    "writingCount": 0,
                    "outboxCount": 0,
                    "publisherEnabled": True,
                    "scannerEnabled": True,
                    "workerEnabled": False,
                    "maxPacketsPerCycle": 3,
                    "worstCaseRemainingCycles": 0,
                    "replenishmentState": "scanner_enabled_writer_unverified",
                    "severity": "critical",
                    "reasons": [
                        "publisher_enabled",
                        "scanner_enabled",
                        "worker_disabled",
                        "writer_unverified",
                        "outbox_critical",
                    ],
                },
            )

            summary = root / "summary.md"
            output = io.StringIO()
            with redirect_stdout(output):
                generate_pipeline_status.write_actions_summary(runway, summary)

            rendered = summary.read_text(encoding="utf-8")
            self.assertIn("## Staged queue runway", rendered)
            self.assertIn("| Ready packets | 0 |", rendered)
            self.assertIn("| Writing packets | 0 |", rendered)
            self.assertIn("| Worst-case remaining cycles | 0 |", rendered)
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
            "publisherEnabled": True,
            "scannerEnabled": False,
            "workerEnabled": False,
            "maxPacketsPerCycle": 3,
            "worstCaseRemainingCycles": 5,
            "replenishmentState": "disabled",
            "severity": "ok",
            "reasons": [
                "publisher_enabled",
                "scanner_disabled",
                "worker_disabled",
                "outbox_ok",
            ],
        }
        fake_dashboard = types.ModuleType("dashboard")
        fake_dashboard.build_dashboard = lambda hours: {
            "hours": hours,
            "articles": {"published": 0},
            "runs": {"total": 0},
        }
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


if __name__ == "__main__":
    unittest.main()

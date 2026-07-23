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
    ) -> None:
        outbox = root / "pipeline/queues/staged/outbox"
        outbox.mkdir(parents=True)
        for index in range(outbox_count):
            (outbox / f"{index:03d}.json").write_text("{}", encoding="utf-8")
        if publisher_enabled:
            (root / "pipeline/actions-publish.enabled").touch()
        if scanner_enabled:
            (root / "pipeline/actions-scan.enabled").touch()

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

                self.assertEqual(runway["outboxCount"], outbox_count)
                self.assertTrue(runway["publisherEnabled"])
                self.assertFalse(runway["scannerEnabled"])
                self.assertEqual(runway["maxPacketsPerCycle"], 3)
                self.assertEqual(runway["worstCaseRemainingCycles"], remaining_cycles)
                self.assertEqual(runway["replenishmentState"], "disabled")
                self.assertEqual(runway["severity"], severity)
                self.assertEqual(
                    runway["reasons"],
                    ["publisher_enabled", "scanner_disabled", f"outbox_{severity}"],
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

    def test_marker_combinations_fail_closed_without_a_writer_signal(self) -> None:
        cases = (
            (False, False, "inactive", "disabled", []),
            (
                False,
                True,
                "inactive",
                "scanner_enabled_writer_unverified",
                ["writer_unverified"],
            ),
            (
                True,
                True,
                "critical",
                "scanner_enabled_writer_unverified",
                ["writer_unverified", "outbox_critical"],
            ),
        )
        for (
            publisher_enabled,
            scanner_enabled,
            severity,
            replenishment,
            extra_reasons,
        ) in cases:
            with (
                self.subTest(
                    publisher_enabled=publisher_enabled,
                    scanner_enabled=scanner_enabled,
                ),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                self.build_fixture(
                    root,
                    outbox_count=0,
                    publisher_enabled=publisher_enabled,
                    scanner_enabled=scanner_enabled,
                )
                runway = generate_pipeline_status.build_staged_queue_runway(root)
                self.assertEqual(runway["severity"], severity)
                self.assertEqual(runway["replenishmentState"], replenishment)
                self.assertEqual(
                    runway["reasons"],
                    [
                        "publisher_enabled" if publisher_enabled else "publisher_disabled",
                        "scanner_enabled" if scanner_enabled else "scanner_disabled",
                        *extra_reasons,
                    ],
                )

    def test_dual_markers_with_zero_outbox_remain_critical_and_warn(self) -> None:
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
                    "outboxCount": 0,
                    "publisherEnabled": True,
                    "scannerEnabled": True,
                    "maxPacketsPerCycle": 3,
                    "worstCaseRemainingCycles": 0,
                    "replenishmentState": "scanner_enabled_writer_unverified",
                    "severity": "critical",
                    "reasons": [
                        "publisher_enabled",
                        "scanner_enabled",
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
            self.assertIn("| Worst-case remaining cycles | 0 |", rendered)
            self.assertIn(
                "| Replenishment | scanner_enabled_writer_unverified |",
                rendered,
            )
            self.assertNotIn("hour", rendered.lower())
            self.assertIn("::warning title=Staged queue runway critical::", output.getvalue())
            self.assertNotIn("::error", output.getvalue())

    def test_main_adds_runway_to_the_canonical_status_json(self) -> None:
        runway = {
            "outboxCount": 13,
            "publisherEnabled": True,
            "scannerEnabled": False,
            "maxPacketsPerCycle": 3,
            "worstCaseRemainingCycles": 5,
            "replenishmentState": "disabled",
            "severity": "ok",
            "reasons": ["publisher_enabled", "scanner_disabled", "outbox_ok"],
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

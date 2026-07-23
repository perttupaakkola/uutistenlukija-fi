#!/usr/bin/env python3
"""Static contracts for the marker-gated Actions pipeline stages."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGED_SCAN = ROOT / ".github/workflows/staged-scan.yml"
DEPLOY = ROOT / ".github/workflows/deploy.yml"
FAILURE_ALERT = ROOT / ".github/workflows/deploy-failure-alert.yml"


class StagedScanWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = STAGED_SCAN.read_text(encoding="utf-8")

    def test_schedule_marker_permissions_and_concurrency_are_fail_closed(self) -> None:
        for expected in (
            "name: Staged scan",
            'cron: "1,16,31,46 * * * *"',
            "workflow_dispatch: {}",
            "permissions:\n  contents: write",
            "group: staged-scan",
            "cancel-in-progress: false",
            "pipeline/actions-scan.enabled",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.workflow)
        self.assertNotIn("pipeline/actions-publish.enabled", self.workflow)

    def test_scanner_command_matches_the_paused_vps_contract(self) -> None:
        command = (
            "timeout --signal=TERM --kill-after=15s 240s "
            "python3 pipeline/staged_publish.py scan "
            "--max-packets 1 "
            "--max-research-candidates 8 "
            "--dedup-window 48 "
            "--max-ready-backlog 150 "
            "--max-ready-age-hours 24"
        )
        self.assertIn(command, " ".join(self.workflow.split()))
        self.assertNotIn("--cpu-load-max", self.workflow)
        self.assertNotIn("--min-disk-free-mb", self.workflow)

    def test_only_required_source_secret_and_queue_paths_are_used(self) -> None:
        self.assertIn("FIREHOSE_TOKEN: ${{ secrets.FIREHOSE_TOKEN }}", self.workflow)
        self.assertNotRegex(self.workflow, r"(?i)(api|access|firehose)[_-]?key:\s*[\"']?[A-Za-z0-9_-]{16,}")
        self.assertIn("git add -- pipeline/queues/staged", self.workflow)
        self.assertIn("git pull --rebase origin main", self.workflow)
        self.assertIn("git push origin HEAD:main", self.workflow)
        self.assertRegex(
            self.workflow,
            re.compile(
                r"git diff --cached --name-only.*pipeline/queues/staged/",
                re.DOTALL,
            ),
        )

    def test_manual_canary_requires_exactly_one_valid_ready_packet(self) -> None:
        for expected in (
            'os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"',
            "expected exactly one new ready packet",
            "uutistenlukija.staged_packet.v1",
            "packet_id",
            "source_text",
            "sha256",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.workflow)


class ScannerDeployIsolationContractTests(unittest.TestCase):
    def test_scanner_control_and_queue_pushes_do_not_trigger_pages_deploy(self) -> None:
        deploy = DEPLOY.read_text(encoding="utf-8")
        for ignored in (
            '"pipeline/actions-scan.enabled"',
            '"pipeline/queues/staged/**"',
            '"pipeline/AGENTS.md"',
            '".github/AGENTS.md"',
            '".github/workflows/staged-scan.yml"',
        ):
            with self.subTest(ignored=ignored):
                self.assertIn(ignored, deploy)

    def test_scanner_failures_are_watched(self) -> None:
        alert = FAILURE_ALERT.read_text(encoding="utf-8")
        self.assertIn("      - Staged scan", alert)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Static contracts for the marker-gated Actions pipeline stages."""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGED_SCAN = ROOT / ".github/workflows/staged-scan.yml"
STAGED_PUBLISH = ROOT / ".github/workflows/staged-publish.yml"
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
            "branches: [main]",
            '- "pipeline/actions-scan.enabled"',
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

    def test_supervised_canary_requires_exactly_one_valid_ready_packet(self) -> None:
        for expected in (
            'os.environ["GITHUB_EVENT_NAME"] in {"workflow_dispatch", "push"}',
            "supervised canary expected exactly one new ready packet",
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


class StagedPublishRunwayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = STAGED_PUBLISH.read_text(encoding="utf-8")

    def _publish_run_script(self) -> str:
        step = self.workflow.index("      - name: Publish staged outbox packets")
        run_header = "        run: |\n"
        run_start = self.workflow.index(run_header, step) + len(run_header)
        run_end = self.workflow.index("\n      - name:", run_start)
        return textwrap.dedent(self.workflow[run_start:run_end])

    def test_runway_summary_uses_the_canonical_status_producer(self) -> None:
        publish = self.workflow.index("- name: Publish staged outbox packets")
        summary = self.workflow.index("- name: Summarize staged queue runway")
        validate = self.workflow.index("- name: Validate Hugo templates")
        self.assertLess(publish, summary)
        self.assertLess(summary, validate)
        self.assertIn(
            "python3 pipeline/generate_pipeline_status.py --actions-summary",
            self.workflow,
        )

    def test_runway_cap_is_enforced_for_manual_actions_runs(self) -> None:
        self.assertIn('default: "3"', self.workflow)
        self.assertIn(
            '        type: choice\n'
            '        options:\n'
            '          - "1"\n'
            '          - "2"\n'
            '          - "3"',
            self.workflow,
        )
        self.assertIn("github.event.inputs.max_articles || '3'", self.workflow)

        script = (
            'python3() { printf "PUBLISHER_CALLED %s\\n" "$*"; }\n'
            + self._publish_run_script()
        )
        env = os.environ.copy()
        env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
        for max_articles in ("4", "24"):
            with self.subTest(max_articles=max_articles):
                env["MAX_ARTICLES"] = max_articles
                result = subprocess.run(
                    ["bash", "-c", script],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("max_articles must be 1, 2, or 3", result.stdout)
                self.assertNotIn("PUBLISHER_CALLED", result.stdout)

        for max_articles in ("1", "2", "3"):
            with self.subTest(max_articles=max_articles):
                env["MAX_ARTICLES"] = max_articles
                result = subprocess.run(
                    ["bash", "-c", script],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(
                    f"--max-articles {max_articles} --git-push",
                    result.stdout,
                )


if __name__ == "__main__":
    unittest.main()

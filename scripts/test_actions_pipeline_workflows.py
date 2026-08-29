#!/usr/bin/env python3
"""Static contracts for the marker-gated Actions pipeline stages."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
STAGED_SCAN = ROOT / ".github/workflows/staged-scan.yml"
STAGED_PUBLISH = ROOT / ".github/workflows/staged-publish.yml"
DEPLOY = ROOT / ".github/workflows/deploy.yml"
FAILURE_ALERT = ROOT / ".github/workflows/deploy-failure-alert.yml"


class StagedScanWorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = STAGED_SCAN.read_text(encoding="utf-8")

    def _run_script(self, step_name: str) -> str:
        step = self.workflow.index(f"      - name: {step_name}")
        run_header = "        run: |\n"
        run_start = self.workflow.index(run_header, step) + len(run_header)
        run_end = self.workflow.find("\n      - name:", run_start)
        if run_end == -1:
            run_end = len(self.workflow)
        return textwrap.dedent(self.workflow[run_start:run_end])

    def _embedded_python(self, step_name: str) -> str:
        script = self._run_script(step_name)
        match = re.search(
            r"python3 <<'PY'\n(?P<source>.*?)\nPY(?:\n|$)",
            script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"{step_name}: embedded Python block missing")
        return match.group("source")

    def _write_valid_ready_packet(self, root: Path, packet_id: str = "valid_packet") -> None:
        target = root / "pipeline/queues/staged/ready" / f"{packet_id}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "schema": "uutistenlukija.staged_packet.v1",
                    "packet": {
                        "packet_id": packet_id,
                        "headline_seed": "Test headline",
                        "link": "https://example.com/story",
                        "source_text": "sufficient deterministic source text",
                        "source_selection_outcome": "usable_source_packet",
                        "selected_source_provenance_error": False,
                    },
                }
            ),
            encoding="utf-8",
        )

    def _run_queue_delta_fixture(
        self,
        setup_before,
        mutate_after,
        *,
        event_name: str = "workflow_dispatch",
        event_action: str = "",
    ) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            (root / "pipeline/queues/staged/ready").mkdir(parents=True)
            setup_before(root)
            env = os.environ.copy()
            env.update(
                {
                    "RUNNER_TEMP": str(runner_temp),
                    "GITHUB_EVENT_NAME": event_name,
                    "STAGED_SCAN_EVENT_ACTION": event_action,
                    "GITHUB_STEP_SUMMARY": str(root / "summary.md"),
                }
            )
            capture = subprocess.run(
                ["python3", "-c", self._embedded_python("Capture staged queue before scan")],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
            mutate_after(root)
            return subprocess.run(
                ["python3", "-c", self._embedded_python("Verify queue delta and push")],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_schedule_marker_permissions_and_concurrency_are_fail_closed(self) -> None:
        for expected in (
            "name: Staged scan",
            'cron: "1,16,31,46 * * * *"',
            "workflow_dispatch: {}",
            "permissions:\n  contents: write",
            "group: staged-scan",
            "cancel-in-progress: false",
            "queue: max",
            "timeout-minutes: 8",
            "STAGED_SCAN_EVENT_ACTION:",
            "pipeline/actions-scan.enabled",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.workflow)
        self.assertRegex(
            self.workflow,
            re.compile(
                r"^concurrency:\n"
                r"  group: staged-scan\n"
                r"  cancel-in-progress: false\n"
                r"  queue: max$",
                re.MULTILINE,
            ),
        )
        self.assertEqual(self.workflow.count("queue: max"), 1)
        self.assertNotIn("pipeline/actions-publish.enabled", self.workflow)
        trigger_block = self.workflow[: self.workflow.index("\npermissions:")]
        self.assertRegex(
            trigger_block,
            re.compile(
                r"^  repository_dispatch:\n"
                r"    types:\n"
                r"      - staged_scan_recovery$",
                re.MULTILINE,
            ),
        )
        self.assertNotIn("\n  push:", trigger_block)
        self.assertNotIn('- "pipeline/actions-scan.enabled"', trigger_block)

    def test_manual_canary_cannot_enable_scheduled_scans(self) -> None:
        gate = self._run_script("Gate automated runs on cutover marker")
        cases = (
            ("workflow_dispatch", False, "enabled=true\nmode=canary\n"),
            ("schedule", False, "enabled=false\nmode=disabled\n"),
            ("schedule", True, "enabled=true\nmode=cutover\n"),
        )
        for event_name, marker_present, expected_output in cases:
            with self.subTest(event=event_name, marker=marker_present), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                marker = root / "pipeline/actions-scan.enabled"
                if marker_present:
                    marker.parent.mkdir(parents=True)
                    marker.touch()
                output = root / "github-output"
                env = os.environ.copy()
                env.update(
                    {
                        "GITHUB_EVENT_NAME": event_name,
                        "GITHUB_REF": "refs/heads/main",
                        "GITHUB_OUTPUT": str(output),
                    }
                )
                result = subprocess.run(
                    ["bash", "-c", gate],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output.read_text(encoding="utf-8"), expected_output)
                self.assertEqual(marker.exists(), marker_present)

    def test_recovery_dispatch_admits_only_exact_type_from_main(self) -> None:
        gate = self._run_script("Gate automated runs on cutover marker")
        cases = (
            (
                "staged_scan_recovery",
                "refs/heads/main",
                0,
                "enabled=true\nmode=canary\n",
                "",
            ),
            (
                "unexpected_recovery",
                "refs/heads/main",
                1,
                "",
                "Unsupported staged scan repository_dispatch type",
            ),
            (
                "staged_scan_recovery",
                "refs/heads/unreviewed-canary",
                1,
                "",
                "recovery canary must run from refs/heads/main",
            ),
        )
        for event_action, event_ref, expected_returncode, expected_output, expected_error in cases:
            with self.subTest(action=event_action, ref=event_ref), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "github-output"
                env = os.environ.copy()
                env.update(
                    {
                        "GITHUB_EVENT_NAME": "repository_dispatch",
                        "GITHUB_REF": event_ref,
                        "GITHUB_OUTPUT": str(output),
                        "STAGED_SCAN_EVENT_ACTION": event_action,
                    }
                )
                result = subprocess.run(
                    ["bash", "-c", gate],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                actual_output = output.read_text(encoding="utf-8") if output.exists() else ""

            self.assertEqual(result.returncode, expected_returncode, result.stdout + result.stderr)
            self.assertEqual(actual_output, expected_output)
            if expected_error:
                self.assertIn(expected_error, result.stdout + result.stderr)

    def test_manual_canary_rejects_non_main_ref_before_source_setup_or_scan(self) -> None:
        gate = self._run_script("Gate automated runs on cutover marker")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "github-output"
            env = os.environ.copy()
            env.update(
                {
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "GITHUB_REF": "refs/heads/unreviewed-canary",
                    "GITHUB_OUTPUT": str(output),
                }
            )
            result = subprocess.run(
                ["bash", "-c", gate],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            output_exists = output.exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "manual canary must run from refs/heads/main",
            result.stdout + result.stderr,
        )
        self.assertFalse(output_exists)
        gate_step = self.workflow.index(
            "      - name: Gate automated runs on cutover marker"
        )
        source_step = self.workflow.index(
            "      - name: Declare RSS-only restoration mode"
        )
        scan_step = self.workflow.index("      - name: Scan one staged packet")
        self.assertLess(gate_step, source_step)
        self.assertLess(source_step, scan_step)

    def test_scanner_command_matches_the_paused_vps_contract(self) -> None:
        command = (
            "timeout --signal=TERM --kill-after=15s 240s "
            "python3 pipeline/staged_publish.py scan "
            "--max-packets 1 "
            "--max-research-candidates 8 "
            "--min-source-words 200 "
            "--dedup-window 48 "
            "--max-ready-backlog 150 "
            "--max-ready-age-hours 24"
        )
        self.assertIn(command, " ".join(self.workflow.split()))
        self.assertNotIn("--cpu-load-max", self.workflow)
        self.assertNotIn("--min-disk-free-mb", self.workflow)

    def test_rss_only_source_mode_and_queue_paths_are_used(self) -> None:
        self.assertIn("source_mode=rss-only", self.workflow)
        self.assertNotIn("FIREHOSE_TOKEN", self.workflow)
        self.assertNotIn("secrets.", self.workflow)
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
            'manual_canary = event_name == "workflow_dispatch"',
            'event_name == "repository_dispatch"',
            'event_action == "staged_scan_recovery"',
            "supervised canary expected exactly one new ready packet",
            "removed_paths",
            "modified_paths",
            "other_added_paths",
            "uutistenlukija.staged_packet.v1",
            "packet_id",
            "source_text",
            "sha256",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.workflow)

    def test_canary_accepts_exactly_one_valid_ready_addition(self) -> None:
        result = self._run_queue_delta_fixture(
            lambda root: (root / "pipeline/queues/staged/outbox").mkdir(parents=True),
            lambda root: self._write_valid_ready_packet(root),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"added_paths": [', result.stdout)
        self.assertIn("ready/valid_packet.json", result.stdout)

    def test_recovery_dispatch_accepts_zero_or_one_ready_addition(self) -> None:
        for label, mutation in (
            ("zero", lambda root: None),
            ("one", lambda root: self._write_valid_ready_packet(root)),
        ):
            with self.subTest(label=label):
                result = self._run_queue_delta_fixture(
                    lambda root: (root / "pipeline/queues/staged/outbox").mkdir(parents=True),
                    mutation,
                    event_name="repository_dispatch",
                    event_action="staged_scan_recovery",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('"event_action": "staged_scan_recovery"', result.stdout)

    def test_recovery_dispatch_rejects_two_ready_additions(self) -> None:
        def add_two(root: Path) -> None:
            self._write_valid_ready_packet(root, "one")
            self._write_valid_ready_packet(root, "two")

        result = self._run_queue_delta_fixture(
            lambda root: None,
            add_two,
            event_name="repository_dispatch",
            event_action="staged_scan_recovery",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max-packets contract is 1", result.stdout + result.stderr)

    def test_recovery_queue_contract_rejects_unknown_dispatch_type(self) -> None:
        result = self._run_queue_delta_fixture(
            lambda root: None,
            lambda root: self._write_valid_ready_packet(root),
            event_name="repository_dispatch",
            event_action="unexpected_recovery",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "unsupported staged scan event: repository_dispatch/unexpected_recovery",
            result.stdout + result.stderr,
        )

    def test_canary_rejects_removed_ready_file(self) -> None:
        def setup(root: Path) -> None:
            existing = root / "pipeline/queues/staged/ready/existing.json"
            existing.write_text("{}", encoding="utf-8")

        def mutate(root: Path) -> None:
            (root / "pipeline/queues/staged/ready/existing.json").unlink()
            self._write_valid_ready_packet(root)

        result = self._run_queue_delta_fixture(setup, mutate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("removed_paths", result.stdout + result.stderr)

    def test_canary_rejects_other_box_addition_and_modification(self) -> None:
        def setup_unchanged(root: Path) -> None:
            outbox = root / "pipeline/queues/staged/outbox"
            outbox.mkdir(parents=True)
            (outbox / "existing.json").write_text('{"state":"before"}', encoding="utf-8")

        def add_other_box_file(root: Path) -> None:
            self._write_valid_ready_packet(root)
            writing = root / "pipeline/queues/staged/writing"
            writing.mkdir(parents=True)
            (writing / "unexpected.json").write_text("{}", encoding="utf-8")

        def modify_other_box_file(root: Path) -> None:
            self._write_valid_ready_packet(root)
            (root / "pipeline/queues/staged/outbox/existing.json").write_text(
                '{"state":"after"}',
                encoding="utf-8",
            )

        for label, mutation, expected in (
            ("addition", add_other_box_file, "other_added_paths"),
            ("modification", modify_other_box_file, "modified_paths"),
        ):
            with self.subTest(change=label):
                result = self._run_queue_delta_fixture(setup_unchanged, mutation)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)

    def test_schedule_allows_only_paired_ready_expiry_moves(self) -> None:
        def setup(root: Path) -> None:
            existing = root / "pipeline/queues/staged/ready/expired.json"
            existing.write_text('{"state":"ready"}', encoding="utf-8")

        def paired_expiry(root: Path) -> None:
            (root / "pipeline/queues/staged/ready/expired.json").unlink()
            failed = root / "pipeline/queues/staged/failed"
            failed.mkdir(parents=True)
            (failed / "expired.json").write_text('{"state":"expired"}', encoding="utf-8")
            self._write_valid_ready_packet(root)

        result = self._run_queue_delta_fixture(
            setup,
            paired_expiry,
            event_name="schedule",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        def unpaired_failed_addition(root: Path) -> None:
            self._write_valid_ready_packet(root)
            failed = root / "pipeline/queues/staged/failed"
            failed.mkdir(parents=True)
            (failed / "unpaired.json").write_text("{}", encoding="utf-8")

        result = self._run_queue_delta_fixture(
            lambda root: None,
            unpaired_failed_addition,
            event_name="schedule",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmatched_failed_paths", result.stdout + result.stderr)


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


class DeployFallbackContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = DEPLOY.read_text(encoding="utf-8")

    def _run_script(self, step_name: str) -> str:
        step = self.workflow.index(f"      - name: {step_name}")
        run_header = "        run: |\n"
        run_start = self.workflow.index(run_header, step) + len(run_header)
        run_end = self.workflow.find("\n      - name:", run_start)
        if run_end == -1:
            run_end = len(self.workflow)
        return textwrap.dedent(self.workflow[run_start:run_end])

    def _run_step(
        self,
        step_name: str,
        *,
        event_name: str = "push",
        event_ref: str = "refs/heads/main",
        github_sha: str = "current-main",
        checkout_head: str = "current-main",
        remote_main: str = "current-main",
        fetch_mode: str = "ok",
        resolve_mode: str = "ok",
    ) -> tuple[subprocess.CompletedProcess, str]:
        git_stub = textwrap.dedent(
            """\
            git() {
              case "$*" in
                "rev-parse HEAD") printf '%s\\n' "$TEST_CHECKOUT_HEAD" ;;
                "fetch --no-tags --force origin refs/heads/main:refs/remotes/origin/deploy-main")
                  if [ "${TEST_FETCH_MODE:-ok}" = "fail" ]; then
                    return 42
                  fi
                  ;;
                "rev-parse --verify --quiet refs/remotes/origin/deploy-main^{commit}")
                  case "${TEST_RESOLVE_MODE:-ok}" in
                    fail) return 43 ;;
                    empty) return 0 ;;
                    ambiguous)
                      printf '%s\\n%s\\n' "$TEST_REMOTE_MAIN" "$TEST_REMOTE_OTHER"
                      ;;
                    *) printf '%s\\n' "$TEST_REMOTE_MAIN" ;;
                  esac
                  ;;
                *) command git "$@" ;;
              esac
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "github-output"
            env = os.environ.copy()
            env.update(
                {
                    "GITHUB_EVENT_NAME": event_name,
                    "GITHUB_REF": event_ref,
                    "GITHUB_SHA": github_sha,
                    "GITHUB_OUTPUT": str(output),
                    "TEST_CHECKOUT_HEAD": checkout_head,
                    "TEST_REMOTE_MAIN": remote_main,
                    "TEST_REMOTE_OTHER": "other-main",
                    "TEST_FETCH_MODE": fetch_mode,
                    "TEST_RESOLVE_MODE": resolve_mode,
                }
            )
            result = subprocess.run(
                ["bash", "-c", git_stub + self._run_script(step_name)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            actual_output = output.read_text(encoding="utf-8") if output.exists() else ""
        return result, actual_output

    def test_dispatch_permissions_checkout_and_secret_boundary(self) -> None:
        trigger_block = self.workflow[: self.workflow.index("\npermissions:")]
        self.assertRegex(
            trigger_block,
            re.compile(r"^  workflow_dispatch: \{\}$", re.MULTILINE),
        )
        self.assertEqual(trigger_block.count("workflow_dispatch"), 1)
        self.assertNotIn("inputs:", trigger_block)
        self.assertIn(
            "permissions:\n  contents: read\n\nconcurrency:",
            self.workflow,
        )
        for prohibited in (
            "contents: write",
            "actions: write",
            "deployments: write",
            "id-token: write",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, self.workflow)

        checkout = self.workflow.index("      - uses: actions/checkout@v5")
        admission = self.workflow.index("      - name: Admit current-main deploy event")
        checkout_step = self.workflow[checkout:admission]
        self.assertIn("persist-credentials: false", checkout_step)
        self.assertNotRegex(self.workflow, re.compile(r"^\s+environment:", re.MULTILINE))

        for secret_name, action_input in (
            ("CLOUDFLARE_API_TOKEN", "apiToken"),
            ("CLOUDFLARE_ACCOUNT_ID", "accountId"),
        ):
            with self.subTest(secret=secret_name):
                self.assertEqual(self.workflow.count(secret_name), 1)
                self.assertIn(
                    f"{action_input}: ${{{{ secrets.{secret_name} }}}}",
                    self.workflow,
                )
        prohibited_historical_sha = "".join(
            ("0549c28a9e5ee5fdbea32ffbd516b917", "31f0b75d")
        )
        self.assertNotIn(prohibited_historical_sha, self.workflow)

    def test_event_admission_is_main_only_and_checkout_bound(self) -> None:
        for event_name in ("push", "workflow_dispatch"):
            with self.subTest(event=event_name):
                result, output = self._run_step(
                    "Admit current-main deploy event",
                    event_name=event_name,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output, "")

        rejected = (
            ("workflow_dispatch", "refs/heads/unreviewed", "current-main", "refs/heads/main"),
            ("workflow_dispatch", "refs/tags/release", "current-main", "refs/heads/main"),
            ("schedule", "refs/heads/main", "current-main", "Unsupported deploy event"),
            ("push", "refs/heads/main", "different-checkout", "Checkout does not match GITHUB_SHA"),
        )
        for event_name, event_ref, checkout_head, expected in rejected:
            with self.subTest(event=event_name, ref=event_ref, checkout=checkout_head):
                result, output = self._run_step(
                    "Admit current-main deploy event",
                    event_name=event_name,
                    event_ref=event_ref,
                    checkout_head=checkout_head,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
                self.assertIn(expected, result.stdout + result.stderr)

        checkout = self.workflow.index("      - uses: actions/checkout@v5")
        admission = self.workflow.index("      - name: Admit current-main deploy event")
        setup = self.workflow.index("      - name: Setup Hugo")
        self.assertLess(checkout, admission)
        self.assertLess(admission, setup)

    def test_existing_validation_and_concurrency_order_is_preserved(self) -> None:
        expected_order = (
            "      - uses: actions/checkout@v5",
            "      - name: Admit current-main deploy event",
            "      - name: Setup Hugo",
            "      - name: Validate Hugo templates",
            "      - name: Validate portal CSS contract",
            "      - name: Validate critical pipeline script permissions",
            "      - name: Validate frontmatter YAML syntax",
            "      - name: Generate canonical pipeline status",
            "      - name: Build",
            "      - name: Validate build",
            "      - name: Check Cloudflare Pages file budget",
            "      - name: Validate public surface",
            "      - name: Verify deployment checkout is current",
            "      - name: Deploy to Cloudflare Pages",
            "      - name: Check internal links",
        )
        positions = [self.workflow.index(step) for step in expected_order]
        self.assertEqual(positions, sorted(positions))
        for expected in (
            'HUGO_VERSION="0.147.0"',
            "sha256sum --check --strict",
            "hugo --minify --cleanDestinationDir",
            "python3 pipeline/ci_validate.py --skip templates",
            "python3 scripts/check_public_file_count.py --public-dir public --limit 20000 --min-headroom 1000",
            "python3 scripts/validate_public_surface.py --public-dir public",
            "python3 pipeline/check_links.py --public-dir public",
            "group: cloudflare-pages-production",
            "queue: max",
            "cancel-in-progress: false",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.workflow)

    def test_freshness_fetch_and_resolution_fail_closed(self) -> None:
        cases = (
            ("fail", "ok", "Unable to fetch refs/heads/main"),
            ("ok", "fail", "Unable to resolve fetched origin/main"),
            ("ok", "empty", "did not resolve to exactly one commit"),
            ("ok", "ambiguous", "did not resolve to exactly one commit"),
        )
        for fetch_mode, resolve_mode, expected in cases:
            with self.subTest(fetch=fetch_mode, resolve=resolve_mode):
                result, output = self._run_step(
                    "Verify deployment checkout is current",
                    fetch_mode=fetch_mode,
                    resolve_mode=resolve_mode,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
                self.assertIn(expected, result.stdout + result.stderr)

        result, output = self._run_step(
            "Verify deployment checkout is current",
            event_name="schedule",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")
        self.assertIn("Unsupported deploy event", result.stdout + result.stderr)

    def test_stale_manual_fails_stale_push_skips_and_exact_main_enables(self) -> None:
        result, output = self._run_step(
            "Verify deployment checkout is current",
            event_name="workflow_dispatch",
            remote_main="newer-main",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")
        self.assertIn("Stale manual deployment rejected", result.stdout + result.stderr)

        result, output = self._run_step(
            "Verify deployment checkout is current",
            event_name="push",
            remote_main="newer-main",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "current=false\n")
        self.assertIn("Superseded deployment skipped", result.stdout + result.stderr)

        for event_name in ("push", "workflow_dispatch"):
            with self.subTest(event=event_name):
                result, output = self._run_step(
                    "Verify deployment checkout is current",
                    event_name=event_name,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output, "current=true\n")

    def test_fresh_fetch_directly_controls_the_following_cloudflare_step(self) -> None:
        verify = self.workflow.index("      - name: Verify deployment checkout is current")
        deploy = self.workflow.index("      - name: Deploy to Cloudflare Pages")
        next_step = self.workflow.index("\n      - name:", verify + 1) + 1
        self.assertEqual(next_step, deploy)
        verify_step = self.workflow[verify:deploy]
        self.assertIn(
            'git fetch --no-tags --force origin "refs/heads/main:${REMOTE_REF}"',
            verify_step,
        )
        self.assertIn(
            'git rev-parse --verify --quiet "${REMOTE_REF}^{commit}"',
            verify_step,
        )
        link_check = self.workflow.index("\n      - name: Check internal links", deploy)
        deploy_step = self.workflow[deploy:link_check]
        self.assertIn("steps.deploy_head.outputs.current == 'true'", deploy_step)
        self.assertIn("uses: cloudflare/wrangler-action@v4", deploy_step)


class PagesDeployStatusContractTests(unittest.TestCase):
    def _deploy_workflows(self) -> list[tuple[Path, str]]:
        workflows = []
        for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = workflow_path.read_text(encoding="utf-8")
            if "pages deploy public" in workflow:
                workflows.append((workflow_path, workflow))
        return workflows

    def _run_script(self, workflow: str, step_name: str) -> str:
        step = workflow.index(f"      - name: {step_name}")
        run_header = "        run: |\n"
        run_start = workflow.index(run_header, step) + len(run_header)
        run_end = workflow.index("\n      - name:", run_start)
        return textwrap.dedent(workflow[run_start:run_end])

    def test_every_pages_deploy_refreshes_status_then_panel_before_build(self) -> None:
        deploy_workflows = []
        for workflow_path, workflow in self._deploy_workflows():
            deploy_workflows.append(workflow_path.name)
            with self.subTest(workflow=workflow_path.name):
                producer = "python3 pipeline/generate_pipeline_status.py"
                panel = (
                    "python3 scripts/business_control_panel.py "
                    "--pipeline-status-file static/api/pipeline-status.json "
                    "--output static/api/business-control-panel.json"
                )
                self.assertIn(producer, workflow)
                self.assertIn(panel, workflow)
                status = workflow.index(producer)
                business_panel = workflow.index(panel)
                build = workflow.index("- name: Build")
                deploy = workflow.index("- name: Deploy to Cloudflare Pages")
                self.assertLess(status, business_panel)
                self.assertLess(business_panel, build)
                self.assertLess(build, deploy)

        self.assertEqual(
            deploy_workflows,
            ["daily-kooste.yml", "deploy.yml", "staged-publish.yml"],
        )

    def test_deploy_workflow_changes_trigger_the_corrected_path(self) -> None:
        deploy = DEPLOY.read_text(encoding="utf-8")
        self.assertNotIn('- ".github/workflows/deploy.yml"', deploy)

    def test_pages_deployments_share_one_non_cancelling_multi_run_queue(self) -> None:
        concurrency = (
            "concurrency:\n"
            "  group: cloudflare-pages-production\n"
            "  queue: max\n"
            "  cancel-in-progress: false"
        )
        for workflow_path, workflow in self._deploy_workflows():
            with self.subTest(workflow=workflow_path.name):
                self.assertIn(concurrency, workflow)

    def test_superseded_checkout_skips_pages_deploy_cleanly(self) -> None:
        git_stub = textwrap.dedent(
            """\
            git() {
              case "$*" in
                "rev-parse HEAD") printf '%s\\n' "$TEST_CHECKOUT_HEAD" ;;
                "fetch --no-tags --force origin refs/heads/main:refs/remotes/origin/deploy-main")
                  return 0
                  ;;
                "rev-parse --verify --quiet refs/remotes/origin/deploy-main^{commit}")
                  printf '%s\\n' "$TEST_REMOTE_MAIN"
                  ;;
                "ls-remote origin refs/heads/main")
                  printf '%s\\trefs/heads/main\\n' "$TEST_REMOTE_MAIN"
                  ;;
                *) command git "$@" ;;
              esac
            }
            """
        )
        for workflow_path, workflow in self._deploy_workflows():
            with self.subTest(workflow=workflow_path.name), tempfile.TemporaryDirectory() as tmp:
                script = git_stub + self._run_script(
                    workflow,
                    "Verify deployment checkout is current",
                )
                output = Path(tmp) / "github-output"
                env = os.environ.copy()
                env.update(
                    {
                        "GITHUB_EVENT_NAME": "push",
                        "GITHUB_OUTPUT": str(output),
                        "TEST_CHECKOUT_HEAD": "older-checkout",
                        "TEST_REMOTE_MAIN": "newer-main",
                    }
                )
                result = subprocess.run(
                    ["bash", "-c", script],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output.read_text(encoding="utf-8"), "current=false\n")
                self.assertIn("Superseded deployment skipped", result.stdout)

                deploy_start = workflow.index(
                    "      - name: Deploy to Cloudflare Pages"
                )
                deploy_end = workflow.index("\n      - name:", deploy_start)
                deploy_step = workflow[deploy_start:deploy_end]
                self.assertIn(
                    "steps.deploy_head.outputs.current == 'true'",
                    deploy_step,
                )


class StagedPublishRunwayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = STAGED_PUBLISH.read_text(encoding="utf-8")

    def _publish_run_script(self) -> str:
        step = self.workflow.index("      - name: Publish staged outbox packets")
        run_header = "        run: |\n"
        run_start = self.workflow.index(run_header, step) + len(run_header)
        run_end = self.workflow.index("\n      - name:", run_start)
        return textwrap.dedent(self.workflow[run_start:run_end])

    def _gate_run_script(self) -> str:
        step = self.workflow.index(
            "      - name: Gate automated runs and admit current main"
        )
        run_header = "        run: |\n"
        run_start = self.workflow.index(run_header, step) + len(run_header)
        run_end = self.workflow.index("\n      - name:", run_start)
        return textwrap.dedent(self.workflow[run_start:run_end])

    def _run_gate(
        self,
        *,
        event_name: str = "schedule",
        marker_present: bool = True,
        github_sha: str = "current-main",
        checkout_head: str = "current-main",
        remote_main: str = "current-main",
        fetch_mode: str = "ok",
        resolve_mode: str = "ok",
    ) -> tuple[subprocess.CompletedProcess, str]:
        git_stub = textwrap.dedent(
            """\
            git() {
              case "$*" in
                "rev-parse HEAD") printf '%s\\n' "$TEST_CHECKOUT_HEAD" ;;
                "fetch --no-tags --force origin refs/heads/main:refs/remotes/origin/staged-publish-main")
                  if [ "${TEST_FETCH_MODE:-ok}" = "fail" ]; then
                    return 42
                  fi
                  ;;
                "rev-parse --verify --quiet refs/remotes/origin/staged-publish-main^{commit}")
                  case "${TEST_RESOLVE_MODE:-ok}" in
                    fail) return 43 ;;
                    empty) return 0 ;;
                    ambiguous)
                      printf '%s\\n%s\\n' "$TEST_REMOTE_MAIN" "$TEST_REMOTE_OTHER"
                      ;;
                    *) printf '%s\\n' "$TEST_REMOTE_MAIN" ;;
                  esac
                  ;;
                *) command git "$@" ;;
              esac
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if marker_present:
                marker = root / "pipeline/actions-publish.enabled"
                marker.parent.mkdir(parents=True)
                marker.touch()
            output = root / "github-output"
            env = os.environ.copy()
            env.update(
                {
                    "GITHUB_EVENT_NAME": event_name,
                    "GITHUB_SHA": github_sha,
                    "GITHUB_OUTPUT": str(output),
                    "TEST_CHECKOUT_HEAD": checkout_head,
                    "TEST_REMOTE_MAIN": remote_main,
                    "TEST_REMOTE_OTHER": "other-main",
                    "TEST_FETCH_MODE": fetch_mode,
                    "TEST_RESOLVE_MODE": resolve_mode,
                }
            )
            result = subprocess.run(
                ["bash", "-c", git_stub + self._gate_run_script()],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            actual_output = output.read_text(encoding="utf-8") if output.exists() else ""
        return result, actual_output

    def _git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def _commit_changes(
        self,
        repository: Path,
        changes: dict[str, str | None],
        message: str,
    ) -> str:
        for relative_path, content in changes.items():
            target = repository / relative_path
            if content is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        self._git(repository, "add", "-A")
        self._git(repository, "commit", "-m", message)
        return self._git(repository, "rev-parse", "HEAD")

    def _run_real_schedule_gate(
        self,
        first_changes: dict[str, str | None],
        *,
        second_changes: dict[str, str | None] | None = None,
        divergent: bool = False,
        merge_history: bool = False,
    ) -> tuple[subprocess.CompletedProcess, str, dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            seed = root / "seed"
            runner = root / "runner"
            runner_temp = root / "runner-temp"

            self._git(root, "init", "--bare", str(remote))
            seed.mkdir()
            self._git(seed, "init")
            self._git(seed, "config", "user.name", "Workflow Fixture")
            self._git(seed, "config", "user.email", "workflow-fixture@example.invalid")
            marker = seed / "pipeline/actions-publish.enabled"
            marker.parent.mkdir(parents=True)
            marker.write_text("", encoding="utf-8")
            (seed / "README.md").write_text("baseline\n", encoding="utf-8")
            self._git(seed, "add", "-A")
            self._git(seed, "commit", "-m", "baseline")
            self._git(seed, "branch", "-M", "main")
            self._git(seed, "remote", "add", "origin", str(remote))
            self._git(seed, "push", "-u", "origin", "main")
            base = self._git(seed, "rev-parse", "HEAD")

            self._git(root, "clone", "--branch", "main", str(remote), str(runner))
            self._git(runner, "checkout", "-B", "main", base)

            if merge_history:
                self._git(seed, "checkout", "-b", "queue-side", base)
                self._commit_changes(seed, first_changes, "side queue motion")
                self._git(seed, "checkout", "main")
                self._commit_changes(
                    seed,
                    {
                        "pipeline/queues/staged/ready/main.json":
                            '{"packet":"main"}\n',
                    },
                    "main queue motion",
                )
                self._git(seed, "merge", "--no-ff", "queue-side", "-m", "merge queue motion")
                first_tip = self._git(seed, "rev-parse", "HEAD")
            else:
                first_tip = self._commit_changes(seed, first_changes, "first main motion")
            self._git(seed, "push", "origin", "HEAD:main")

            if divergent:
                tree = self._git(seed, "rev-parse", f"{first_tip}^{{tree}}")
                divergent_tip = self._git(seed, "commit-tree", tree, "-m", "divergent motion")
                self._git(
                    seed,
                    "push",
                    "origin",
                    f"{divergent_tip}:refs/heads/divergent-fixture",
                )
                self._git(
                    root,
                    f"--git-dir={remote}",
                    "update-ref",
                    "refs/heads/main",
                    divergent_tip,
                    first_tip,
                )
                first_tip = divergent_tip

            second_tip = ""
            wrapper = ""
            if second_changes is not None:
                second_tip = self._commit_changes(seed, second_changes, "second main motion")
                wrapper = textwrap.dedent(
                    """\
                    TEST_FETCH_COUNT=0
                    git() {
                      if [ "$1" = "fetch" ]; then
                        command git "$@"
                        fetch_status=$?
                        TEST_FETCH_COUNT=$((TEST_FETCH_COUNT + 1))
                        if [ "$fetch_status" -eq 0 ] && [ "$TEST_FETCH_COUNT" -eq 1 ]; then
                          command git -C "$TEST_SECOND_PUSH_REPO" push origin HEAD:main >/dev/null
                          fetch_status=$?
                        fi
                        return "$fetch_status"
                      fi
                      command git "$@"
                    }
                    """
                )

            output = root / "github-output"
            runner_temp.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "GITHUB_EVENT_NAME": "schedule",
                    "GITHUB_SHA": base,
                    "GITHUB_OUTPUT": str(output),
                    "RUNNER_TEMP": str(runner_temp),
                    "TEST_SECOND_PUSH_REPO": str(seed),
                }
            )
            result = subprocess.run(
                ["bash", "-c", wrapper + self._gate_run_script()],
                cwd=runner,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            actual_output = output.read_text(encoding="utf-8") if output.exists() else ""
            state = {
                "base": base,
                "first_tip": first_tip,
                "second_tip": second_tip,
                "head": self._git(runner, "rev-parse", "HEAD"),
                "branch": self._git(runner, "branch", "--show-current"),
            }
        return result, actual_output, state

    def test_runway_summary_uses_the_canonical_status_producer(self) -> None:
        publish = self.workflow.index("- name: Publish staged outbox packets")
        summary = self.workflow.index("- name: Summarize staged queue runway")
        preserve = self.workflow.index("- name: Preserve staged publish cycle telemetry")
        validate = self.workflow.index("- name: Validate Hugo templates")
        self.assertLess(publish, summary)
        self.assertLess(summary, preserve)
        self.assertLess(preserve, validate)
        self.assertIn(
            "python3 pipeline/generate_pipeline_status.py "
            '--cycle-outcome "$RUNNER_TEMP/staged-publish-cycle.json" '
            "--actions-summary",
            self.workflow,
        )

    def test_clean_runner_cycle_telemetry_is_always_preserved(self) -> None:
        publish = self.workflow.index("      - name: Publish staged outbox packets")
        summary = self.workflow.index("      - name: Summarize staged queue runway")
        preserve = self.workflow.index(
            "      - name: Preserve staged publish cycle telemetry"
        )
        publish_step = self.workflow[publish:summary]
        summary_step = self.workflow[summary:preserve]
        preserve_end = self.workflow.index("\n      - name:", preserve + 1)
        preserve_step = self.workflow[preserve:preserve_end]

        self.assertIn(
            '--outcome-json "$RUNNER_TEMP/staged-publish-cycle.json"',
            publish_step,
        )
        self.assertIn("if: always() && steps.gate.outputs.enabled == 'true'", summary_step)
        self.assertIn(
            '--cycle-outcome "$RUNNER_TEMP/staged-publish-cycle.json"',
            summary_step,
        )
        self.assertIn("if: always() && steps.gate.outputs.enabled == 'true'", preserve_step)
        self.assertIn("uses: actions/upload-artifact@v4", preserve_step)
        self.assertIn("path: ${{ runner.temp }}/staged-publish-cycle.json", preserve_step)
        self.assertIn("if-no-files-found: error", preserve_step)
        self.assertNotIn("pipeline/logs/publish-metrics.json", self.workflow)

    def test_outbox_push_reuses_marker_gate_and_max_one_cap(self) -> None:
        trigger_block = self.workflow[: self.workflow.index("\npermissions:")]
        self.assertIn('"pipeline/queues/staged/outbox/**"', trigger_block)
        self.assertNotIn('"pipeline/queues/staged/ready/**"', trigger_block)
        self.assertIn(
            '"$GITHUB_EVENT_NAME" != "workflow_dispatch" ] && '
            "[ ! -f pipeline/actions-publish.enabled ]",
            self.workflow,
        )

        script = (
            'python3() { printf "PUBLISHER_CALLED %s\\n" "$*"; }\n'
            + self._publish_run_script()
        )
        env = os.environ.copy()
        env.update(
            {
                "GITHUB_EVENT_NAME": "push",
                "MAX_ARTICLES": "3",
                "RUNNER_TEMP": "/tmp/test-runner",
            }
        )
        result = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--max-articles 1 --git-push", result.stdout)

    def test_disabled_schedule_skips_without_remote_admission(self) -> None:
        result, output = self._run_gate(
            marker_present=False,
            fetch_mode="fail",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "enabled=false\n")
        self.assertIn("Cutover marker", result.stdout)
        self.assertNotIn("Unable to fetch", result.stdout + result.stderr)

    def test_exact_current_main_is_admitted_for_every_supported_event(self) -> None:
        for event_name in ("push", "schedule", "workflow_dispatch"):
            with self.subTest(event=event_name):
                result, output = self._run_gate(
                    event_name=event_name,
                    marker_present=event_name != "workflow_dispatch",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output, "enabled=true\n")

        gate = self.workflow.index(
            "      - name: Gate automated runs and admit current main"
        )
        setup = self.workflow.index("      - name: Setup Hugo")
        publish = self.workflow.index("      - name: Publish staged outbox packets")
        self.assertLess(gate, setup)
        self.assertLess(setup, publish)

    def test_superseded_push_skips_but_stale_manual_fails(self) -> None:
        result, output = self._run_gate(
            event_name="push",
            remote_main="newer-main",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "enabled=false\n")
        self.assertIn("Superseded staged publish skipped", result.stdout)

        result, output = self._run_gate(
            event_name="workflow_dispatch",
            marker_present=False,
            remote_main="newer-main",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")
        self.assertIn("Stale manual staged publish rejected", result.stdout)

    def test_stale_schedule_readmits_one_queue_json_motion(self) -> None:
        result, output, state = self._run_real_schedule_gate(
            {
                "pipeline/queues/staged/ready/20260815T103927Z_415eeab89b.json":
                    '{"schema":"uutistenlukija.staged_packet.v1"}\n',
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "enabled=true\n")
        self.assertEqual(state["head"], state["first_tip"])
        self.assertEqual(state["branch"], "main")

    def test_stale_schedule_stops_on_second_main_motion(self) -> None:
        result, output, state = self._run_real_schedule_gate(
            {
                "pipeline/queues/staged/ready/first.json": '{"packet":"first"}\n',
            },
            second_changes={
                "pipeline/queues/staged/ready/second.json": '{"packet":"second"}\n',
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "enabled=false\n")
        self.assertIn("reason=second_main_motion", result.stdout)
        self.assertEqual(state["head"], state["first_tip"])
        self.assertNotEqual(state["head"], state["second_tip"])

    def test_stale_schedule_stops_on_wider_drift(self) -> None:
        wider_paths = (
            ".github/workflows/staged-publish.yml",
            "pipeline/generate_pipeline_status.py",
            "content/posts/drift.md",
            "pipeline/actions-publish.enabled",
        )
        for wider_path in wider_paths:
            with self.subTest(path=wider_path):
                result, output, state = self._run_real_schedule_gate(
                    {
                        "pipeline/queues/staged/ready/packet.json": '{"packet":"queue"}\n',
                        wider_path: "wider drift\n",
                    }
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output, "enabled=false\n")
                self.assertIn("reason=wider_drift", result.stdout)
                self.assertIn(f"path={wider_path}", result.stdout)
                self.assertEqual(state["head"], state["base"])

    def test_stale_schedule_stops_on_invalid_queue_json(self) -> None:
        result, output, state = self._run_real_schedule_gate(
            {
                "pipeline/queues/staged/ready/packet.json": "not json\n",
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output, "enabled=false\n")
        self.assertIn("reason=invalid_queue_json", result.stdout)
        self.assertEqual(state["head"], state["base"])

    def test_stale_schedule_stops_on_ambiguous_ancestry(self) -> None:
        cases = (
            {"divergent": True},
            {"merge_history": True},
        )
        for options in cases:
            with self.subTest(options=options):
                result, output, state = self._run_real_schedule_gate(
                    {
                        "pipeline/queues/staged/ready/packet.json":
                            '{"packet":"queue"}\n',
                    },
                    **options,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(output, "enabled=false\n")
                self.assertIn("reason=ambiguous_ancestry", result.stdout)
                self.assertEqual(state["head"], state["base"])

    def test_schedule_readmission_is_single_bounded_refetch_and_recheckout(self) -> None:
        gate = self._gate_run_script()
        fetch = 'git fetch --no-tags --force origin "refs/heads/main:${REMOTE_REF}"'
        self.assertEqual(gate.count(fetch), 2)
        self.assertEqual(gate.count("git checkout main"), 1)
        self.assertEqual(gate.count('git merge --ff-only "$REMOTE_MAIN"'), 1)
        self.assertIn('pipeline/queues/staged/*.json)', gate)
        self.assertIn('git merge-base --is-ancestor "$CHECKOUT_HEAD" "$REMOTE_MAIN"', gate)
        self.assertIn("reason=ambiguous_ancestry", gate)
        self.assertIn("reason=wider_drift", gate)
        self.assertIn("reason=invalid_queue_json", gate)
        self.assertIn("reason=second_main_motion", gate)

    def test_admission_failures_do_not_enable_publishing(self) -> None:
        cases = (
            ("different-checkout", "ok", "ok", "Checkout does not match GITHUB_SHA"),
            ("current-main", "fail", "ok", "Unable to fetch refs/heads/main"),
            ("current-main", "ok", "fail", "did not resolve to exactly one commit"),
            ("current-main", "ok", "empty", "did not resolve to exactly one commit"),
            ("current-main", "ok", "ambiguous", "did not resolve to exactly one commit"),
        )
        for checkout_head, fetch_mode, resolve_mode, expected in cases:
            with self.subTest(
                checkout=checkout_head,
                fetch=fetch_mode,
                resolve=resolve_mode,
            ):
                result, output = self._run_gate(
                    checkout_head=checkout_head,
                    fetch_mode=fetch_mode,
                    resolve_mode=resolve_mode,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
                self.assertIn(expected, result.stdout + result.stderr)

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
        env["RUNNER_TEMP"] = "/tmp/test-runner"
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

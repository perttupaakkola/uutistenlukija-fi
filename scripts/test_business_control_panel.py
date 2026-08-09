#!/usr/bin/env python3
"""Regression tests for the public business control-panel JSON."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().with_name("business_control_panel.py")
spec = importlib.util.spec_from_file_location("business_control_panel", MODULE_PATH)
assert spec and spec.loader
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)


class BusinessControlPanelReportingTest(unittest.TestCase):
    def production_payload(self, now: datetime) -> dict:
        return {
            "hours": 24,
            "generated_at": (now - timedelta(minutes=5)).isoformat(),
            "status": "ok",
            "is_stale": False,
            "stale_threshold_minutes": 90,
            "articles": {
                "attempted": 0,
                "published": 14,
                "rejected": 0,
                "publish_rate": 0,
                "last_published_ts": (now - timedelta(minutes=30)).isoformat(),
            },
            "stagedQueueRunway": {
                "readyCount": 0,
                "writingCount": 0,
                "outboxCount": 23,
                "publisherEnabled": True,
                "scannerEnabled": True,
                "workerEnabled": True,
                "maxPacketsPerCycle": 3,
                "worstCaseRemainingCycles": 8,
                "replenishmentState": "end_to_end_enabled",
                "severity": "ok",
                "reasons": [
                    "publisher_enabled",
                    "scanner_enabled",
                    "worker_enabled",
                    "queue_active",
                ],
            },
        }

    def validated_production(self, now: datetime, *, published: int = 14) -> dict:
        payload = self.production_payload(now)
        payload["articles"]["published"] = published
        return panel.validate_production_pipeline_status(
            payload,
            now,
            panel.PRODUCTION_PIPELINE_STATUS_URL,
        )

    def run_git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def init_tracked_repo(self, root: Path) -> str:
        root.mkdir(parents=True)
        self.run_git(root, "init", "--initial-branch=main")
        self.run_git(root, "config", "user.name", "Business Panel Test")
        self.run_git(root, "config", "user.email", "panel-test@example.invalid")
        (root / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.run_git(root, "add", "tracked.txt")
        self.run_git(root, "commit", "-m", "base")
        head = self.run_git(root, "rev-parse", "HEAD")
        self.run_git(root, "remote", "add", "origin", str(root.parent / "unused-origin.git"))
        self.run_git(root, "update-ref", "refs/remotes/origin/main", head)
        self.run_git(root, "branch", "--set-upstream-to=origin/main", "main")
        return head

    def test_fresh_production_truth_overrides_stale_local_checkout(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content_dir = root / "content" / "posts"
            log_dir = root / "pipeline" / "logs"
            outbox_dir = root / "pipeline" / "queues" / "staged" / "outbox"
            content_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            outbox_dir.mkdir(parents=True)
            (content_dir / "stale.md").write_text(
                "---\n"
                "title: Stale observer article\n"
                "date: 2026-08-04T22:08:07+00:00\n"
                "categories:\n"
                "  - Kotimaa\n"
                "---\nBody\n",
                encoding="utf-8",
            )
            (log_dir / "metrics.json").write_text("[]", encoding="utf-8")
            (outbox_dir / "local-only.json").write_text("{}", encoding="utf-8")
            checkout_freshness = {
                "status": "stale",
                "fresh": False,
                "reason": "fixture is stale",
                "head": "a" * 40,
                "upstream": "origin/main",
                "upstream_head": "b" * 40,
                "behind_count": 200,
                "ahead_count": 0,
                "source": "read-only local Git metadata; no fetch or network access",
            }
            production = self.validated_production(now)
            with (
                patch.object(panel, "PROJECT_DIR", root),
                patch.object(panel, "CONTENT_DIR", content_dir),
                patch.object(panel, "PIPELINE_DIR", root / "pipeline"),
                patch.object(panel, "LOG_DIR", log_dir),
                patch.object(panel, "QUEUE_DIR", root / "pipeline" / "queues"),
                patch.object(panel, "git_upstream_freshness", return_value=checkout_freshness),
                patch.object(panel, "production_pipeline_status", return_value=production),
            ):
                data = panel.build_panel(now)

        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["production_pipeline"]["evidence_status"], "validated")
        self.assertEqual(data["pipeline"]["last_24h"]["article_count"], 14)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count_source"], "validated production pipeline-status")
        self.assertEqual(data["content"]["published_last_24h"], 14)
        self.assertEqual(data["content"]["published_last_24h_local"], 0)
        self.assertEqual(data["content"]["last_publish_at"], production["last_publish_at"])
        self.assertEqual(data["content"]["last_publish_at_local"], "2026-08-04T22:08:07Z")
        self.assertEqual(data["content"]["operator_source"], panel.PRODUCTION_PIPELINE_STATUS_URL)
        self.assertEqual(data["pipeline"]["operator_source"], panel.PRODUCTION_PIPELINE_STATUS_URL)
        self.assertEqual(data["pipeline"]["staged_queue_runway"]["outboxCount"], 23)
        self.assertEqual(data["queues"]["queues"]["staged/outbox"]["count"], 1)
        self.assertEqual(data["git_upstream_freshness"]["status"], "stale")

    def test_unusable_production_never_falls_back_to_local_ok(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)
        local_content = {
            "article_count_local": 1,
            "draft_count_local": 0,
            "published_last_24h_local": 1,
            "last_publish_at": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "last_publish_age_minutes": 10.0,
            "latest_article": {"slug": "local", "title": "Local", "category": "Kotimaa"},
            "source": "content/posts frontmatter",
        }
        local_pipeline = {
            "source": "local metrics",
            "metrics_rows_total": 1,
            "last_24h": {"article_count": 1, "failure": 0},
        }
        local_queues = {"source": "pipeline/queues", "queues": {}}
        checkout_freshness = {"status": "fresh", "fresh": True, "reason": "local fixture is fresh"}
        cases = [
            ("unavailable", "unknown"),
            ("invalid", "unknown"),
            ("contradictory", "unknown"),
            ("stale", "stale"),
        ]
        for evidence_status, expected_status in cases:
            with self.subTest(evidence_status=evidence_status):
                production = panel._production_evidence_failure(
                    now,
                    evidence_status,
                    f"fixture is {evidence_status}",
                    generated_at=now - timedelta(minutes=100) if evidence_status == "stale" else None,
                )
                with (
                    patch.object(panel, "git_upstream_freshness", return_value=checkout_freshness),
                    patch.object(panel, "production_pipeline_status", return_value=production),
                    patch.object(panel, "content_summary", return_value=dict(local_content)),
                    patch.object(
                        panel,
                        "pipeline_summary",
                        return_value={**local_pipeline, "last_24h": dict(local_pipeline["last_24h"])},
                    ),
                    patch.object(panel, "queue_summary", return_value=dict(local_queues)),
                    patch.object(panel, "category_drift", return_value={}),
                    patch.object(panel, "analytics_status", return_value={}),
                    patch.object(panel, "monetization_status", return_value={}),
                    patch.object(panel, "local_coordination_placeholders", return_value={}),
                ):
                    data = panel.build_panel(now)

                self.assertEqual(data["status"], expected_status)
                self.assertIsNone(data["content"]["published_last_24h"])
                self.assertIsNone(data["content"]["last_publish_at"])
                self.assertEqual(data["content"]["published_last_24h_local"], 1)
                self.assertEqual(data["content"]["last_publish_at_local"], local_content["last_publish_at"])
                self.assertIsNone(data["pipeline"]["last_24h"]["article_count"])
                self.assertEqual(data["pipeline"]["last_24h"]["article_count_local"], 1)
                self.assertIsNone(data["pipeline"]["staged_queue_runway"])

    def test_production_validation_fails_closed_for_stale_invalid_site_and_contradiction(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)
        cases = []

        stale = self.production_payload(now)
        stale["generated_at"] = (now - timedelta(minutes=91)).isoformat()
        cases.append(("stale", stale, "stale", panel.PRODUCTION_PIPELINE_STATUS_URL))

        invalid = self.production_payload(now)
        invalid["articles"] = {**invalid["articles"], "published": "14"}
        cases.append(("invalid", invalid, "invalid", panel.PRODUCTION_PIPELINE_STATUS_URL))

        wrong_site = self.production_payload(now)
        wrong_site["site"] = "other.invalid"
        cases.append(("wrong_site", wrong_site, "invalid", panel.PRODUCTION_PIPELINE_STATUS_URL))

        wrong_url = self.production_payload(now)
        cases.append(("wrong_url", wrong_url, "invalid", "https://other.invalid/api/pipeline-status.json"))

        contradictory = self.production_payload(now)
        contradictory["is_stale"] = True
        cases.append(("contradictory", contradictory, "contradictory", panel.PRODUCTION_PIPELINE_STATUS_URL))

        for name, payload, expected, source_url in cases:
            with self.subTest(name=name):
                evidence = panel.validate_production_pipeline_status(
                    payload,
                    now,
                    source_url,
                )
                self.assertEqual(evidence["evidence_status"], expected)
                self.assertFalse(evidence["fresh"])
                self.assertNotEqual(evidence.get("pipeline_status"), "ok")

    def test_zero_published_with_recent_last_publish_fails_closed(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)
        payload = self.production_payload(now)
        payload["articles"]["published"] = 0

        evidence = panel.validate_production_pipeline_status(
            payload,
            now,
            panel.PRODUCTION_PIPELINE_STATUS_URL,
        )

        self.assertEqual(evidence["evidence_status"], "contradictory")
        self.assertFalse(evidence["fresh"])
        self.assertIsNone(evidence["pipeline_status"])
        self.assertIsNone(evidence["published_last_24h"])
        self.assertIsNone(evidence["last_publish_at"])
        self.assertIsNone(evidence["staged_queue_runway"])

        with (
            patch.object(panel, "git_upstream_freshness", return_value={"status": "fresh"}),
            patch.object(panel, "production_pipeline_status", return_value=evidence),
            patch.object(
                panel,
                "content_summary",
                return_value={
                    "published_last_24h_local": 0,
                    "last_publish_at": None,
                    "last_publish_age_minutes": None,
                },
            ),
            patch.object(panel, "pipeline_summary", return_value={"last_24h": {}}),
            patch.object(panel, "queue_summary", return_value={}),
            patch.object(panel, "category_drift", return_value={}),
            patch.object(panel, "analytics_status", return_value={}),
            patch.object(panel, "monetization_status", return_value={}),
            patch.object(panel, "local_coordination_placeholders", return_value={}),
        ):
            data = panel.build_panel(now)

        self.assertEqual(data["status"], "unknown")
        self.assertIsNone(data["content"]["published_last_24h"])
        self.assertIsNone(data["content"]["last_publish_at"])
        self.assertIsNone(data["pipeline"]["staged_queue_runway"])

    def test_production_fetch_timeout_is_sanitized_and_fails_closed(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)
        with patch.object(
            panel,
            "urlopen",
            side_effect=TimeoutError(
                "request failed https://uutistenlukija.fi/api/pipeline-status.json?token=do-not-print"
            ),
        ):
            evidence = panel.production_pipeline_status(now)

        self.assertEqual(evidence["evidence_status"], "unavailable")
        self.assertFalse(evidence["fresh"])
        self.assertNotIn("do-not-print", evidence["reason"])
        self.assertNotIn("?", evidence["reason"])

    def test_production_fetch_rejects_invalid_json(self) -> None:
        now = datetime(2026, 8, 9, 5, 30, tzinfo=timezone.utc)

        class InvalidJsonResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self) -> str:
                return panel.PRODUCTION_PIPELINE_STATUS_URL

            def read(self, _limit: int) -> bytes:
                return b"{not-json"

        with patch.object(panel, "urlopen", return_value=InvalidJsonResponse()):
            evidence = panel.production_pipeline_status(now)

        self.assertEqual(evidence["evidence_status"], "invalid")
        self.assertFalse(evidence["fresh"])
        self.assertIn("valid JSON", evidence["reason"])

    def test_git_upstream_freshness_is_fresh_only_at_configured_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            head = self.init_tracked_repo(root)

            freshness = panel.git_upstream_freshness(root)

        self.assertEqual(freshness["status"], "fresh")
        self.assertTrue(freshness["fresh"])
        self.assertEqual(freshness["head"], head)
        self.assertEqual(freshness["upstream_head"], head)
        self.assertEqual(freshness["behind_count"], 0)
        self.assertEqual(freshness["ahead_count"], 0)

    def test_git_upstream_freshness_reports_positive_behind_count_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            head = self.init_tracked_repo(root)
            self.run_git(root, "switch", "--create", "upstream-work")
            (root / "tracked.txt").write_text("base\nupstream\n", encoding="utf-8")
            self.run_git(root, "add", "tracked.txt")
            self.run_git(root, "commit", "-m", "upstream")
            upstream_head = self.run_git(root, "rev-parse", "HEAD")
            self.run_git(root, "switch", "main")
            self.run_git(root, "update-ref", "refs/remotes/origin/main", upstream_head)

            freshness = panel.git_upstream_freshness(root)

        self.assertEqual(freshness["status"], "stale")
        self.assertFalse(freshness["fresh"])
        self.assertEqual(freshness["head"], head)
        self.assertEqual(freshness["upstream_head"], upstream_head)
        self.assertEqual(freshness["behind_count"], 1)
        self.assertEqual(freshness["ahead_count"], 0)

    def test_git_upstream_freshness_is_unknown_without_resolvable_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "checkout"
            root.mkdir()
            missing_repo = panel.git_upstream_freshness(root)

            self.run_git(root, "init", "--initial-branch=main")
            self.run_git(root, "config", "user.name", "Business Panel Test")
            self.run_git(root, "config", "user.email", "panel-test@example.invalid")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            self.run_git(root, "add", "tracked.txt")
            self.run_git(root, "commit", "-m", "base")
            missing_upstream = panel.git_upstream_freshness(root)

        self.assertEqual(missing_repo["status"], "unknown")
        self.assertIsNone(missing_repo["fresh"])
        self.assertIn("Git worktree", missing_repo["reason"])
        self.assertEqual(missing_upstream["status"], "unknown")
        self.assertIsNone(missing_upstream["fresh"])
        self.assertIn("configured upstream", missing_upstream["reason"])

    def test_panel_propagates_checkout_freshness_to_local_sections(self) -> None:
        now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
        cases = [
            ("fresh", True, "ok"),
            ("stale", False, "ok"),
            ("unknown", None, "ok"),
        ]
        for freshness_status, fresh, expected_panel_status in cases:
            with self.subTest(freshness_status=freshness_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                content_dir = root / "content" / "posts"
                log_dir = root / "pipeline" / "logs"
                content_dir.mkdir(parents=True)
                log_dir.mkdir(parents=True)
                (content_dir / "fresh.md").write_text(
                    "---\n"
                    "title: Fresh article\n"
                    f"date: {(now - timedelta(hours=1)).isoformat()}\n"
                    "categories:\n"
                    "  - Kotimaa\n"
                    "---\nBody\n",
                    encoding="utf-8",
                )
                (log_dir / "metrics.json").write_text(
                    '[{"timestamp":"2026-08-02T07:30:00+00:00","success":true,"article_count":1,"errors":[]}]',
                    encoding="utf-8",
                )
                freshness = {
                    "status": freshness_status,
                    "fresh": fresh,
                    "reason": f"fixture is {freshness_status}",
                    "head": "a" * 40,
                    "upstream": "origin/main" if freshness_status != "unknown" else None,
                    "upstream_head": "b" * 40 if freshness_status == "stale" else "a" * 40,
                    "behind_count": 3 if freshness_status == "stale" else (0 if fresh else None),
                    "ahead_count": 0 if freshness_status != "unknown" else None,
                    "source": "read-only local Git metadata; no fetch or network access",
                }
                with (
                    patch.object(panel, "PROJECT_DIR", root),
                    patch.object(panel, "CONTENT_DIR", content_dir),
                    patch.object(panel, "PIPELINE_DIR", root / "pipeline"),
                    patch.object(panel, "LOG_DIR", log_dir),
                    patch.object(panel, "QUEUE_DIR", root / "pipeline" / "queues"),
                    patch.object(panel, "git_upstream_freshness", return_value=freshness),
                    patch.object(
                        panel,
                        "production_pipeline_status",
                        return_value=self.validated_production(now, published=1),
                    ),
                ):
                    data = panel.build_panel(now)

            self.assertEqual(data["status"], expected_panel_status)
            self.assertEqual(data["git_upstream_freshness"]["status"], freshness_status)
            self.assertEqual(data["content"]["git_upstream_freshness"]["status"], freshness_status)
            self.assertEqual(data["pipeline"]["git_upstream_freshness"]["status"], freshness_status)
            self.assertEqual(data["queues"]["git_upstream_freshness"]["status"], freshness_status)
            self.assertEqual(data["content"]["article_count_local"], 1)
            self.assertEqual(data["pipeline"]["last_24h"]["article_count"], 1)
            self.assertEqual(
                data["pipeline"]["last_24h"]["article_count_source"],
                "validated production pipeline-status",
            )

    def test_content_summary_excludes_truthy_drafts_from_published_metrics(self) -> None:
        now = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        cases = [
            ("published-missing", "", 1),
            ("published-false", "draft: false\n", 2),
            ("draft-lower", "draft: true\n", 3),
            ("draft-title", "draft: True\n", 4),
            ("draft-upper", "draft: TRUE\n", 5),
            ("draft-yes", "draft: yes\n", 6),
            ("draft-on", "draft: ON\n", 7),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            content_dir = Path(tmp) / "content" / "posts"
            content_dir.mkdir(parents=True)
            for slug, draft_line, hours_ago in cases:
                published = now - timedelta(hours=hours_ago)
                (content_dir / f"{slug}.md").write_text(
                    "---\n"
                    f"title: {slug}\n"
                    f"date: {published.isoformat()}\n"
                    f"{draft_line}"
                    "categories:\n"
                    "  - Kotimaa\n"
                    "---\nBody\n",
                    encoding="utf-8",
                )

            with patch.object(panel, "CONTENT_DIR", content_dir):
                content = panel.content_summary(now)

        self.assertEqual(content["article_count_local"], 2)
        self.assertEqual(content["draft_count_local"], 5)
        self.assertEqual(content["published_last_24h_local"], 2)
        self.assertEqual(content["latest_article"]["slug"], "published-missing")

    def test_effective_ad_config_rejects_incomplete_or_dormant_activation(self) -> None:
        cases = [
            ({"ads_enabled": False, "adsense_id": "ca-test", "ads_consent_revision": 3}, False, 3, 2),
            ({"ads_enabled": True, "adsense_id": "", "ads_consent_revision": 3}, False, 3, 2),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 2}, False, 3, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 3}, True, 3, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 3, "ads_activation_revision": 2}, False, 2, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 3, "ads_activation_revision": 0}, False, 0, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 3, "ads_activation_revision": -1}, False, -1, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": 3, "ads_activation_revision": "invalid"}, False, 0, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test", "ads_consent_revision": "invalid"}, False, 3, 3),
            ({"ads_enabled": True, "adsense_id": "ca-test"}, False, 3, 3),
        ]
        for params, expected, activation_revision, consent_revision in cases:
            with self.subTest(params=params):
                config = panel.effective_ad_config(params)
                self.assertEqual(config["effective_ads_enabled"], expected)
                self.assertEqual(config["activation_revision"], activation_revision)
                self.assertEqual(config["consent_revision"], consent_revision)
                self.assertEqual(config["immutable_activation_floor"], 3)

    def test_effective_ad_config_requires_revision_at_or_above_activation(self) -> None:
        config = panel.effective_ad_config({
            "ads_enabled": True,
            "adsense_id": "ca-test",
            "ads_consent_revision": 3,
            "ads_activation_revision": 4,
        })
        self.assertFalse(config["effective_ads_enabled"])
        self.assertFalse(config["revision_current"])
        self.assertEqual(config["consent_revision"], 3)

    def test_last_24h_article_count_uses_published_content_when_scanner_metrics_are_zero(self) -> None:
        """Local diagnostics retain published content even when production is authoritative."""
        now = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content_dir = root / "content" / "posts"
            log_dir = root / "pipeline" / "logs"
            content_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            for idx in range(2):
                published = now - timedelta(hours=idx + 1)
                (content_dir / f"article-{idx}.md").write_text(
                    "---\n"
                    f"title: Article {idx}\n"
                    f"date: {published.isoformat()}\n"
                    "categories:\n"
                    "  - Kotimaa\n"
                    "---\nBody\n",
                    encoding="utf-8",
                )
            (log_dir / "metrics.json").write_text(
                '[{"timestamp":"2026-05-24T11:50:00+00:00","success":true,"article_count":0,"errors":[]}]',
                encoding="utf-8",
            )
            with (
                patch.object(panel, "PROJECT_DIR", root),
                patch.object(panel, "CONTENT_DIR", content_dir),
                patch.object(panel, "PIPELINE_DIR", root / "pipeline"),
                patch.object(panel, "LOG_DIR", log_dir),
                patch.object(panel, "QUEUE_DIR", root / "pipeline" / "queues"),
                patch.object(
                    panel,
                    "production_pipeline_status",
                    return_value=self.validated_production(now, published=9),
                ),
            ):
                data = panel.build_panel(now)

        self.assertEqual(data["content"]["published_last_24h_local"], 2)
        self.assertEqual(data["pipeline"]["last_24h"]["generated_article_count"], 0)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count_local"], 2)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count_local_source"], "content/posts frontmatter")
        self.assertEqual(data["pipeline"]["last_24h"]["article_count"], 9)
        self.assertEqual(data["pipeline"]["last_24h"]["article_count_source"], "validated production pipeline-status")

    def test_fresh_analytics_evidence_supersedes_stale_log_errors(self) -> None:
        """Fresh redacted GA4/GSC evidence must not be reported as blocked because old log tails contain errors."""
        now = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "pipeline" / "logs"
            status_path = root / "static" / "api" / "analytics-freshness-status.json"
            log_dir.mkdir(parents=True)
            status_path.parent.mkdir(parents=True)
            (log_dir / "daily-traffic-card.log").write_text("old invalid_grant error\nnewer run ok\n", encoding="utf-8")
            (log_dir / "fetch-search-console.log").write_text("old refresh failed\nnewer run got rows\n", encoding="utf-8")
            status_path.write_text(
                '{'
                '"status":"fresh",'
                '"checked_at":"2026-06-01T07:55:00+00:00",'
                '"source_command":"SECRETS_DIR=/home/pertt/.openclaw/workspace/.secrets bash pipeline/check-analytics.sh",'
                '"artifacts":{'
                '"daily_report":{"artifact":"analytics/daily-report.json","fresh":true,"property_id":"529369568","counts":{"daily_pageview_rows":1,"top_pages_7d":10,"search_console_top_queries":10}},'
                '"search_console":{"artifact":"static/api/search-console-data.json","fresh":true,"site":"sc-domain:uutistenlukija.fi","row_count":293},'
                '"oauth_blocker":{"blocked":false}'
                '}'
                '}',
                encoding="utf-8",
            )

            with patch.object(panel, "PROJECT_DIR", root), patch.object(panel, "LOG_DIR", log_dir):
                analytics = panel.analytics_status(now)

        self.assertEqual(analytics["freshness"]["status"], "fresh")
        self.assertEqual(analytics["ga4"]["status"], "fresh")
        self.assertEqual(analytics["gsc"]["status"], "fresh")
        self.assertEqual(analytics["ga4"]["reason"], "fresh GA4 validation artifact present")
        self.assertEqual(analytics["gsc"]["reason"], "fresh Search Console validation artifact present")

    def test_queue_summary_excludes_retention_archives(self) -> None:
        """Archived queue artifacts are evidence, not live backlog."""
        now = datetime(2026, 6, 3, 9, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "pipeline" / "queues" / "staged" / "failed"
            archive = root / "pipeline" / "queues" / "staged" / "failed_archive" / "20260603T090000Z"
            manifests = root / "pipeline" / "queues" / "staged" / "failed_archive" / "manifests"
            legacy_archive = root / "pipeline" / "queues" / "monica" / "archive" / "20260603T090000Z"
            live.mkdir(parents=True)
            archive.mkdir(parents=True)
            manifests.mkdir(parents=True)
            legacy_archive.mkdir(parents=True)
            (live / "current.json").write_text("{}", encoding="utf-8")
            (archive / "old.json").write_text("{}", encoding="utf-8")
            (manifests / "manifest.json").write_text("{}", encoding="utf-8")
            (legacy_archive / "old.json").write_text("{}", encoding="utf-8")

            with patch.object(panel, "QUEUE_DIR", root / "pipeline" / "queues"):
                queues = panel.queue_summary(now)["queues"]

        self.assertEqual(set(queues), {"staged/failed"})
        self.assertEqual(queues["staged/failed"]["count"], 1)

    def test_coordination_summary_reads_workspace_linear_mirror(self) -> None:
        """Business control panel should expose the live OpenClaw/Linear mirror, not only project-local placeholders."""
        now = datetime(2026, 6, 9, 6, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            project = workspace / "projects" / "uutistenlukija"
            project.mkdir(parents=True)
            (workspace / "TASKBOARD.md").write_text(
                "# TASKBOARD.md - Linear OPE mirror/cache\n"
                "Updated: 2026-06-09T06:20:16+00:00\n"
                "Linear OPE is authoritative. This file is a cache/recovery mirror only.\n"
                "- **OPE-9** — Prove pull loop\n"
                "- **OPE-163** — Restore X distribution\n",
                encoding="utf-8",
            )
            (workspace / "agent-health.json").write_text(
                '{'
                '"updatedAt":"2026-06-09T06:20:16+00:00",'
                '"linearOpenIssues":['
                '{"identifier":"OPE-9","title":"Prove pull loop","state":"In Progress","stateType":"started","labels":["lane:automation","owner:felix","verification-required"],"updatedAt":"2026-06-09T06:20:08.442Z"},'
                '{"identifier":"OPE-163","title":"Restore approval-gated X distribution","state":"Todo","stateType":"unstarted","labels":["blocked","needs:approval","needs:perttu","lane:growth","owner:iris"],"updatedAt":"2026-06-07T09:57:34.405Z"}'
                '],'
                '"latestEvidence":{"ownerLaneLabelAudit":{"ok":true,"checkedAt":"2026-06-09T06:20:16+00:00","checkedCount":2,"missingLabelCount":0}},'
                '"agents":{"felix":{"status":"linear_reconciled","state":"coordinating","linearIssue":"OPE-9","lastCheck":"2026-06-09T06:20:16+00:00","currentTask":"Keep OPE-9 open"}}'
                '}',
                encoding="utf-8",
            )

            with patch.object(panel, "PROJECT_DIR", project):
                coordination = panel.local_coordination_placeholders(now)

        self.assertTrue(coordination["items"]["taskboard"]["available"])
        self.assertTrue(coordination["items"]["agent_health"]["available"])
        self.assertEqual(coordination["linear_open_issue_count"], 2)
        self.assertEqual(coordination["active_issue_ids"], ["OPE-9", "OPE-163"])
        self.assertEqual(coordination["blocked_issue_ids"], ["OPE-163"])
        self.assertEqual(coordination["needs_approval_issue_ids"], ["OPE-163"])
        self.assertTrue(coordination["assignment_coverage_ok"])
        self.assertEqual(coordination["owner_issue_counts"], {"owner:felix": 1, "owner:iris": 1})
        self.assertEqual(coordination["items"]["taskboard"]["path"], "workspace:TASKBOARD.md")
        self.assertEqual(coordination["items"]["agent_health"]["summary"]["agents"]["felix"]["linear_issue"], "OPE-9")


if __name__ == "__main__":
    unittest.main()

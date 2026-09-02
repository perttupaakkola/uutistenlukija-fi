#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

try:
    from . import staged_publish
    from . import publisher
    from . import image_gen
    from .image_candidate_guard import PROMPT_VERSION, category_fallback_fields, stock_decision_fields
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import staged_publish
    import publisher
    import image_gen
    from image_candidate_guard import PROMPT_VERSION, category_fallback_fields, stock_decision_fields


def _mock_stock_receipt(article: dict[str, Any], *, provider: str | None = None, accepted: bool = False) -> None:
    if provider is None:
        provider = "unsplash" if staged_publish.get_provider_result(article, "unsplash") is None else "pexels"
    staged_publish.set_provider_result(article, staged_publish.build_provider_result(
        provider=provider,
        attempted=True,
        succeeded=True,
        outcome="accepted" if accepted else "all_policy_rejected",
        reason="candidate_accepted" if accepted else "all_fresh_candidates_rejected",
        query_count=1,
        candidate_count=1,
        fresh_candidate_count=1,
        rejected_count=0 if accepted else 1,
        accepted_count=1 if accepted else 0,
        semantic_accepted=accepted,
        attribution_complete=accepted,
        delivery_mode=("hotlink" if provider == "unsplash" else "download") if accepted else "none",
        delivery_attempted=accepted,
        delivery_succeeded=accepted,
        thumbnail_delivery_succeeded=accepted,
        tracking_attempted=accepted and provider == "unsplash",
        tracking_succeeded=accepted and provider == "unsplash",
    ))


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
        self.cache_root = self.root / "cache"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.patch = patch.object(staged_publish, "STAGED_ROOT", self.root)
        self.cache_patch = patch.object(staged_publish, "PIPELINE_CACHE_DIR", self.cache_root)
        self.patch.start()
        self.cache_patch.start()

    def tearDown(self) -> None:
        self.cache_patch.stop()
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

    def _write_publish_record(self, packet_id: str) -> tuple[Path, dict, dict]:
        article = {
            "title": packet_id,
            "description": f"Kuvaus uutiselle {packet_id}.",
            "content": "sana " * 260,
            "category": "Kotimaa",
            "source_url": f"https://example.test/{packet_id}",
            "monica_packet_id": packet_id,
        }
        data = {
            "article": article,
            "packet": {
                "packet_id": packet_id,
                "category": "Kotimaa",
                "clean_source_blocks": [
                    {
                        "source": "Testi",
                        "source_url": f"https://example.test/{packet_id}",
                        "text": "lähdesana " * 260,
                    }
                ],
            },
            "payload": {"category": "Kotimaa"},
        }
        return self._write("outbox", packet_id, data, age_hours=1), data, article

    def _run_single_packet_scan(self, packet: dict) -> tuple[int, list[str]]:
        article = {
            "title": "Synthetic scheduled scan candidate",
            "description": "Focused scanner admission regression.",
            "link": "https://example.test/ope-447",
            "category_hint": "Kotimaa",
            "research": (
                "[Lähde: Testi | URL: https://example.test/source]\n"
                + "lähdesana " * 100
            ),
        }
        args = Namespace(
            dry_run=False,
            max_ready_age_hours=24,
            max_ready_backlog=150,
            dedup_window=48,
            cooldown_hours=48,
            max_research_candidates=8,
            min_source_words=80,
            max_packets=1,
        )
        with patch.object(staged_publish, "scan_all_feeds", return_value=[article]), \
             patch.object(staged_publish, "poll_firehose", return_value=[]), \
             patch.object(staged_publish, "filter_new_articles", side_effect=lambda candidates: candidates), \
             patch.object(
                 staged_publish,
                 "check_published_duplicates",
                 side_effect=lambda candidates, window_hours: candidates,
             ), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda candidates: candidates), \
             patch.object(staged_publish, "should_skip_staged_cooldown", return_value=False), \
             patch.object(
                 staged_publish,
                 "filter_talous_source_floor_cooldown",
                 side_effect=lambda candidates, hours: (candidates, []),
             ), \
             patch.object(
                 staged_publish,
                 "select_research_candidates",
                 side_effect=lambda candidates, max_candidates, **kwargs: candidates,
             ), \
             patch.object(staged_publish, "enrich_with_research", side_effect=lambda candidates: candidates), \
             patch.object(
                 staged_publish,
                 "annotate_selected_source_evidence",
                 side_effect=lambda candidates: candidates,
             ), \
             patch.object(
                 staged_publish,
                 "select_scan_enqueue_candidates",
                 side_effect=lambda candidates, max_packets: candidates,
             ), \
             patch.object(staged_publish, "record_talous_source_floor_rejections", return_value=[]), \
             patch.object(staged_publish, "build_story_packet", return_value=packet), \
             patch.object(staged_publish, "log") as log_mock:
            result = staged_publish.cmd_scan(args)
        return result, [str(call.args[0]) for call in log_mock.call_args_list]

    def test_cmd_scan_rejects_invalid_built_packets_before_ready_write(self) -> None:
        cases = (
            (
                "selected provenance error",
                {
                    "selected_source_provenance_error": "SYNTHETIC_PRIVATE_DETAIL_447",
                    "source_selection_outcome": "provenance_invalid",
                },
                "selected_source_provenance_error",
                "SYNTHETIC_PRIVATE_DETAIL_447",
            ),
            (
                "unusable selection outcome",
                {
                    "selected_source_provenance_error": "",
                    "source_selection_outcome": "SYNTHETIC_PRIVATE_OUTCOME_447",
                },
                "source_selection_outcome_not_usable",
                "SYNTHETIC_PRIVATE_OUTCOME_447",
            ),
        )
        for index, (label, invalid_fields, expected_reason, private_detail) in enumerate(cases):
            with self.subTest(label=label):
                packet = {
                    "packet_id": f"invalid_packet_{index}",
                    "headline_seed": "Synthetic invalid packet",
                    "link": "https://example.test/ope-447",
                    "source_text": "Synthetic source text",
                    **invalid_fields,
                }
                before = {
                    path.relative_to(self.root).as_posix(): path.read_bytes()
                    for path in sorted(self.root.glob("*/*.json"))
                }

                result, messages = self._run_single_packet_scan(packet)

                after = {
                    path.relative_to(self.root).as_posix(): path.read_bytes()
                    for path in sorted(self.root.glob("*/*.json"))
                }
                diagnostic = "\n".join(messages)
                self.assertEqual(result, 0)
                self.assertEqual(after, before)
                self.assertIn(expected_reason, diagnostic)
                self.assertNotIn(private_detail, diagnostic)

    def test_cmd_scan_backfills_valid_second_after_invalid_top_candidate(self) -> None:
        articles = [
            {
                "title": "Invalid thin Talous top", "link": "https://example.test/top",
                "category_hint": "Talous", "source": "Fixture",
                "research": "[Lähde: Fixture]\n" + "thin " * 37 + "\n[Lähde: Other]\n" + "thin " * 38,
                "research_source": "multi", "story_confidence": 0.85,
                "_selected_source_evidence": {"source_words": 75, "source_blocks": 2},
            },
            {"title": "Valid second", "link": "https://example.test/second", "category_hint": "Kotimaa"},
        ]
        invalid = {
            "packet_id": "invalid-top",
            "clean_source_blocks": [{"source_url": "https://example.test/top", "text": "thin"}],
            "selected_source_provenance_error": "",
            "source_selection_outcome": "usable_source_packet",
        }
        valid = {
            "packet_id": "valid-second",
            "clean_source_blocks": [{
                "source": "Fixture",
                "source_url": "https://example.test/second",
                "text": " ".join(f"source{index}" for index in range(200)),
            }],
            "selected_source_provenance_error": "",
            "source_selection_outcome": "usable_source_packet",
        }
        args = Namespace(
            dry_run=False, max_ready_age_hours=24, max_ready_backlog=150,
            dedup_window=48, cooldown_hours=48, max_research_candidates=8,
            min_source_words=200, max_packets=1,
        )
        with patch.object(staged_publish, "scan_all_feeds", return_value=articles), \
             patch.object(staged_publish, "poll_firehose", return_value=[]), \
             patch.object(staged_publish, "filter_new_articles", side_effect=lambda rows: rows), \
             patch.object(staged_publish, "check_published_duplicates", side_effect=lambda rows, window_hours: rows), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda rows: rows), \
             patch.object(staged_publish, "talous_interim_priority_state", return_value={"active": False, "share": None, "talous_count": 0, "total": 0, "reason": "fixture"}), \
             patch.object(staged_publish, "select_research_candidates", side_effect=lambda rows, max_candidates, **kwargs: rows), \
             patch.object(staged_publish, "enrich_with_research", side_effect=lambda rows: rows) as enrich_mock, \
             patch.object(staged_publish, "annotate_selected_source_evidence", side_effect=lambda rows: rows), \
             patch.object(staged_publish, "build_story_packet", side_effect=[invalid, valid]), \
             patch.object(staged_publish, "select_scan_enqueue_candidates", side_effect=lambda rows, max_packets: rows[:max_packets]) as select_mock:
            self.assertEqual(staged_publish.cmd_scan(args), 0)
            self.assertEqual(staged_publish.cmd_scan(args), 0)
        self.assertEqual([path.name for path in (self.root / "ready").glob("*.json")], ["valid-second.json"])
        self.assertEqual(select_mock.call_args.args[0], [articles[1]])
        self.assertEqual(enrich_mock.call_count, 1)
        invalid_digest = staged_publish.stable_digest(articles[0])
        cache = staged_publish.load_talous_source_floor_cooldown(hours=48)
        self.assertEqual(list(cache), [invalid_digest])
        self.assertEqual(cache[invalid_digest]["reason"], "source_floor_not_met")
        self.assertFalse(any(list((self.root / box).glob("*.json")) for box in ("writing", "outbox", "failed")))

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

    def test_failed_writer_feedback_classifies_near_miss_short_repair(self) -> None:
        record = _record("near-miss", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-near-miss"
        payload = {
            "packet_id": "pkt-near-miss",
            "title": "Lähes valmis artikkeli",
            "content": " ".join(["sana"] * 248),
            "category": "Talous",
        }

        feedback = staged_publish.failed_writer_feedback(record, payload, ["content too short: 248 words"])

        self.assertEqual(feedback["packet_id"], "pkt-near-miss")
        self.assertEqual(feedback["selected_source_words"], 366)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertEqual(feedback["final_word_count"], 248)
        self.assertTrue(feedback["near_miss_short"])
        self.assertEqual(feedback["retry_classification"], "repair_near_miss_short")
        self.assertTrue(feedback["fail_closed"])


    def test_failed_writer_feedback_classifies_high_confidence_209_word_talous_shortfall(self) -> None:
        record = _record("talous-209", source_words=199, blocks=3)
        record["packet"]["packet_id"] = "pkt-talous-209"
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        payload = {
            "packet_id": "pkt-talous-209",
            "title": "Talousartikkeli jäi liian lyhyeksi",
            "content": " ".join(["sana"] * 209),
            "category": "Talous",
        }

        feedback = staged_publish.failed_writer_feedback(record, payload, ["content too short: 209 words"])

        self.assertGreaterEqual(feedback["selected_source_words"], 199)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertEqual(feedback["final_word_count"], 209)
        self.assertTrue(feedback["source_backed"])
        self.assertTrue(feedback["near_miss_short"])
        self.assertEqual(feedback["retry_classification"], "repair_near_miss_short")

    def test_talous_ready_guardrail_fails_promotional_instagram_org_packet(self) -> None:
        record = _record("finanssiala-promo", source_words=145, blocks=2)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.79
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Finanssiala",
            "description": "Kesätyöntekijät ottavat Finanssialalle-Instagram-tilin haltuun. Ota tili seurantaan ja vinkkaa kaverille.",
            "research": "[Lähde: Finanssiala]\nKesätyöntekijät ottavat Finanssialalle-Instagram-tilin haltuun. Ota Finanssialalle-Instagram seurantaan ja vinkkaa kaverille.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "fail")
        self.assertEqual(guard["reason"], "weak_talous_ready_promotional")

    def test_talous_ready_guardrail_fails_borderline_political_entrepreneur_packet(self) -> None:
        record = _record("yrittaja-eduskuntaan", source_words=169, blocks=2)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["headline_seed"] = "Yksi yrittäjä lisää eduskuntaan – Konkari palaa Arkadianmäelle"
        record["packet"]["story_confidence"] = 0.83
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "title": "Yksi yrittäjä lisää eduskuntaan – Konkari palaa Arkadianmäelle",
            "research": "[Lähde: Suomen Yrittäjät]\nPertti Hemmilä nousee eduskuntaan. YRITTÄJÄ, tule mukaan omiesi pariin! Liity Yrittäjiin.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "fail")
        self.assertEqual(guard["reason"], "weak_talous_ready_category_borderline")

    def test_talous_ready_guardrail_keeps_publishable_market_packet(self) -> None:
        record = _record("kamux", source_words=214, blocks=3)
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        record["original_article"].update({
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "description": "Kamuxin liikevaihto laski 12 prosenttia 205 miljoonaan euroon ja bruttokate parani.",
            "research": "[Lähde: Arvopaperi]\nKamuxin liikevaihto laski alkuvuonna 12 prosenttia 205 miljoonaan euroon. Oikaistu liiketulos oli tappiolla. Bruttokate parani.",
        })

        guard = staged_publish.talous_packet_quality_guardrail(record)

        self.assertEqual(guard["action"], "keep")
        self.assertEqual(guard["reason"], "source_quality_ok")


    def test_talous_cooldown_requeues_when_recent_recoverable_failure_exists(self) -> None:
        article = {"title": "talous-recoverable", "link": "https://example.com/talous-recoverable", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-recoverable", source_words=330, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["packet"]["story_confidence"] = 0.98
        failed["packet"]["source_diagnostics"] = {"selected_sources": ["Testi", "Testi", "Testi"]}
        failed["failure"] = "content too short: 225 words"
        failed["writer_failure_feedback"] = {
            "retry_classification": "repair_near_miss_short",
            "selected_source_words": 330,
            "selected_source_blocks": 3,
            "story_confidence": 0.98,
            "final_word_count": 225,
            "issues": ["content too short: 225 words"],
        }
        self._write("failed", "old-talous", failed, age_hours=1)

        self.assertFalse(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_repeated_near_short_failures(self) -> None:
        article = {"title": "talous-repeat", "link": "https://example.com/talous-repeat", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        for idx, words in enumerate([225, 231, 241], start=1):
            failed = _record(f"talous-repeat-{idx}", source_words=330, blocks=3)
            failed["digest"] = digest
            failed["packet"]["category_hint"] = "Talous"
            failed["packet"]["story_confidence"] = 0.98
            failed["packet"]["source_diagnostics"] = {"selected_sources": ["Testi", "Testi", "Testi"]}
            failed["failure"] = f"content too short: {words} words"
            failed["writer_failure_feedback"] = {
                "retry_classification": "repair_near_miss_short",
                "selected_source_words": 330,
                "selected_source_blocks": 3,
                "story_confidence": 0.98,
                "final_word_count": words,
                "issues": [f"content too short: {words} words"],
            }
            self._write("failed", f"failed-talous-repeat-{idx}", failed, age_hours=idx)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_mixed_source_near_short(self) -> None:
        article = {"title": "talous-mixed", "link": "https://example.com/talous-mixed", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-mixed", source_words=360, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["packet"]["story_confidence"] = 0.98
        failed["packet"]["source_diagnostics"] = {"selected_sources": ["Finanssiala", "Yle", "Finanssiala"]}
        failed["failure"] = "content too short: 231 words"
        failed["writer_failure_feedback"] = {
            "retry_classification": "repair_near_miss_short",
            "selected_source_words": 360,
            "selected_source_blocks": 3,
            "story_confidence": 0.98,
            "final_word_count": 231,
            "issues": ["content too short: 231 words"],
        }
        self._write("failed", "failed-talous-mixed", failed, age_hours=1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_writer_runtime_timeout(self) -> None:
        article = {"title": "talous-timeout", "link": "https://example.com/talous-timeout", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-timeout", source_words=283, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["packet"]["story_confidence"] = 0.98
        failed["failure"] = "Monica writer command timed out after 360 seconds"
        failed["writer_failure_feedback"] = staged_publish.failed_writer_feedback(
            failed,
            None,
            [],
            raw_response="Monica writer command timed out after 360 seconds",
        )
        self._write("failed", "failed-talous-timeout", failed, age_hours=1)

        self.assertEqual(failed["writer_failure_feedback"]["retry_classification"], "writer_runtime")
        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_stale_timeout_misclassified_as_invalid_json(self) -> None:
        article = {"title": "talous-timeout-stale", "link": "https://example.com/talous-timeout-stale", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-timeout-stale", source_words=283, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["failure"] = "Monica writer command timed out after 360 seconds"
        failed["writer_failure_feedback"] = {"retry_classification": "writer_invalid_json"}
        self._write("failed", "failed-talous-timeout-stale", failed, age_hours=1)

        self.assertEqual(staged_publish.staged_failed_retry_classification(failed), "writer_runtime")
        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_still_skips_when_digest_already_ready(self) -> None:
        article = {"title": "talous-ready", "link": "https://example.com/talous-ready", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-ready", source_words=220, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["writer_failure_feedback"] = {"retry_classification": "repair_near_miss_short"}
        ready = _record("talous-ready", source_words=220, blocks=3)
        ready["digest"] = digest
        ready["packet"]["category_hint"] = "Talous"
        self._write("failed", "failed-talous-ready", failed, age_hours=1)
        self._write("ready", "ready-talous-ready", ready, age_hours=0.1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_talous_cooldown_does_not_requeue_quality_gate_failure(self) -> None:
        article = {"title": "talous-quality", "link": "https://example.com/talous-quality", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-quality", source_words=360, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["failure"] = "quality_gate_rejected: unsourced numbers"
        failed["quality_gate_feedback"] = {"retry_classification": "fail_closed_quality_gate"}
        self._write("failed", "failed-talous-quality", failed, age_hours=1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))


    def test_failed_writer_feedback_classifies_invalid_json(self) -> None:
        record = _record("bad-json", source_words=111, blocks=4)
        record["packet"]["packet_id"] = "pkt-bad-json"

        feedback = staged_publish.failed_writer_feedback(record, None, [], raw_response="not valid json")

        self.assertEqual(feedback["packet_id"], "pkt-bad-json")
        self.assertEqual(feedback["retry_classification"], "writer_invalid_json")
        self.assertEqual(feedback["final_word_count"], 0)
        self.assertTrue(feedback["fail_closed"])

    def test_talous_cooldown_does_not_requeue_invalid_json_noise(self) -> None:
        article = {"title": "talous-bad-json", "link": "https://example.com/talous-bad-json", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-bad-json", source_words=283, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["failure"] = "Monica response did not contain valid JSON object"
        failed["writer_failure_feedback"] = {"retry_classification": "writer_invalid_json"}
        self._write("failed", "failed-talous-bad-json", failed, age_hours=1)

        self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=48))

    def test_quality_gate_reject_quarantine_records_fail_closed_feedback(self) -> None:
        record = _record("rich-quality-reject", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-rich-quality"
        record["packet"]["category_hint"] = "Talous"
        record["packet"]["story_confidence"] = 0.98
        article = {
            "title": "Trump asetti EU:lle määräajan tullikiistan ratkaisemiseksi",
            "description": "Trump uhkaa EU:ta uusilla tulleilla, ellei sopua synny.",
            "content": (
                "Yhdysvaltain presidentti Donald Trump vaatii EU:lta ratkaisua 4. heinäkuuta mennessä ja uhkaa "
                "10, 15, 30 ja 50 prosentin tulleilla. Neuvottelut jatkuvat Brysselissä, mutta päätöksiä ei vielä ole.\n\n"
                "## Neuvottelut jatkuvat\n\n"
                "EU:n edustajat arvioivat tilannetta ja korostavat, että sopimuksen toimeenpano vaatii jäsenmaiden hyväksyntää."
            ),
            "category": "Talous",
            "source_text": "Trump ja EU neuvottelevat tulleista ilman näitä tarkkoja lukuja.",
            "source_url": "https://example.com/story",
        }
        data = {**record, "article": article, "payload": {"packet_id": "pkt-rich-quality"}}
        path = self._write("outbox", "pkt-rich-quality", data)

        moved = staged_publish.quarantine_rejected_outbox([(path, data)], [article])

        self.assertEqual(moved, 1)
        failed = json.loads((self.root / "failed" / "pkt-rich-quality.json").read_text(encoding="utf-8"))
        feedback = failed["quality_gate_feedback"]
        self.assertEqual(feedback["packet_id"], "pkt-rich-quality")
        self.assertEqual(feedback["category"], "Talous")
        self.assertGreaterEqual(feedback["selected_source_words"], 360)
        self.assertEqual(feedback["selected_source_blocks"], 3)
        self.assertFalse(feedback["repair_eligible"])
        self.assertEqual(feedback["retry_classification"], "fail_closed_quality_gate")
        self.assertTrue(any("central unsourced number" in reason for reason in feedback["quality_reasons"]))
        self.assertIn("quality_gate_rejected", failed["failure"])

    def test_quality_gate_accepts_source_date_rephrased_as_finnish_ordinal(self) -> None:
        article = {
            "title": "Laura Welling nimitettiin Finanssiala ry:n johtajaksi",
            "description": "Laura Welling aloittaa tehtävässä syyskuussa 2026.",
            "content": (
                "Laura Welling aloittaa Finanssiala ry:n johtajana 1. syyskuuta 2026. "
                "Hän tulee tehtävään Taina Ahvenjärven tilalle ja liittyy samalla FA:n johtoryhmään.\n\n"
                "## Tausta\n\n"
                "Lähde kertoo aloituspäivän muodossa 1.9.2026, jonka toimituksellinen teksti "
                "voi kirjoittaa suomenkielisenä päivämääränä ilman, että päivä muuttuu uudeksi luvuksi. "
                "Tarkistus ei saa koventaa tällaista lähteistettyä päivämäärää keskiseksi luvuksi."
            ),
            "category": "Talous",
            "image": "https://example.com/img.jpg",
            "source_text": "Laura Welling aloittaa tehtävässään 1.9.2026 ja on osa FA:n johtoryhmää.",
            "source_url": "https://example.com/story",
        }

        breakdown = staged_publish.score_article(article)

        self.assertFalse(any("central unsourced number" in reason for reason in breakdown.hard_fails))
        self.assertFalse(any("unsourced_numbers: 1" in reason for reason in breakdown.soft_warnings))

    def test_enrich_images_uses_unsplash_for_missing_article_images(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous", "content": "sisältö"}]

        def fake_unsplash(batch, delay=0):
            batch[0]["image"] = "https://images.unsplash.com/photo-test"
            batch[0]["image_thumb"] = "https://images.unsplash.com/photo-test-thumb"
            batch[0]["image_alt"] = "Kuvaton artikkeli"
            batch[0]["image_source"] = "unsplash"
            batch[0]["image_category_fallback"] = False
            _mock_stock_receipt(batch[0], provider="unsplash", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key"}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=fake_unsplash), \
             patch.object(staged_publish, "record_success") as success:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 1)
        self.assertEqual(summary["missing"], 0)
        self.assertEqual(articles[0]["image"], "https://images.unsplash.com/photo-test")
        success.assert_called_with("unsplash")

    def test_invalid_stock_receipt_cannot_retain_image_or_stop_next_provider(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous", "content": "sisältö"}]

        def impossible_unsplash_acceptance(batch, delay=0):
            batch[0].update({
                "image": "https://images.unsplash.com/photo-unverified?w=1080",
                "image_thumb": "https://images.unsplash.com/photo-unverified?w=400",
                "image_source": "unsplash",
                "image_source_url": "https://unsplash.com/photos/unverified",
                "image_category_fallback": False,
            })
            # Missing semantic, attribution, delivery, and tracking facts: the
            # receipt normalizer must turn this impossible acceptance into a fault.
            staged_publish.set_provider_result(batch[0], staged_publish.build_provider_result(
                provider="unsplash",
                attempted=True,
                succeeded=True,
                outcome="accepted",
                reason="candidate_accepted",
                accepted_count=1,
            ))
            return batch

        def pexels_rescue(batch, delay=0):
            self.assertNotIn("image", batch[0])
            batch[0].update({
                "image": "/images/articles/pexels-rescue.jpg",
                "image_thumb": "/images/articles/pexels-rescue-thumb.jpg",
                "image_source": "pexels",
                "image_category_fallback": False,
            })
            _mock_stock_receipt(batch[0], provider="pexels", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "key",
            "PEXELS_API_KEY": "key",
            "KIE_API_KEY": "",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=impossible_unsplash_acceptance,
        ), patch.object(
            staged_publish,
            "pexels_fetch_images",
            side_effect=pexels_rescue,
        ) as pexels_fetch:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        pexels_fetch.assert_called_once()
        self.assertEqual(articles[0]["image"], "/images/articles/pexels-rescue.jpg")
        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 0)
        self.assertEqual(summary["pexels"], 1)
        self.assertEqual(summary["missing"], 0)
        unsplash_receipt = staged_publish.get_provider_result(articles[0], "unsplash")
        self.assertEqual(unsplash_receipt["outcome"], "provider_fault")
        self.assertEqual(unsplash_receipt["reason"], "invalid_acceptance_receipt")
        self.assertEqual(unsplash_receipt["accepted_count"], 0)

    def test_unknown_remote_image_cannot_bypass_verified_enrichment(self) -> None:
        articles = [{
            "title": "Lähteestä yhdistetty artikkeli",
            "category": "Kotimaa",
            "image": "https://attacker.invalid/unvetted.jpg",
            "image_thumb": "https://attacker.invalid/unvetted-thumb.jpg",
            "image_source_url": "https://attacker.invalid/source",
            "image_candidate_id": "unvetted-candidate",
            "image_category_fallback": False,
        }]

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "",
        }, clear=False):
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        self.assertEqual(summary["images"], 0)
        self.assertEqual(summary["category_fallback"], 1)
        self.assertEqual(summary["missing"], 1)
        self.assertTrue(articles[0]["image_category_fallback"])
        self.assertEqual(articles[0]["image_source"], "category_fallback")
        self.assertEqual(articles[0]["image"], "/images/categories/kotimaa.jpg")
        self.assertNotIn("image_candidate_id", articles[0])
        self.assertNotIn("attacker.invalid", str(articles[0]))

    def test_stock_receipt_cannot_bless_artifact_from_wrong_origin(self) -> None:
        articles = [{"title": "Väärään alkuperään sidottu kuva", "category": "Kotimaa"}]

        def wrong_origin_unsplash(batch, delay=0):
            batch[0].update({
                "image": "https://attacker.invalid/unvetted.jpg",
                "image_thumb": "https://attacker.invalid/unvetted-thumb.jpg",
                "image_source": "unsplash",
                "image_category_fallback": False,
            })
            _mock_stock_receipt(batch[0], provider="unsplash", accepted=True)
            return batch

        def pexels_rescue(batch, delay=0):
            self.assertNotIn("image", batch[0])
            batch[0].update({
                "image": "/images/articles/origin-rescue.jpg",
                "image_thumb": "/images/articles/origin-rescue-thumb.jpg",
                "image_source": "pexels",
                "image_category_fallback": False,
            })
            _mock_stock_receipt(batch[0], provider="pexels", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "key",
            "PEXELS_API_KEY": "key",
            "KIE_API_KEY": "",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=wrong_origin_unsplash,
        ), patch.object(
            staged_publish,
            "pexels_fetch_images",
            side_effect=pexels_rescue,
        ) as pexels_fetch:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        pexels_fetch.assert_called_once()
        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 0)
        self.assertEqual(summary["pexels"], 1)
        self.assertEqual(articles[0]["image"], "/images/articles/origin-rescue.jpg")
        self.assertNotIn("attacker.invalid", str(articles[0]))
        receipt = staged_publish.get_provider_result(articles[0], "unsplash")
        self.assertEqual(receipt["outcome"], "provider_fault")
        self.assertEqual(receipt["reason"], "provider_artifact_mismatch")
        self.assertEqual(receipt["accepted_count"], 0)

    def test_inbound_complete_stock_receipt_cannot_self_authorize_image(self) -> None:
        article = {
            "title": "Monican toimittama kuva",
            "category": "Kotimaa",
            "image": "https://images.unsplash.com/photo-inbound?w=1080",
            "image_thumb": "https://images.unsplash.com/photo-inbound?w=400",
            "image_source": "unsplash",
            "image_candidate_id": "inbound",
            "image_category_fallback": False,
            image_gen.IMAGE_TERMINAL_REASONS_FIELD: [{
                "schema": image_gen.IMAGE_TERMINAL_SCHEMA,
                "stage": "stock",
                "provider": "unsplash",
                "reason": "forged_acceptance",
                "outcome": "accepted",
                "provider_fault": False,
                "provider_attempted": True,
                "provider_succeeded": True,
            }],
        }
        _mock_stock_receipt(article, provider="unsplash", accepted=True)
        articles = [article]

        def current_unsplash(batch, delay=0):
            self.assertNotIn("image", batch[0])
            self.assertIsNone(staged_publish.get_provider_result(batch[0], "unsplash"))
            self.assertNotIn(image_gen.GENERATION_TERMINAL_FIELD, batch[0])
            self.assertNotIn(image_gen.IMAGE_TERMINAL_REASONS_FIELD, batch[0])
            batch[0].update({
                "image": "https://images.unsplash.com/photo-current?w=1080",
                "image_thumb": "https://images.unsplash.com/photo-current?w=400",
                "image_source": "unsplash",
                "image_candidate_id": "current",
                "image_category_fallback": False,
            })
            _mock_stock_receipt(batch[0], provider="unsplash", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "key",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=current_unsplash,
        ) as fetch:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0)

        fetch.assert_called_once()
        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 1)
        self.assertEqual(article["image_candidate_id"], "current")
        self.assertNotIn("forged_acceptance", str(article))

    def test_inbound_generated_terminal_cannot_self_authorize_local_paths(self) -> None:
        article = {
            "title": "Monican generoitu kuva",
            "category": "Kotimaa",
            "image": "/images/articles/inbound-generated.jpg",
            "image_thumb": "/images/articles/inbound-generated.jpg",
            "image_source": "generated",
            "image_candidate_id": "/images/articles/inbound-generated.jpg",
            "image_category_fallback": False,
        }
        image_gen.set_generation_terminal(
            article,
            image_gen.build_image_terminal_reason(
                stage="generated",
                reason=image_gen.REASON_ACCEPTED,
                outcome="accepted",
                provider_attempted=True,
                provider_succeeded=True,
            ),
        )
        article[image_gen.IMAGE_TERMINAL_REASONS_FIELD][0]["forged"] = True
        articles = [article]

        def current_unsplash(batch, delay=0):
            self.assertNotIn("image", batch[0])
            self.assertNotIn(image_gen.GENERATION_TERMINAL_FIELD, batch[0])
            self.assertNotIn(image_gen.IMAGE_TERMINAL_REASONS_FIELD, batch[0])
            batch[0].update({
                "image": "https://images.unsplash.com/photo-current-generated?w=1080",
                "image_thumb": "https://images.unsplash.com/photo-current-generated?w=400",
                "image_source": "unsplash",
                "image_candidate_id": "current-generated",
                "image_category_fallback": False,
            })
            _mock_stock_receipt(batch[0], provider="unsplash", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "key",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=current_unsplash,
        ) as fetch:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0)

        fetch.assert_called_once()
        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["unsplash"], 1)
        self.assertEqual(article["image_candidate_id"], "current-generated")
        self.assertNotIn("forged", str(article))

    def test_stock_batch_exception_preserves_completed_receipts_images_and_count(self) -> None:
        cases = (
            (
                "unsplash",
                "unsplash_fetch_images",
                {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "", "KIE_API_KEY": ""},
                "https://images.unsplash.com/photo-accepted",
            ),
            (
                "pexels",
                "pexels_fetch_images",
                {"UNSPLASH_ACCESS_KEY": "", "PEXELS_API_KEY": "key", "KIE_API_KEY": ""},
                "/images/articles/pexels-accepted.jpg",
            ),
        )
        for provider, fetch_name, environment, accepted_image in cases:
            with self.subTest(provider=provider):
                articles = [
                    {"title": "Hyväksytty kuva", "category": "Kotimaa"},
                    {"title": "Valmis hylkäys", "category": "Kotimaa"},
                    {"title": "Kesken jäänyt", "category": "Kotimaa"},
                ]

                def partial_stock(batch, delay=0):
                    batch[0]["image"] = accepted_image
                    batch[0]["image_thumb"] = accepted_image
                    batch[0]["image_source"] = provider
                    batch[0]["image_category_fallback"] = False
                    _mock_stock_receipt(batch[0], provider=provider, accepted=True)
                    _mock_stock_receipt(batch[1], provider=provider, accepted=False)
                    raise RuntimeError("synthetic batch failure")

                with patch.dict(staged_publish.os.environ, environment, clear=False), \
                     patch.object(staged_publish, "should_skip", return_value=(False, None)), \
                     patch.object(staged_publish, fetch_name, side_effect=partial_stock), \
                     patch.object(staged_publish, "record_failure") as failure:
                    summary = staged_publish.enrich_images_for_articles(
                        articles,
                        unsplash_delay=0,
                        pexels_delay=0,
                    )

                self.assertEqual(summary["images"], 1)
                self.assertEqual(summary[provider], 1)
                self.assertEqual(articles[0]["image"], accepted_image)
                self.assertEqual(
                    staged_publish.get_provider_result(articles[0], provider)["outcome"],
                    "accepted",
                )
                self.assertEqual(
                    staged_publish.get_provider_result(articles[0], provider)["accepted_count"],
                    1,
                )
                self.assertEqual(
                    staged_publish.get_provider_result(articles[1], provider)["outcome"],
                    "all_policy_rejected",
                )
                self.assertEqual(
                    staged_publish.get_provider_result(articles[2], provider)["outcome"],
                    "provider_fault",
                )
                self.assertEqual(summary["provider_outcomes"][provider], {
                    "accepted": 1,
                    "all_policy_rejected": 1,
                    "provider_fault": 1,
                })
                failure.assert_called_once_with(provider)

    def test_enrich_images_does_not_mark_policy_rejection_as_provider_failure(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous", "content": "sisältö"}]

        def rejected_stock(batch, delay=0):
            batch[0].update(staged_publish.category_fallback_fields("Talous", reason="stock rejected"))
            _mock_stock_receipt(batch[0])
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "", "KIE_API_KEY": ""}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "record_failure") as failure:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["unsplash"], 0)
        self.assertEqual(summary["category_fallback"], 1)
        failure.assert_not_called()

    def test_stock_compliance_failures_are_provider_runtime_terminals(self) -> None:
        for outcome in ("delivery_failed", "tracking_failed", "attribution_incomplete"):
            with self.subTest(outcome=outcome):
                article: dict[str, Any] = {}
                staged_publish.set_provider_result(
                    article,
                    staged_publish.build_provider_result(
                        provider="unsplash",
                        attempted=True,
                        succeeded=True,
                        outcome=outcome,
                        reason=f"synthetic_{outcome}",
                        fault_count=1,
                    ),
                )

                staged_publish.capture_stock_provider_result(article, "unsplash")

                terminals = article[image_gen.IMAGE_TERMINAL_REASONS_FIELD]
                self.assertEqual(len(terminals), 1)
                self.assertEqual(terminals[0]["outcome"], outcome)
                self.assertEqual(terminals[0]["reason"], image_gen.REASON_PROVIDER_RUNTIME)
                self.assertTrue(terminals[0]["provider_fault"])

    def test_stock_compliance_failure_updates_provider_backoff_as_failure(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Kotimaa"}]

        def compliance_failure(batch, delay=0):
            batch[0].update(category_fallback_fields(
                "Kotimaa",
                reason="provider delivery failed",
            ))
            staged_publish.set_provider_result(
                batch[0],
                staged_publish.build_provider_result(
                    provider="unsplash",
                    attempted=True,
                    succeeded=True,
                    outcome="delivery_failed",
                    reason="hero_or_thumbnail_delivery_unavailable",
                    fault_count=1,
                ),
            )
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "key",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=compliance_failure,
        ), patch.object(staged_publish, "record_failure") as failure, patch.object(
            staged_publish,
            "record_success",
        ) as success:
            staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        failure.assert_called_once_with("unsplash")
        success.assert_not_called()

    def test_enrich_images_records_each_stock_provider_policy_attempt(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous", "content": "sisältö"}]

        def rejected_stock(batch, delay=0):
            batch[0].update(staged_publish.category_fallback_fields("Talous", reason="stock rejected"))
            _mock_stock_receipt(batch[0])
            return batch

        with patch.dict(
            staged_publish.os.environ,
            {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "key", "KIE_API_KEY": ""},
            clear=False,
        ), patch.object(staged_publish, "should_skip", return_value=(False, None)), patch.object(
            staged_publish,
            "unsplash_fetch_images",
            side_effect=rejected_stock,
        ), patch.object(
            staged_publish,
            "pexels_fetch_images",
            side_effect=rejected_stock,
        ):
            staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        terminal_rows = articles[0].get(image_gen.IMAGE_TERMINAL_REASONS_FIELD) or []
        stock_rows = [
            row
            for row in terminal_rows
            if isinstance(row, dict) and row.get("stage") == "stock"
        ]
        self.assertEqual(
            [
                (row.get("provider"), row.get("provider_attempted"), row.get("provider_succeeded"))
                for row in stock_rows
            ],
            [("unsplash", True, True), ("pexels", True, True)],
        )
        self.assertTrue(all(row.get("reason") == image_gen.REASON_STOCK_REJECTION for row in stock_rows))

    def test_enrich_images_clears_category_fallback_before_pexels_rescue(self) -> None:
        articles = [{"title": "Fallback artikkeli", "category": "Kotimaa", "image": "/images/categories/kotimaa.jpg", "image_category_fallback": True}]

        def fake_pexels(batch, delay=0):
            self.assertNotIn("image", batch[0])
            batch[0]["image"] = "/images/articles/fallback-hero.jpg"
            batch[0]["image_thumb"] = "/images/articles/fallback-thumb.jpg"
            batch[0]["image_source"] = "pexels"
            batch[0]["image_category_fallback"] = False
            _mock_stock_receipt(batch[0], provider="pexels", accepted=True)
            return batch

        with patch.dict(staged_publish.os.environ, {"PEXELS_API_KEY": "key", "UNSPLASH_ACCESS_KEY": ""}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "pexels_fetch_images", side_effect=fake_pexels):
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["pexels"], 1)
        self.assertEqual(articles[0]["image"], "/images/articles/fallback-hero.jpg")
        self.assertFalse(articles[0]["image_category_fallback"])

    def test_sync_image_provider_keys_refreshes_kie_module_key(self) -> None:
        image_module_globals = staged_publish.generate_images_for_articles.__globals__
        old_key = image_module_globals.get("KIE_API_KEY", "")
        try:
            image_module_globals["KIE_API_KEY"] = ""
            with patch.dict(staged_publish.os.environ, {"KIE_API_KEY": "kie-test-key"}, clear=False):
                staged_publish.sync_image_provider_keys()
            self.assertEqual(image_module_globals["KIE_API_KEY"], "kie-test-key")
        finally:
            image_module_globals["KIE_API_KEY"] = old_key

    def test_enrich_images_uses_generated_fallback_after_rejected_stock(self) -> None:
        articles = [{"title": "Sääartikkeli", "category": "Kotimaa", "content": "aurinkoinen sää"}]

        def rejected_stock(batch, delay=0):
            batch[0].update(staged_publish.category_fallback_fields("Kotimaa", reason="stock rejected"))
            _mock_stock_receipt(batch[0])
            return batch

        def generated(batch, max_total_sec=180):
            batch[0]["image"] = "/images/articles/generated.jpg"
            batch[0]["image_thumb"] = "/images/articles/generated.jpg"
            batch[0]["image_source"] = "generated"
            batch[0]["image_source_type"] = "generated_editorial"
            batch[0]["image_decision_reason"] = "stock candidates unavailable or rejected"
            batch[0]["image_category_fallback"] = False
            batch[0]["image_decision"] = {"source": "generated", "accepted": True}
            image_gen.set_generation_terminal(
                batch[0],
                image_gen.build_image_terminal_reason(
                    stage="generated",
                    reason=image_gen.REASON_ACCEPTED,
                    outcome="accepted",
                    provider_attempted=True,
                    provider_succeeded=True,
                ),
            )
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "key", "KIE_API_KEY": "key"}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "pexels_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "generate_images_for_articles", side_effect=generated):
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["category_fallback"], 0)
        self.assertEqual(articles[0]["image"], "/images/articles/generated.jpg")
        self.assertEqual(articles[0]["image_source"], "generated")
        self.assertEqual(articles[0]["image_source_type"], "generated_editorial")
        self.assertIn("stock candidates", articles[0]["image_decision_reason"])

    def test_generated_batch_exception_preserves_completed_terminals_images_and_count(self) -> None:
        articles = [
            {"title": "Hyväksytty generoitu kuva", "category": "Kotimaa"},
            {"title": "Valmis visuaalinen hylkäys", "category": "Kotimaa"},
            {"title": "Generoimatta jäänyt", "category": "Kotimaa"},
        ]

        def partial_generation(batch, max_total_sec=180):
            batch[0].update({
                "image": "/images/articles/generated-accepted.jpg",
                "image_thumb": "/images/articles/generated-accepted.jpg",
                "image_source": "generated",
                "image_source_type": "generated_editorial",
                "image_category_fallback": False,
            })
            image_gen.set_generation_terminal(
                batch[0],
                image_gen.build_image_terminal_reason(
                    stage="generated",
                    reason=image_gen.REASON_ACCEPTED,
                    outcome="accepted",
                    provider_attempted=True,
                    provider_succeeded=True,
                ),
            )
            image_gen.set_generation_terminal(
                batch[1],
                image_gen.build_image_terminal_reason(
                    stage="generated",
                    reason=image_gen.REASON_VISUAL_REJECT,
                    outcome="policy_reject",
                    provider_attempted=True,
                    provider_succeeded=True,
                ),
            )
            raise RuntimeError("synthetic generation batch failure")

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "key",
        }, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "generate_images_for_articles", side_effect=partial_generation), \
             patch.object(staged_publish, "record_failure") as failure:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        self.assertEqual(summary["images"], 1)
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(articles[0]["image"], "/images/articles/generated-accepted.jpg")
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_ACCEPTED,
        )
        self.assertEqual(
            articles[1][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )
        self.assertEqual(
            articles[2][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_PROVIDER_RUNTIME,
        )
        self.assertEqual(summary["generated_terminal_reasons"], {
            image_gen.REASON_ACCEPTED: 1,
            image_gen.REASON_PROVIDER_RUNTIME: 1,
            image_gen.REASON_VISUAL_REJECT: 1,
        })
        failure.assert_called_once_with("kie_api")

    def test_generated_exception_cannot_retain_unverified_partial_artifact(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Kotimaa"}]

        def partial_generation(batch, max_total_sec=180):
            batch[0].update({
                "image": "/images/generated/unverified.png",
                "image_thumb": "/images/generated/unverified.png",
                "image_source": "generated",
                "image_source_type": "generated_editorial",
                "image_category_fallback": False,
            })
            raise RuntimeError("synthetic generation failure after mutation")

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "key",
        }, clear=False), patch.object(
            staged_publish,
            "should_skip",
            return_value=(False, None),
        ), patch.object(
            staged_publish,
            "generate_images_for_articles",
            side_effect=partial_generation,
        ), patch.object(staged_publish, "record_failure") as failure:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        failure.assert_called_once_with("kie_api")
        self.assertEqual(summary["images"], 0)
        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["category_fallback"], 1)
        self.assertEqual(summary["missing"], 1)
        self.assertTrue(articles[0]["image_category_fallback"])
        self.assertEqual(articles[0]["image_source"], "category_fallback")
        self.assertNotEqual(articles[0]["image"], "/images/generated/unverified.png")
        terminal = articles[0][image_gen.GENERATION_TERMINAL_FIELD]
        self.assertEqual(terminal["outcome"], "provider_fault")
        self.assertEqual(terminal["reason"], image_gen.REASON_PROVIDER_RUNTIME)

    def test_enrich_images_uses_category_fallback_when_generated_visual_judge_fails(self) -> None:
        articles = [{"title": "Sääartikkeli", "category": "Kotimaa", "content": "aurinkoinen sää"}]

        def rejected_stock(batch, delay=0):
            batch[0].update(staged_publish.category_fallback_fields("Kotimaa", reason="stock rejected"))
            _mock_stock_receipt(batch[0])
            return batch

        def rejected_generated(batch, max_total_sec=180):
            batch[0].update(staged_publish.category_fallback_fields("Kotimaa", reason="generated visual judge rejected"))
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "key", "KIE_API_KEY": "key"}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "pexels_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "generate_images_for_articles", side_effect=rejected_generated):
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["category_fallback"], 1)
        self.assertEqual(articles[0]["image_source"], "category_fallback")

    def test_enrich_images_uses_neutral_fallback_when_generation_unavailable(self) -> None:
        articles = [{"title": "Sääartikkeli", "category": "Kotimaa", "content": "aurinkoinen sää"}]

        def rejected_stock(batch, delay=0):
            batch[0].update(staged_publish.category_fallback_fields("Kotimaa", reason="stock rejected"))
            _mock_stock_receipt(batch[0])
            return batch

        with patch.dict(staged_publish.os.environ, {"UNSPLASH_ACCESS_KEY": "key", "PEXELS_API_KEY": "key", "KIE_API_KEY": ""}, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "unsplash_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "pexels_fetch_images", side_effect=rejected_stock), \
             patch.object(staged_publish, "generate_images_for_articles") as generated:
            summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

        generated.assert_not_called()
        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["category_fallback"], 1)
        self.assertTrue(articles[0]["image_category_fallback"])
        self.assertEqual(articles[0]["image_source"], "category_fallback")
        self.assertEqual(articles[0]["image_source_type"], "category_fallback")
        self.assertEqual(articles[0]["image_decision_reason"], "final category fallback after key_unavailable")
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_KEY_UNAVAILABLE,
        )
        terminal_rows = cast(
            list[dict[str, Any]],
            articles[0][image_gen.IMAGE_TERMINAL_REASONS_FIELD],
        )
        self.assertEqual(
            [row["reason"] for row in terminal_rows],
            [
                image_gen.REASON_STOCK_REJECTION,
                image_gen.REASON_STOCK_REJECTION,
                image_gen.REASON_KEY_UNAVAILABLE,
                image_gen.REASON_CATEGORY_FALLBACK,
            ],
        )
        self.assertEqual(
            [row.get("provider") for row in terminal_rows[:2]],
            ["unsplash", "pexels"],
        )

    def test_kie_generated_fallback_is_one_attempt_and_persists_evidence(self) -> None:
        articles = [{
            "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
            "category": "Talous",
            "slug": "veneenkorjaus",
            "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
            "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
        }]
        prompt = "Boat repair workshop. Avoid: generic person portrait or lookalike."
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            prompt,
            terminal,
        )

        with patch.object(image_gen, "generate_article_image", return_value=result) as generated, \
             patch.object(image_gen, "_generated_image_local_path", return_value="/decoded.jpg"), \
             patch.object(
                 image_gen,
                 "_analyze_generated_pixels",
                 return_value={"description": "boat repair workshop and small craft restoration"},
             ):
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        generated.assert_called_once()
        self.assertEqual(articles[0]["image_source"], "generated")
        self.assertEqual(articles[0]["image_source_type"], "generated_editorial")
        self.assertEqual(articles[0]["image_provider"], "kie.ai")
        self.assertEqual(articles[0]["image_model"], "z-image")
        self.assertEqual(articles[0]["image_prompt_version"], PROMPT_VERSION)
        self.assertGreaterEqual(articles[0]["image_visual_judge_score"], 45)
        self.assertEqual(articles[0]["image_generation_prompt"], prompt)
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_ACCEPTED,
        )

    def test_generated_prompt_is_not_pixel_semantic_evidence(self) -> None:
        articles = [{
            "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
            "category": "Talous",
            "slug": "veneenkorjaus",
            "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
            "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
        }]
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            "Required: boat repair. Avoid: generic person portrait or lookalike.",
            terminal,
            pixel_semantics={"description": "boat repair workshop"},
        )

        with patch.object(image_gen, "generate_article_image", return_value=result), \
             patch.object(image_gen, "_generated_image_local_path", return_value="/decoded.jpg"), \
             patch.object(
                 image_gen,
                 "_analyze_generated_pixels",
                 return_value={"description": "glass skyscraper office tower"},
             ):
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        self.assertNotIn("image", articles[0])
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )

    def test_generated_candidate_fails_closed_when_pixel_analyzer_is_unavailable(self) -> None:
        articles = [{
            "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
            "category": "Talous",
            "slug": "veneenkorjaus",
            "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
            "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
        }]
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            "Required: boat repair. Avoid: generic person portrait or lookalike.",
            terminal,
        )

        with patch.object(image_gen, "generate_article_image", return_value=result), \
             patch.object(image_gen, "_generated_image_local_path", return_value="/decoded.jpg"), \
             patch.object(
                 image_gen,
                 "_analyze_generated_pixels",
                 side_effect=RuntimeError("analyzer unavailable"),
             ):
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        self.assertNotIn("image", articles[0])
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )
        self.assertFalse(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["provider_fault"],
        )

    def test_cached_generated_image_rejects_misleading_exif_without_pixel_verdict(self) -> None:
        from PIL import Image

        image_dir = self.root / "generated-images"
        rejected_dir = self.root / "rejected-generated-images"
        image_dir.mkdir()
        image_path = image_dir / "veneenkorjaus.jpg"
        exif = Image.Exif()
        exif[270] = "boat repair workshop and small craft restoration"
        Image.new("RGB", (160, 90), "navy").save(image_path, exif=exif)
        articles = [{
            "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
            "category": "Talous",
            "slug": "veneenkorjaus",
            "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
            "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
        }]

        with patch.object(image_gen, "IMAGE_DIR", str(image_dir)), \
             patch.object(image_gen, "REJECTED_IMAGE_DIR", str(rejected_dir)), \
             patch.object(image_gen, "_kie_request") as provider:
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        provider.assert_not_called()
        self.assertNotIn("image", articles[0])
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )
        self.assertFalse(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["provider_fault"],
        )
        self.assertFalse(image_path.exists())
        self.assertTrue((rejected_dir / image_path.name).exists())

    def test_generated_visual_reject_quarantines_download_before_cache_reuse(self) -> None:
        image_dir = self.root / "generated-images"
        rejected_dir = self.root / "rejected-generated-images"
        image_dir.mkdir()
        image_path = image_dir / "veneenkorjaus.jpg"
        image_path.write_bytes(b"rejected generated image")
        articles = [{
            "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
            "category": "Talous",
            "slug": "veneenkorjaus",
            "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
            "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
        }]
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            "Required: boat repair. Avoid: generic person portrait or lookalike.",
            terminal,
        )

        with patch.object(image_gen, "IMAGE_DIR", str(image_dir)), \
             patch.object(
                 image_gen,
                 "REJECTED_IMAGE_DIR",
                 str(rejected_dir),
                 create=True,
             ), \
             patch.object(image_gen, "generate_article_image", return_value=result):
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        self.assertFalse(image_path.exists())
        self.assertTrue((rejected_dir / image_path.name).exists())
        self.assertNotIn("image", articles[0])
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )
        with patch.object(image_gen, "IMAGE_DIR", str(image_dir)), \
             patch.object(
                 image_gen,
                 "_kie_request",
                 return_value={"data": {}},
             ) as provider:
            retry = image_gen.generate_article_image(
                articles[0]["title"],
                articles[0]["category"],
                articles[0]["slug"],
            )

        provider.assert_called_once()
        self.assertIsNone(retry.image_path)

    def test_generated_visual_reject_delays_before_next_provider_attempt(self) -> None:
        articles = [
            {
                "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
                "category": "Talous",
                "slug": "veneenkorjaus-ensimmainen",
                "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
                "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
            },
            {
                "title": "Akseli Hinkkalan veneenkorjaus jatkuu",
                "category": "Talous",
                "slug": "veneenkorjaus-toinen",
                "summary": "Nuori jatkaa soutuveneiden ja moottoriveneiden korjausta.",
                "content": "Vene, korjaus ja kunnostaminen ovat jutun ydintä.",
            },
        ]
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            "Required: boat repair. Avoid: generic person portrait or lookalike.",
            terminal,
        )
        events: list[tuple[str, object]] = []

        def generated(title, category, slug, *, intent=None):
            events.append(("provider", slug))
            return result

        def delayed(seconds):
            events.append(("sleep", seconds))

        with patch.object(image_gen, "generate_article_image", side_effect=generated) as provider, \
             patch.object(image_gen.time, "sleep", side_effect=delayed):
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        self.assertEqual(provider.call_count, 2)
        self.assertEqual(
            events,
            [
                ("provider", "veneenkorjaus-ensimmainen"),
                ("sleep", 2),
                ("provider", "veneenkorjaus-toinen"),
            ],
        )
        for article in articles:
            terminal_record = article[image_gen.GENERATION_TERMINAL_FIELD]
            self.assertEqual(terminal_record["reason"], image_gen.REASON_VISUAL_REJECT)
            self.assertFalse(terminal_record["provider_fault"])

    def test_generated_pre_safety_reject_does_not_delay_or_call_provider(self) -> None:
        articles = [
            {
                "title": "Kuvaturvallisuus estää generoinnin",
                "category": "Talous",
                "slug": "pre-safety-reject",
            },
            {
                "title": "Akseli Hinkkalan veneenkorjaus toi nuorelle kesätyön",
                "category": "Talous",
                "slug": "veneenkorjaus",
                "summary": "Nuori korjaa soutuveneitä ja moottoriveneitä.",
                "content": "4H-yrittäjyys, vene, korjaus ja kunnostaminen ovat jutun ydintä.",
            },
        ]
        terminal = image_gen.build_image_terminal_reason(
            stage="generated",
            reason=image_gen.REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=True,
            provider_succeeded=True,
        )
        result = image_gen.GeneratedImageResult(
            "/images/articles/veneenkorjaus.jpg",
            "Required: boat repair. Avoid: generic person portrait or lookalike.",
            terminal,
        )

        class _Intent:
            def __init__(self, generated_ok: bool) -> None:
                self.generated_ok = generated_ok

            def to_dict(self) -> dict[str, bool]:
                return {"generated_ok": self.generated_ok}

        class _Brief:
            def __init__(self, generated_ok: bool) -> None:
                self.intent = _Intent(generated_ok)

        runtime_guard = __import__("image_candidate_guard")
        with patch.object(
                 runtime_guard,
                 "build_visual_brief",
                 side_effect=[_Brief(False), _Brief(True)],
             ), \
             patch.object(
                 runtime_guard,
                 "judge_visual_candidate",
                 return_value={"score": 0, "accepted": False},
             ), \
             patch.object(image_gen, "generate_article_image", return_value=result) as provider, \
             patch.object(image_gen.time, "sleep") as delayed:
            image_gen.generate_images_for_articles(articles, max_total_sec=180)

        provider.assert_called_once()
        self.assertEqual(provider.call_args.args[2], "veneenkorjaus")
        delayed.assert_not_called()
        pre_safety = articles[0][image_gen.GENERATION_TERMINAL_FIELD]
        self.assertEqual(pre_safety["reason"], image_gen.REASON_PRE_SAFETY_REJECT)
        self.assertFalse(pre_safety["provider_attempted"])
        self.assertEqual(
            articles[1][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_VISUAL_REJECT,
        )

    def test_generated_provider_fault_records_kie_failure_with_typed_reason(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous"}]

        def provider_fault(batch, max_total_sec=180):
            terminal = image_gen.build_image_terminal_reason(
                stage="generated",
                reason=image_gen.REASON_PROVIDER_HTTP,
                outcome="provider_fault",
                provider_fault=True,
                provider_attempted=True,
                http_status_class="5xx",
            )
            image_gen.set_generation_terminal(batch[0], terminal)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "key",
        }, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "generate_images_for_articles", side_effect=provider_fault), \
             patch.object(staged_publish, "record_failure") as failure, \
             patch.object(staged_publish, "record_success") as success:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        failure.assert_called_once_with("kie_api")
        success.assert_not_called()
        self.assertEqual(
            summary["generated_terminal_reasons"],
            {image_gen.REASON_PROVIDER_HTTP: 1},
        )
        self.assertEqual(
            articles[0][image_gen.GENERATION_TERMINAL_FIELD]["http_status_class"],
            "5xx",
        )

    def test_generated_visual_reject_never_records_kie_failure(self) -> None:
        articles = [{"title": "Kuvaton artikkeli", "category": "Talous"}]

        def visual_reject(batch, max_total_sec=180):
            terminal = image_gen.build_image_terminal_reason(
                stage="generated",
                reason=image_gen.REASON_VISUAL_REJECT,
                outcome="policy_reject",
                provider_attempted=True,
                provider_succeeded=True,
            )
            image_gen.set_generation_terminal(batch[0], terminal)
            return batch

        with patch.dict(staged_publish.os.environ, {
            "UNSPLASH_ACCESS_KEY": "",
            "PEXELS_API_KEY": "",
            "KIE_API_KEY": "key",
        }, clear=False), \
             patch.object(staged_publish, "should_skip", return_value=(False, None)), \
             patch.object(staged_publish, "generate_images_for_articles", side_effect=visual_reject), \
             patch.object(staged_publish, "record_failure") as failure, \
             patch.object(staged_publish, "record_success") as success:
            summary = staged_publish.enrich_images_for_articles(
                articles,
                unsplash_delay=0,
                pexels_delay=0,
            )

        failure.assert_not_called()
        success.assert_called_once_with("kie_api")
        self.assertEqual(
            summary["generated_terminal_reasons"],
            {image_gen.REASON_VISUAL_REJECT: 1},
        )
        self.assertEqual(
            articles[0]["image_decision_reason"],
            "final category fallback after visual_reject",
        )

    def test_stock_decision_fields_emit_policy_metadata(self) -> None:
        fields = stock_decision_fields("unsplash", {
            "decision": {
                "score": 80,
                "candidate_id": "boat-1",
                "source_url": "https://unsplash.com/photos/boat-1",
                "reasons": ["metadata matches boat", "accepted"],
            },
            "intent": {"subject": "boat repair"},
        }, "boat repair")

        self.assertEqual(fields["image_source"], "unsplash")
        self.assertEqual(fields["image_source_type"], "stock")
        self.assertEqual(fields["image_decision_reason"], "metadata matches boat; accepted")
        self.assertEqual(fields["image_asset_identity"], "unsplash:id:boat-1")

    def test_category_fallback_fields_emit_policy_metadata(self) -> None:
        fields = category_fallback_fields("Talous", reason="stock rejected")

        self.assertEqual(fields["image_source"], "category_fallback")
        self.assertEqual(fields["image_source_type"], "category_fallback")
        self.assertEqual(fields["image_decision_reason"], "stock rejected")

    def test_enrich_images_loads_project_env_for_staged_publish(self) -> None:
        project_env = staged_publish.PROJECT_DIR / ".env"
        old_text = project_env.read_text(encoding="utf-8") if project_env.exists() else None
        old_pexels = staged_publish.os.environ.pop("PEXELS_API_KEY", None)
        old_unsplash = staged_publish.os.environ.pop("UNSPLASH_ACCESS_KEY", None)
        try:
            project_env.write_text("PEXELS_API_KEY=project-key\n", encoding="utf-8")
            articles = [{"title": "Env artikkeli", "category": "Kotimaa"}]

            def fake_pexels(batch, delay=0):
                batch[0]["image"] = "/images/articles/env-hero.jpg"
                batch[0]["image_thumb"] = "/images/articles/env-thumb.jpg"
                batch[0]["image_source"] = "pexels"
                batch[0]["image_category_fallback"] = False
                _mock_stock_receipt(batch[0], provider="pexels", accepted=True)
                return batch

            with patch.object(staged_publish, "should_skip", return_value=(False, None)), \
                 patch.object(staged_publish, "pexels_fetch_images", side_effect=fake_pexels), \
                 patch.object(staged_publish, "unsplash_fetch_images", side_effect=lambda batch, delay=0: batch):
                summary = staged_publish.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)

            self.assertEqual(summary["pexels"], 1)
            self.assertEqual(articles[0]["image"], "/images/articles/env-hero.jpg")
        finally:
            if old_text is None:
                project_env.unlink(missing_ok=True)
            else:
                project_env.write_text(old_text, encoding="utf-8")
            if old_pexels is not None:
                staged_publish.os.environ["PEXELS_API_KEY"] = old_pexels
            else:
                staged_publish.os.environ.pop("PEXELS_API_KEY", None)
            if old_unsplash is not None:
                staged_publish.os.environ["UNSPLASH_ACCESS_KEY"] = old_unsplash
            else:
                staged_publish.os.environ.pop("UNSPLASH_ACCESS_KEY", None)

    def test_publish_persists_enriched_image_metadata_to_published_queue(self) -> None:
        article = {
            "title": "Kuvallinen julkaisu",
            "content": "sana " * 260,
            "category": "Kotimaa",
            "source_url": "https://example.test/kuvallinen-julkaisu",
            "image": "/images/articles/pub.jpg",
            "image_category_fallback": False,
            "image_source": "pexels",
            "image_source_type": "stock",
            "image_decision_reason": "metadata matches article",
            image_gen.GENERATION_TERMINAL_FIELD: {
                "schema": image_gen.IMAGE_TERMINAL_SCHEMA,
                "stage": "generated",
                "reason": image_gen.REASON_BACKOFF,
                "outcome": "skipped",
                "provider_fault": False,
                "provider_attempted": False,
                "provider_succeeded": False,
            },
            image_gen.IMAGE_TERMINAL_REASONS_FIELD: [
                {
                    "schema": image_gen.IMAGE_TERMINAL_SCHEMA,
                    "stage": "generated",
                    "reason": image_gen.REASON_BACKOFF,
                    "outcome": "skipped",
                    "provider_fault": False,
                    "provider_attempted": False,
                    "provider_succeeded": False,
                }
            ],
            "monica_packet_id": "pkt-image",
        }
        data = {
            "article": article,
            "packet": {
                "packet_id": "pkt-image",
                "category": "Kotimaa",
                "clean_source_blocks": [
                    {
                        "source": "Testi",
                        "source_url": "https://example.test/kuvallinen-julkaisu",
                        "text": "lähdesana " * 260,
                    }
                ],
            },
            "payload": {"category": "Kotimaa"},
        }
        path = self._write("outbox", "pkt-image", data, age_hours=1)

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), \
             patch.object(staged_publish, "run_quality_gate", return_value=type("Gate", (), {"passed": [article], "rejected": []})()), \
             patch.object(staged_publish, "check_published_duplicates", side_effect=lambda articles, window_hours=48: articles), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
             patch.object(staged_publish, "enrich_images_for_articles", return_value={"total": 1, "images": 1, "unsplash": 0, "pexels": 1, "missing": 0}), \
             patch.object(staged_publish, "publish_articles", return_value=["content/posts/test.md"]), \
             patch.object(staged_publish, "mark_published"), \
             patch.object(staged_publish, "build_site", return_value=(True, "")), \
             patch.object(staged_publish, "atomic_write_json", side_effect=lambda target, payload: target.write_text(json.dumps(payload), encoding="utf-8")):
            rc = staged_publish.cmd_publish(type("Args", (), {"max_articles": 1, "dedup_window": 48, "dry_run": False, "git_push": False})())

        self.assertEqual(rc, 0)
        published = json.loads((self.root / "published" / "pkt-image.json").read_text(encoding="utf-8"))
        self.assertEqual(published["article"]["image"], "/images/articles/pub.jpg")
        self.assertEqual(published["image_enrichment"]["image"], "/images/articles/pub.jpg")
        self.assertEqual(published["image_enrichment"]["image_source"], "pexels")
        self.assertEqual(published["image_enrichment"]["image_source_type"], "stock")
        self.assertEqual(published["image_enrichment"]["image_decision_reason"], "metadata matches article")
        self.assertEqual(
            published["image_enrichment"][image_gen.GENERATION_TERMINAL_FIELD]["reason"],
            image_gen.REASON_BACKOFF,
        )
        self.assertEqual(
            published["image_enrichment"][image_gen.IMAGE_TERMINAL_REASONS_FIELD][0]["reason"],
            image_gen.REASON_BACKOFF,
        )
        self.assertEqual(
            published["category_trace"]["decisions"],
            {"guard": "Kotimaa", "writer": "Kotimaa", "publisher": "Kotimaa"},
        )
        self.assertFalse(published["category_trace"]["disagreement"])

    def test_publish_build_failure_does_not_mark_dedup_or_move_packet(self) -> None:
        article = {
            "title": "Build failure must remain retryable",
            "content": "sana " * 260,
            "category": "Kotimaa",
            "source_url": "https://example.test/build-failure",
            "image": "/images/articles/build-failure.jpg",
            "monica_packet_id": "pkt-build-failure",
        }
        data = {
            "article": article,
            "packet": {
                "packet_id": "pkt-build-failure",
                "category": "Kotimaa",
                "clean_source_blocks": [
                    {
                        "source": "Testi",
                        "source_url": "https://example.test/build-failure",
                        "text": "lähdesana " * 260,
                    }
                ],
            },
            "payload": {"category": "Kotimaa"},
        }
        path = self._write("outbox", "pkt-build-failure", data, age_hours=1)
        outcome_path = self.root / "cycle.json"

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), \
             patch.object(staged_publish, "run_quality_gate", return_value=type("Gate", (), {"passed": [article], "rejected": []})()), \
             patch.object(staged_publish, "check_published_duplicates", side_effect=lambda articles, window_hours=48: articles), \
             patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
             patch.object(staged_publish, "enrich_images_for_articles", return_value={"total": 1, "images": 1, "unsplash": 0, "pexels": 1, "missing": 0}), \
             patch.object(staged_publish, "publish_articles", return_value=["content/posts/test.md"]), \
             patch.object(staged_publish, "mark_published") as mark_published, \
             patch.object(staged_publish, "build_site", return_value=(False, "synthetic build failure")):
            rc = staged_publish.cmd_publish(
                Namespace(
                    max_articles=1,
                    dedup_window=48,
                    dry_run=False,
                    git_push=False,
                    outcome_json=str(outcome_path),
                )
            )

        self.assertEqual(rc, 2)
        mark_published.assert_not_called()
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "published" / "pkt-build-failure.json").exists())
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        self.assertEqual(outcome["outcome"], "error")
        self.assertEqual(outcome["result"], "build_failed")
        self.assertEqual(outcome["execution"]["created"], 1)
        self.assertEqual(outcome["published"], 0)

    def test_preflight_reject_is_terminalized_without_moving_monica_review_hold(self) -> None:
        reject_path, reject_data, _ = self._write_publish_record("20260901T010000Z_preflight-reject")
        reject_data["article"]["category"] = "Talous"
        reject_path.write_text(json.dumps(reject_data, ensure_ascii=False), encoding="utf-8")

        review_path, review_data, _ = self._write_publish_record("20260901T020000Z_monica-review")
        review_data["packet"]["clean_source_blocks"][0]["text"] = "lähdesana " * 40
        review_path.write_text(json.dumps(review_data, ensure_ascii=False), encoding="utf-8")

        self.assertEqual(staged_publish.evaluate_publish_preflight(reject_data).action, "reject")
        self.assertEqual(staged_publish.evaluate_publish_preflight(review_data).action, "monica_review")
        args = Namespace(max_articles=1, dedup_window=48, dry_run=False, git_push=True)

        with patch.object(
            staged_publish,
            "load_outbox",
            return_value=[(reject_path, reject_data), (review_path, review_data)],
        ), patch.object(staged_publish, "run_quality_gate") as quality_gate, patch.object(
            staged_publish,
            "persist_queue_transitions",
            return_value=0,
        ) as persist:
            rc = staged_publish.cmd_publish(args)

        self.assertEqual(rc, 0)
        quality_gate.assert_not_called()
        persist.assert_called_once_with(
            [(reject_path, self.root / "failed" / reject_path.name)]
        )
        self.assertFalse(reject_path.exists())
        failed = json.loads((self.root / "failed" / reject_path.name).read_text(encoding="utf-8"))
        self.assertTrue(failed["publish_preflight_rejected"])
        self.assertEqual(failed["publish_preflight_feedback"]["action"], "reject")
        self.assertIn("category_disagreement", failed["publish_preflight_feedback"]["reasons"])
        self.assertTrue(failed["failure"].startswith("publish_preflight_rejected:"))
        self.assertTrue(review_path.exists())
        self.assertFalse((self.root / "failed" / review_path.name).exists())

    def test_preflight_reject_dry_run_preserves_outbox_and_does_not_persist(self) -> None:
        path, data, _ = self._write_publish_record("20260901T030000Z_preflight-dry-run")
        data["article"]["category"] = "Talous"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        args = Namespace(max_articles=1, dedup_window=48, dry_run=True, git_push=True)

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), patch.object(
            staged_publish,
            "persist_queue_transitions",
        ) as persist:
            rc = staged_publish.cmd_publish(args)

        self.assertEqual(rc, 0)
        persist.assert_not_called()
        self.assertTrue(path.exists())
        self.assertFalse((self.root / "failed" / path.name).exists())

    def test_preflight_reject_fails_closed_on_terminal_basename_collision(self) -> None:
        path, data, _ = self._write_publish_record("20260901T040000Z_preflight-collision")
        data["article"]["category"] = "Talous"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        failed_path = self.root / "failed" / path.name
        failed_bytes = b'{"existing": true}\n'
        failed_path.write_bytes(failed_bytes)
        result = staged_publish.evaluate_publish_preflight(data)
        self.assertEqual(result.action, "reject")

        with self.assertRaises(FileExistsError):
            staged_publish.quarantine_preflight_rejected_outbox(path, data, result)

        self.assertTrue(path.exists())
        self.assertEqual(failed_path.read_bytes(), failed_bytes)

    def test_all_quality_rejects_persist_exact_queue_delta_and_propagate_failure(self) -> None:
        path, data, article = self._write_publish_record("20260804T010000Z_quality-reject")
        args = Namespace(max_articles=1, dedup_window=48, dry_run=False, git_push=True)

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), \
             patch.object(
                 staged_publish,
                 "run_quality_gate",
                 return_value=type("Gate", (), {"passed": [], "rejected": [article]})(),
             ), \
             patch.object(staged_publish, "quarantine_duplicate_outbox") as duplicate_quarantine, \
             patch.object(staged_publish, "persist_queue_transitions", return_value=17) as persist:
            rc = staged_publish.cmd_publish(args)

        self.assertEqual(rc, 17)
        duplicate_quarantine.assert_not_called()
        persist.assert_called_once()
        self.assertEqual(
            persist.call_args.args[0],
            [(path, self.root / "failed" / path.name)],
        )
        failed = json.loads((self.root / "failed" / path.name).read_text(encoding="utf-8"))
        self.assertTrue(failed["quality_gate_rejected"])
        self.assertNotIn("duplicate_rejected", failed)

    def test_all_duplicate_passes_persist_exact_queue_delta_before_zero_return(self) -> None:
        path, data, article = self._write_publish_record("20260804T020000Z_duplicate")
        args = Namespace(max_articles=1, dedup_window=48, dry_run=False, git_push=True)

        with patch.object(staged_publish, "load_outbox", return_value=[(path, data)]), \
             patch.object(
                 staged_publish,
                 "run_quality_gate",
                 return_value=type("Gate", (), {"passed": [article], "rejected": []})(),
             ), \
             patch.object(staged_publish, "filter_new_articles", return_value=[]), \
             patch.object(staged_publish, "check_published_duplicates", return_value=[]), \
             patch.object(staged_publish, "dedup_within_batch", return_value=[]), \
             patch.object(staged_publish, "persist_queue_transitions", return_value=0) as persist:
            rc = staged_publish.cmd_publish(args)

        self.assertEqual(rc, 0)
        persist.assert_called_once()
        self.assertEqual(
            persist.call_args.args[0],
            [(path, self.root / "failed" / path.name)],
        )
        failed = json.loads((self.root / "failed" / path.name).read_text(encoding="utf-8"))
        self.assertTrue(failed["duplicate_rejected"])
        self.assertNotIn("quality_gate_rejected", failed)

    def test_publisher_frontmatter_preserves_image_policy_metadata(self) -> None:
        markdown = publisher._article_to_markdown({
            "title": "Kuvallinen julkaisu",
            "content": "sana " * 260,
            "category": "Kotimaa",
            "image": "/images/articles/pub.jpg",
            "image_source": "pexels",
            "image_source_type": "stock",
            "image_decision_reason": "metadata matches article",
            "image_asset_identity": "pexels:id:12345",
            "image_category_fallback": False,
        }, "2026-07-03T08:00:00+00:00")

        self.assertIn('image_source: "pexels"', markdown)
        self.assertIn('image_source_type: "stock"', markdown)
        self.assertIn('image_decision_reason: "metadata matches article"', markdown)
        self.assertIn('image_asset_identity: "pexels:id:12345"', markdown)
        self.assertIn("image_category_fallback: false", markdown)

    def test_git_deploy_includes_generated_article_images(self) -> None:
        commands: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch.object(staged_publish, "refresh_static_status"), \
             patch.object(staged_publish.subprocess, "run", side_effect=fake_run):
            rc = staged_publish.run_git_deploy(1)

        self.assertEqual(rc, 0)
        git_add = next(cmd for cmd in commands if cmd[:3] == ["git", "add", "-A"])
        self.assertIn("static/images/articles/", git_add)

    def test_queue_only_persistence_stages_exact_transition_and_verifies_remote(self) -> None:
        project_dir = self.root / "project"
        staged_root = project_dir / "pipeline" / "queues" / "staged"
        source = staged_root / "outbox" / "packet.json"
        target = staged_root / "failed" / "packet.json"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")
        expected_head = "a" * 40
        expected_status = (
            "D\tpipeline/queues/staged/outbox/packet.json\n"
            "A\tpipeline/queues/staged/failed/packet.json\n"
        )
        commands: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            stdout = ""
            if cmd[:4] == ["git", "diff", "--cached", "--name-status"]:
                stdout = expected_status
            elif cmd == ["git", "rev-parse", "HEAD"]:
                stdout = expected_head + "\n"
            elif cmd == ["git", "ls-remote", "origin", "refs/heads/main"]:
                stdout = f"{expected_head}\trefs/heads/main\n"
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

        with patch.object(staged_publish, "PROJECT_DIR", project_dir), \
             patch.object(staged_publish, "STAGED_ROOT", staged_root), \
             patch.object(staged_publish.subprocess, "run", side_effect=fake_run):
            rc = staged_publish.persist_queue_transitions([(source, target)])

        self.assertEqual(rc, 0)
        self.assertIn(
            [
                "git",
                "add",
                "-A",
                "--",
                "pipeline/queues/staged/failed/packet.json",
                "pipeline/queues/staged/outbox/packet.json",
            ],
            commands,
        )
        self.assertIn(["git", "pull", "--rebase", "--autostash", "origin", "main"], commands)
        self.assertIn(["git", "push", "origin", "main"], commands)
        self.assertIn(["git", "ls-remote", "origin", "refs/heads/main"], commands)

    def test_queue_only_persistence_rejects_unrelated_staged_delta(self) -> None:
        project_dir = self.root / "project"
        staged_root = project_dir / "pipeline" / "queues" / "staged"
        source = staged_root / "outbox" / "packet.json"
        target = staged_root / "failed" / "packet.json"
        source.parent.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")
        commands: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            stdout = ""
            if cmd[:4] == ["git", "diff", "--cached", "--name-status"]:
                stdout = (
                    "D\tpipeline/queues/staged/outbox/packet.json\n"
                    "A\tpipeline/queues/staged/failed/packet.json\n"
                    "M\tpipeline/staged_publish.py\n"
                )
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

        with patch.object(staged_publish, "PROJECT_DIR", project_dir), \
             patch.object(staged_publish, "STAGED_ROOT", staged_root), \
             patch.object(staged_publish.subprocess, "run", side_effect=fake_run):
            rc = staged_publish.persist_queue_transitions([(source, target)])

        self.assertEqual(rc, 4)
        self.assertNotIn(["git", "push", "origin", "main"], commands)

    def test_quality_gate_feedback_marks_source_backed_length_only_as_repairable(self) -> None:
        record = _record("length-only", source_words=360, blocks=3)
        record["packet"]["packet_id"] = "pkt-length-only"
        article = {
            "title": "Hallitus valmistelee säästöjä",
            "description": "Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle.",
            "content": "Hallitus valmistelee säästöjä ensi vuodelle. Valmistelu jatkuu ministeriöissä.\n\n## Tausta\n\nPäätöksiä arvioidaan myöhemmin.",
            "category": "Kotimaa",
            "image": "https://example.com/img.jpg",
            "source_text": " ".join(["Hallitus valmistelee säästöjä sosiaalihuoltoon ensi vuodelle."] * 70),
            "source_url": "https://example.com/story",
        }

        feedback = staged_publish.quality_gate_retry_classification(record, article)

        self.assertTrue(feedback["source_backed"])
        self.assertTrue(feedback["repair_eligible"])
        self.assertEqual(feedback["retry_classification"], "repairable_length_only")

    def test_priority_prefers_promising_packet_over_old_thin_fifo(self) -> None:
        thin_old = self._write("ready", "thin-old", _record("thin-old", source_words=45, blocks=1), age_hours=30)
        rich_newer = self._write("ready", "rich-newer", _record("rich-newer", source_words=420, blocks=3), age_hours=10)

        ordered = staged_publish.prioritized_ready_packets()

        self.assertEqual(ordered[0], rich_newer)
        self.assertIn(thin_old, ordered)

    def test_priority_applies_talous_mix_bonus_without_beating_much_stronger_packet(self) -> None:
        talous = _record("talous", source_words=260, blocks=2)
        talous["packet"]["category_hint"] = "Talous"
        talous_path = self._write("ready", "talous", talous, age_hours=1)
        kotimaa_path = self._write("ready", "kotimaa", _record("kotimaa", source_words=260, blocks=2), age_hours=1)
        rich_path = self._write("ready", "rich", _record("rich", source_words=700, blocks=4), age_hours=1)

        self.assertGreater(staged_publish.priority_score(talous_path)[0], staged_publish.priority_score(kotimaa_path)[0])
        self.assertEqual(staged_publish.ready_sample(talous_path)["category_priority_bonus"], 4.0)
        self.assertEqual(staged_publish.prioritized_ready_packets()[0], rich_path)

    def test_priority_uses_original_talous_hint_when_saved_packet_still_says_ulkomaat(self) -> None:
        stale_saved = _record("stale-saved", source_words=260, blocks=2)
        stale_saved["packet"]["category_hint"] = "Ulkomaat"
        stale_saved["packet"]["category"] = "Ulkomaat"
        stale_saved["original_article"]["category_hint"] = "Talous"
        stale_saved["original_article"]["_guessed_category"] = "Talous"
        stale_path = self._write("ready", "stale-saved", stale_saved, age_hours=1)
        kotimaa_path = self._write("ready", "kotimaa", _record("kotimaa", source_words=260, blocks=2), age_hours=1)

        self.assertGreater(staged_publish.priority_score(stale_path)[0], staged_publish.priority_score(kotimaa_path)[0])
        self.assertEqual(staged_publish.ready_sample(stale_path)["category"], "Talous")
        self.assertEqual(staged_publish.ready_sample(stale_path)["category_priority_bonus"], 4.0)



    def test_talous_rss_source_backed_counts_as_enriched_and_passes_priority_floor(self) -> None:
        article = {
            "title": "Pörssi laski inflaatiolukujen jälkeen",
            "category_hint": "Talous",
            "source": "Taloussanomat",
            "research_source": "rss_talous_source_backed",
            "research": "[Lähde: Taloussanomat]\n" + " ".join(["sana"] * 125),
            "description": "Lyhyt kuvaus",
        }

        self.assertEqual(staged_publish.article_research_bucket(article), "research_enriched")
        self.assertTrue(staged_publish.passes_priority_source_floor(article))
        self.assertGreater(staged_publish.category_enqueue_bonus(article), 0)


    def test_research_candidate_cap_keeps_talous_after_cooldown(self) -> None:
        kotimaa = {"title": "kotimaa uutinen", "category_hint": "Kotimaa", "description": "kuvaus " * 6}
        ulkomaat = {"title": "ulkomaat uutinen", "category_hint": "Ulkomaat", "description": "kuvaus " * 5}
        talous = {"title": "talous uutinen", "category_hint": "Talous", "description": "kuvaus " * 4}

        selected = staged_publish.select_research_candidates([kotimaa, ulkomaat, talous], max_candidates=2)

        self.assertEqual(len(selected), 2)
        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(ulkomaat, selected)


    def test_research_candidate_cap_keeps_two_talous_before_enrichment(self) -> None:
        articles = [
            {"title": "kotimaa yksi", "category_hint": "Kotimaa", "description": "kuvaus " * 6},
            {"title": "kotimaa kaksi", "category_hint": "Kotimaa", "description": "kuvaus " * 6},
            {"title": "ulkomaat yksi", "category_hint": "Ulkomaat", "description": "kuvaus " * 5},
            {"title": "talous yksi", "category_hint": "Talous", "description": "kuvaus " * 4},
            {"title": "talous kaksi", "category_hint": "Talous", "description": "kuvaus " * 4},
        ]

        selected = staged_publish.select_research_candidates(articles, max_candidates=3)

        self.assertEqual(len(selected), 3)
        categories = [staged_publish.article_category(article) for article in selected]
        self.assertEqual(categories.count("Talous"), 2)
        self.assertEqual(sum(1 for article in selected if article["title"].startswith("talous")), 2)

    def test_repeated_scan_records_one_source_floor_drop_and_rotates_to_next_candidate(self) -> None:
        thin = {
            "title": "Ohut Arvopaperin Talous-ehdokas",
            "link": "https://example.com/talous-thin",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "research": "[Lähde: Arvopaperi]\n" + "sana " * 37 + "\n\n[Lähde: Haastattelu]\n" + "sana " * 38,
            "description": "Sijoittajan arvio yrityskaupasta.",
            "story_confidence": 0.85,
            "research_source": "multi",
        }
        next_candidate = {
            "title": "Seuraava Talous-ehdokas",
            "link": "https://example.com/talous-next",
            "category_hint": "Talous",
            "source": "Testi",
            "description": "Seuraava ehdokas tutkittavaksi.",
        }
        now_ts = 1_800_000_000.0

        self.assertEqual(staged_publish.talous_enqueue_drop_reason(thin), "source_floor_not_met")
        self.assertEqual(staged_publish.org_source_talous_guardrail(thin)["classification"], "not_org_source_talous")
        recorded = staged_publish.record_talous_source_floor_rejections(
            [thin], [], hours=24, now_ts=now_ts
        )
        kept, skipped = staged_publish.filter_talous_source_floor_cooldown(
            [thin, next_candidate], hours=24, now_ts=now_ts + 60
        )
        selected = staged_publish.select_research_candidates(kept, max_candidates=1)
        repeated_scan_recorded = staged_publish.record_talous_source_floor_rejections(
            kept, selected, hours=24, now_ts=now_ts + 60
        )

        self.assertEqual(recorded, [thin])
        self.assertEqual(skipped, [thin])
        self.assertEqual(selected, [next_candidate])
        self.assertEqual(repeated_scan_recorded, [])
        cache = staged_publish.load_talous_source_floor_cooldown(hours=24, now_ts=now_ts + 60)
        self.assertEqual(list(cache), [staged_publish.stable_digest(thin)])
        self.assertEqual(
            staged_publish.load_talous_source_floor_cooldown(hours=24, now_ts=now_ts + 24 * 3600 + 1),
            {},
        )

    def test_talous_source_floor_cooldown_reports_no_backfill_candidate(self) -> None:
        thin = {
            "title": "Ainoa ohut Talous-ehdokas",
            "link": "https://example.com/talous-only-thin",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "research": "[Lähde: Arvopaperi]\n" + "sana " * 75 + "\n\n[Lähde: Toinen]\n",
            "description": "Niukka lähdeaineisto.",
            "story_confidence": 0.85,
            "research_source": "multi",
        }
        now_ts = 1_800_000_000.0
        staged_publish.record_talous_source_floor_rejections([thin], [], hours=24, now_ts=now_ts)

        kept, skipped = staged_publish.filter_talous_source_floor_cooldown(
            [thin], hours=24, now_ts=now_ts + 60
        )

        self.assertEqual(kept, [])
        self.assertEqual(skipped, [thin])

    def test_one_block_talous_source_floor_drop_rotates_to_next_candidate(self) -> None:
        thin = {
            "title": "Ohut Finanssialan Talous-ehdokas",
            "link": "https://example.com/talous-one-block-thin",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 58,
            "description": "Maksutapoja koskeva kysely.",
            "story_confidence": 0.85,
            "research_source": "multi",
        }
        next_candidate = {
            "title": "Seuraava Talous-ehdokas",
            "link": "https://example.com/talous-next-after-one-block",
            "category_hint": "Talous",
            "source": "Testi",
            "description": "Seuraava ehdokas tutkittavaksi.",
        }
        now_ts = 1_800_000_000.0

        self.assertEqual(
            staged_publish.talous_enqueue_drop_reason(thin),
            "source_floor_one_block_too_short",
        )
        recorded = staged_publish.record_talous_source_floor_rejections(
            [thin], [], hours=24, now_ts=now_ts
        )
        kept, skipped = staged_publish.filter_talous_source_floor_cooldown(
            [thin, next_candidate], hours=24, now_ts=now_ts + 60
        )

        self.assertEqual(recorded, [thin])
        self.assertEqual(skipped, [thin])
        self.assertEqual(kept, [next_candidate])
        cache = staged_publish.load_talous_source_floor_cooldown(hours=24, now_ts=now_ts + 60)
        self.assertEqual(
            cache[staged_publish.stable_digest(thin)]["reason"],
            "source_floor_one_block_too_short",
        )

    def test_talous_failed_staged_digest_can_reenter_scan_cooldown(self) -> None:
        failed = _record("talous-failed", source_words=0, blocks=0)
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        self._write("failed", "talous-failed", failed, age_hours=1)

        article = {"title": "Talous failed", "url": "https://example.com/talous", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def0"):
            self.assertFalse(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_duplicate_failed_digest_obeys_terminal_cooldown(self) -> None:
        article = {"title": "Talous duplicate", "url": "https://example.com/talous-duplicate", "category_hint": "Talous"}
        digest = staged_publish.stable_digest(article)
        failed = _record("talous-duplicate", source_words=360, blocks=3)
        failed["digest"] = digest
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["duplicate_rejected"] = True
        self._write("failed", "talous-duplicate", failed, age_hours=1)

        with patch.object(staged_publish, "stable_digest", return_value=digest):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_fail_closed_quality_gate_obeys_terminal_cooldown(self) -> None:
        failed = _record("talous-quality", source_words=360, blocks=3)
        failed["digest"] = "abc123def3"
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["quality_gate_feedback"] = {"retry_classification": "fail_closed_quality_gate"}
        self._write("failed", "talous-quality", failed, age_hours=1)

        article = {"title": "Talous quality", "url": "https://example.com/talous-quality", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def3"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_talous_newer_ready_digest_obeys_cooldown(self) -> None:
        ready = _record("talous-ready", source_words=360, blocks=3)
        ready["digest"] = "abc123def4"
        ready["packet"]["category_hint"] = "Talous"
        ready["original_article"]["category_hint"] = "Talous"
        failed = _record("talous-terminal", source_words=360, blocks=3)
        failed["digest"] = "abc123def4"
        failed["packet"]["category_hint"] = "Talous"
        failed["original_article"]["category_hint"] = "Talous"
        failed["duplicate_rejected"] = True
        self._write("ready", "talous-ready", ready, age_hours=0.5)
        self._write("failed", "talous-terminal", failed, age_hours=1)

        article = {"title": "Talous ready", "url": "https://example.com/talous-ready", "category_hint": "Talous"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def4"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_non_talous_failed_staged_digest_still_obeys_cooldown(self) -> None:
        failed = _record("kotimaa-failed", source_words=0, blocks=0)
        failed["digest"] = "abc123def1"
        failed["packet"]["category_hint"] = "Kotimaa"
        failed["original_article"]["category_hint"] = "Kotimaa"
        self._write("failed", "kotimaa-failed", failed, age_hours=1)

        article = {"title": "Kotimaa failed", "url": "https://example.com/kotimaa", "category_hint": "Kotimaa"}
        with patch.object(staged_publish, "stable_digest", return_value="abc123def1"):
            self.assertTrue(staged_publish.should_skip_staged_cooldown(article, hours=24))

    def test_scan_enqueue_keeps_under_target_talous_when_source_strength_ties(self) -> None:
        kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "[Lähde: Testi]\n" + "sana " * 220, "description": "kuvaus"}
        talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 110 + "\n\n[Lähde: B]\n" + "sana " * 110, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([kotimaa, talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")




    def test_scan_enqueue_uses_full_packet_cap_when_priority_candidate_exists(self) -> None:
        rich_talous = {
            "title": "Talous",
            "category_hint": "Talous",
            "research": "[Lähde: A]\n" + "sana " * 140 + "\n\n[Lähde: B]\n" + "sana " * 140,
            "description": "kuvaus",
            "story_confidence": 0.95,
        }
        kotimaa = {"title": "Kotimaa", "category_hint": "Kotimaa", "research": "[Lähde: K]\n" + "sana " * 230, "description": "kuvaus"}
        ulkomaat = {"title": "Ulkomaat", "category_hint": "Ulkomaat", "research": "[Lähde: U]\n" + "sana " * 210, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_talous, kotimaa, ulkomaat], max_packets=3)

        self.assertEqual(len(selected), 3)
        self.assertEqual(
            {staged_publish.article_category(article) for article in selected},
            {"Talous", "Kotimaa", "Ulkomaat"},
        )



    def test_scan_enqueue_can_fill_cap_with_multiple_source_backed_talous(self) -> None:
        talous_articles = [
            {
                "title": f"talous {index}",
                "category_hint": "Talous",
                "research": "[Lähde: A]\n" + "sana " * 140 + "\n\n[Lähde: B]\n" + "sana " * 140,
                "description": "kuvaus",
                "story_confidence": 0.95,
            }
            for index in range(3)
        ]
        other_articles = [
            {"title": f"kotimaa {index}", "category_hint": "Kotimaa", "research": "[Lähde: K]\n" + "sana " * (240 + index * 20), "description": "kuvaus"}
            for index in range(5)
        ]

        selected = staged_publish.select_scan_enqueue_candidates(talous_articles + other_articles, max_packets=3)

        self.assertEqual(len(selected), 3)
        self.assertEqual(
            [staged_publish.article_category(article) for article in selected],
            ["Talous", "Talous", "Talous"],
        )

    def test_scan_enqueue_does_not_promote_thin_talous_fallback(self) -> None:
        thin_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 90, "description": "kuvaus"}
        fallback_talous = {"title": "talous", "category_hint": "Talous", "research": "sana " * 120, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([thin_kotimaa, fallback_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Kotimaa")

    def test_scan_enqueue_promotes_talous_after_source_floor_over_thin_backlog(self) -> None:
        thin_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 90, "description": "kuvaus"}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([thin_kotimaa, sourced_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_keeps_source_qualified_talous_when_cap_drops_it(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 260, "description": "kuvaus"}
        moderate_ulkomaat = {"title": "ulkomaat", "category_hint": "Ulkomaat", "research": "sana " * 170, "description": "kuvaus"}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_kotimaa, moderate_ulkomaat, sourced_talous], max_packets=2)

        self.assertEqual(len(selected), 2)
        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(moderate_ulkomaat, selected)


    def test_scan_enqueue_reserves_source_backed_talous_when_cap_would_drop_it(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 310, "description": "kuvaus"}
        uutiset = {"title": "uutiset", "category_hint": "Uutiset", "research": "[Lähde: Testi]\n" + "sana " * 260, "description": "kuvaus"}
        talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 95 + "\n\n[Lähde: B]\n" + "sana " * 95, "description": "kuvaus", "story_confidence": 0.90}

        selected = staged_publish.select_scan_enqueue_candidates([teknologia, uutiset, talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")

    def test_scan_enqueue_reserve_rejects_weak_one_block_talous_packet(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 220, "description": "kuvaus"}
        tokmanni = {
            "title": "Tokmanni aloittaa omien osakkeiden hankinnan",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "research": "[Lähde: Arvopaperi]\n" + "sana " * 102,
            "description": "Tokmanni aloittaa omien osakkeiden hankinnan.",
            "story_confidence": 0.62,
            "research_source": "multi",
        }

        self.assertFalse(staged_publish.passes_priority_source_floor(tokmanni))
        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(tokmanni))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, tokmanni], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Teknologia")


    def test_scan_enqueue_reserves_high_confidence_one_block_talous_packet(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 310, "description": "kuvaus"}
        talous = {
            "title": "Yrittäjä tarkistaa luottotiedot ennen sopimuksia",
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "research": "[Lähde: Suomen Yrittäjät]\n" + "Luottotiedot auttavat yritystä arvioimaan maksukykyä ennen sopimuksia. " * 27,
            "description": "Pk-yrityksen riskienhallintaa käsittelevä juttu kertoo luottotietojen käytöstä.",
            "story_confidence": 0.96,
        }

        self.assertTrue(staged_publish.passes_priority_source_floor(talous))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(talous))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, talous], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_uses_selected_source_blocks_after_research_selection(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 310, "description": "kuvaus"}
        paragraph_a = (
            "Verkkokaupan peruuttamistoiminto auttaa yritystä käsittelemään asiakkaan peruutuksen, "
            "maksun palautuksen ja sopimusehdot neutraalisti kuluttajakaupassa. "
        ) * 6
        paragraph_b = (
            "Yrittäjän verkkokaupan sopimusehdot kertovat asiakkaalle määräajat, hyvityksen, "
            "peruutuslomakkeen ja palautusmaksun käytännön vaikutukset. "
        ) * 6
        paragraph_c = (
            "Yritys voi vähentää riitoja, kun verkkokaupan peruuttamistoiminto näyttää "
            "kuluttajalle palautuksen etenemisen ja kauppiaan velvoitteet. "
        ) * 6
        talous = {
            "title": "Verkkokaupan peruuttamistoiminto muuttaa yrittäjän arkea",
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "research": "[Lähde: Suomen Yrittäjät]\n" + "\n\n".join([paragraph_a, paragraph_b, paragraph_c]),
            "description": "Yritysten verkkokaupan lakisääteinen peruuttamistoiminto vaikuttaa maksun palautuksiin.",
            "story_confidence": 0.85,
            "research_source": "multi",
        }

        raw_words, raw_blocks = staged_publish.raw_research_source_evidence(talous)
        selected_words, selected_blocks = staged_publish.selected_source_evidence(talous)
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, talous], max_packets=1)

        self.assertEqual(raw_blocks, 1)
        self.assertLess(raw_words, 250)
        self.assertGreaterEqual(selected_words, 180)
        self.assertGreaterEqual(selected_blocks, 2)
        self.assertTrue(staged_publish.passes_priority_source_floor(talous))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(talous))
        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_rejects_lower_confidence_one_block_talous_packet(self) -> None:
        talous = {
            "title": "Yrittäjä tarkistaa luottotiedot ennen sopimuksia",
            "category_hint": "Talous",
            "source": "Suomen Yrittäjät",
            "research": "[Lähde: Suomen Yrittäjät]\n" + "Luottotiedot auttavat yritystä arvioimaan maksukykyä ennen sopimuksia. " * 27,
            "description": "Pk-yrityksen riskienhallintaa käsittelevä juttu kertoo luottotietojen käytöstä.",
            "story_confidence": 0.72,
        }

        self.assertFalse(staged_publish.passes_priority_source_floor(talous))
        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(talous))


    def test_scan_enqueue_reserves_substantive_one_block_talous_packet(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 310, "description": "kuvaus"}
        talous = {
            "title": "Sijoittajat palasivat rahastomarkkinoille huhtikuussa",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 260,
            "description": "Rahastomarkkinoiden nettomerkinnät kääntyivät huhtikuussa plussalle.",
            "story_confidence": 0.96,
            "research_source": "multi",
        }

        self.assertTrue(staged_publish.passes_priority_source_floor(talous))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(talous))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, talous], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Talous")


    def test_scan_enqueue_reserve_preserves_promotional_talous_rejection(self) -> None:
        teknologia = {"title": "teknologia", "category_hint": "Teknologia", "research": "[Lähde: Testi]\n" + "sana " * 260, "description": "kuvaus"}
        promo = {
            "title": "Finanssiala uudisti verkkosivunsa",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "description": "Tavoitteemme-osio kertoo sivuston uudesta ulkoasusta.",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 300 + " uudisti verkkosivunsa tavoitteemme-osio",
            "story_confidence": 0.98,
        }

        self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(promo))
        selected = staged_publish.select_scan_enqueue_candidates([teknologia, promo], max_packets=1)

        self.assertEqual(staged_publish.article_category(selected[0]), "Teknologia")


    def test_scan_enqueue_rejects_thin_selected_source_talous_fragments(self) -> None:
        for words in (49, 100):
            with self.subTest(words=words):
                talous = {
                    "title": f"Finanssialan lyhyt talouskatkelma {words}",
                    "category_hint": "Talous",
                    "source": "Finanssiala",
                    "research": "[Lähde: Finanssiala]\n" + "markkina " * words,
                    "description": "Lyhyt talouskatkelma ei riitä julkaistavaksi.",
                    "story_confidence": 0.98,
                    "research_source": "multi",
                }

                selected_words, selected_blocks = staged_publish.selected_source_evidence(talous)

                self.assertLessEqual(selected_words, 100)
                self.assertEqual(selected_blocks, 1)
                self.assertFalse(staged_publish.passes_priority_source_floor(talous))
                self.assertFalse(staged_publish.scan_candidate_passes_talous_reserve(talous))


    def test_talous_enqueue_drop_examples_explain_source_passed_final_drop(self) -> None:
        tokmanni = {
            "title": "Tokmanni aloittaa omien osakkeiden hankinnan",
            "category_hint": "Talous",
            "source": "Arvopaperi",
            "research": "[Lähde: Arvopaperi]\n" + "sana " * 102,
            "description": "Tokmanni aloittaa omien osakkeiden hankinnan.",
            "story_confidence": 0.62,
            "research_source": "multi",
        }

        examples = staged_publish.talous_drop_candidates([tokmanni])

        self.assertEqual(examples[0]["source"], "Arvopaperi")
        self.assertEqual(examples[0]["candidate_id"], staged_publish.stable_digest(tokmanni))
        self.assertEqual(examples[0]["source_blocks"], 1)
        self.assertEqual(examples[0]["research_bucket"], "research_enriched")
        self.assertFalse(examples[0]["reserve_pass"])
        self.assertEqual(examples[0]["drop_reason"], "source_floor_one_block_too_short")

    def test_talous_enqueue_drop_examples_mark_promotional_guardrail_drop(self) -> None:
        promo = {
            "title": "Finanssiala uudisti verkkosivunsa",
            "category_hint": "Talous",
            "source": "Finanssiala",
            "description": "Tavoitteemme-osio kertoo sivuston uudesta ulkoasusta.",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 300 + " uudisti verkkosivunsa tavoitteemme-osio",
            "story_confidence": 0.98,
            "research_source": "multi",
        }

        examples = staged_publish.talous_drop_candidates([promo])

        self.assertEqual(examples[0]["guardrail"], "down_rank_promotional_org_source")
        self.assertFalse(examples[0]["reserve_pass"])
        self.assertEqual(examples[0]["drop_reason"], "org_source_guardrail_penalty")


    def test_scan_enqueue_uses_total_source_floor_for_talous_candidate(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 410, "description": "kuvaus"}
        moderate_ulkomaat = {"title": "ulkomaat", "category_hint": "Ulkomaat", "research": "sana " * 204, "description": "kuvaus " * 16}
        sourced_talous = {"title": "talous", "category_hint": "Talous", "research": "[Lähde: A]\n" + "sana " * 100 + "\n\n[Lähde: B]\n" + "sana " * 100, "description": "kuvaus " * 16}
        rich_urheilu = {"title": "urheilu", "category_hint": "Urheilu", "research": "sana " * 608, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_urheilu, rich_kotimaa, moderate_ulkomaat, sourced_talous], max_packets=3)

        self.assertIn("Talous", {staged_publish.article_category(article) for article in selected})
        self.assertNotIn(moderate_ulkomaat, selected)

    def test_scan_enqueue_does_not_let_talous_beat_much_stronger_source(self) -> None:
        rich_kotimaa = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 700, "description": "kuvaus"}
        thin_talous = {"title": "talous", "category_hint": "Talous", "research": "sana " * 120, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([rich_kotimaa, thin_talous], max_packets=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(staged_publish.article_category(selected[0]), "Kotimaa")

    def test_org_source_talous_guardrail_downranks_self_promotional_org_news(self) -> None:
        article = {
            "title": "Finanssiala uudisti verkkosivunsa ja nosti edunvalvontatavoitteet näkyviin",
            "description": "Järjestön Tavoitteemme-osio kertoo sivuston uudesta ulkoasusta.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "down_rank_promotional_org_source")
        self.assertGreater(staged_publish.org_source_talous_penalty(article), staged_publish.category_enqueue_bonus(article))

    def test_org_source_talous_guardrail_keeps_attributed_policy_claim(self) -> None:
        article = {
            "title": "Finanssiala varoittaa osakesäästötilin rahastolaajennuksesta",
            "description": "Finanssialan mukaan muutos voisi heikentää järjestelmän selkeyttä.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_attributed_policy_claim")
        self.assertEqual(staged_publish.org_source_talous_penalty(article), 0)

    def test_org_source_talous_guardrail_allows_concrete_yrittajat_profile(self) -> None:
        article = {
            "title": "Yrittäjä Agim Sopjan löytää shakkilaudalta vastapainoa rakennusalan arkeen",
            "description": "Yritysprofiili kertoo yrittäjän arjesta ja harrastuksesta ilman jäsen-CTA:ta.",
            "source": "Suomen Yrittäjät",
            "category_hint": "Talous",
            "research": "[Lähde: Suomen Yrittäjät]\n" + "sana " * 360,
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_company_profile")
        self.assertEqual(staged_publish.org_source_talous_penalty(article), 0)

    def test_org_source_talous_guardrail_ignores_generic_footer_cta_for_attributed_policy_story(self) -> None:
        article = {
            "title": "Pentikäinen: Vauvabonus harkinnanarvoinen – Yrittäjien malli vaikuttaisi heti eikä vuosien päästä",
            "description": "Suomen Yrittäjien mukaan vauvabonus voisi vaikuttaa perheiden päätöksiin nopeasti.",
            "source": "Suomen Yrittäjät",
            "category_hint": "Talous",
            "research": (
                "[Lähde: Suomen Yrittäjät]\n"
                + "Yrittäjien mukaan ehdotus 10000 euron vauvabonuksesta vaikuttaisi heti. " * 31
                + "\n\nSivuston yleinen alatunniste: liity jäseneksi ja tule mukaan paikallisyhdistyksen toimintaan."
            ),
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_attributed_policy_claim")
        self.assertTrue(staged_publish.passes_priority_source_floor(article))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(article))

    def test_org_source_talous_guardrail_ignores_generic_footer_cta_for_farmer_loss_story(self) -> None:
        article = {
            "title": "Hanhet söivät viljelijän ensimmäisen, lehmille tärkeimmän nurmisadon",
            "description": "Maatilayrittäjä kertoo, että hanhivahingot uhkaavat karjan rehunsaantia ja tilan taloutta.",
            "source": "Suomen Yrittäjät",
            "category_hint": "Talous",
            "research": (
                "[Lähde: Suomen Yrittäjät]\n"
                + "Viljelijän mukaan hanhet söivät ensimmäisen nurmisadon ja aiheuttivat merkittävän taloudellisen menetyksen. " * 34
                + "\n\nSivuston yleinen alatunniste: liity jäseneksi ja tule mukaan paikallisyhdistyksen toimintaan."
            ),
        }

        guardrail = staged_publish.org_source_talous_guardrail(article)

        self.assertEqual(guardrail["classification"], "ok_company_profile")
        self.assertTrue(staged_publish.passes_priority_source_floor(article))
        self.assertTrue(staged_publish.scan_candidate_passes_talous_reserve(article))

    def test_scan_enqueue_downranks_promotional_org_source_talous_below_comparable_packet(self) -> None:
        promotional = {
            "title": "Finanssiala uudisti verkkosivunsa ja nosti edunvalvontatavoitteet näkyviin",
            "description": "Tavoitteemme-osio ja sivuston ulkoasu esitellään järjestön omassa uutisessa.",
            "source": "Finanssiala",
            "category_hint": "Talous",
            "research": "[Lähde: Finanssiala]\n" + "sana " * 360,
        }
        neutral = {"title": "kotimaa", "category_hint": "Kotimaa", "research": "sana " * 260, "description": "kuvaus"}

        selected = staged_publish.select_scan_enqueue_candidates([promotional, neutral], max_packets=1)

        self.assertEqual(selected, [neutral])

    def test_talous_worker_bonus_requires_source_floor(self) -> None:
        kotimaa_record = _record("kotimaa", source_words=320, blocks=1)
        talous_record = _record("talous", source_words=320, blocks=1)
        talous_record["packet"]["category_hint"] = "Talous"
        talous_record["original_article"]["category_hint"] = "Talous"
        thin_talous_record = _record("thin-talous", source_words=120, blocks=1)
        thin_talous_record["packet"]["category_hint"] = "Talous"
        thin_talous_record["original_article"]["category_hint"] = "Talous"

        kotimaa = self._write("ready", "kotimaa", kotimaa_record, age_hours=1)
        talous = self._write("ready", "talous", talous_record, age_hours=1)
        thin_talous = self._write("ready", "thin-talous", thin_talous_record, age_hours=1)

        self.assertGreater(staged_publish.priority_score(talous)[0], staged_publish.priority_score(kotimaa)[0])
        self.assertLess(staged_publish.priority_score(thin_talous)[0], staged_publish.priority_score(talous)[0])
        self.assertEqual(staged_publish.ready_sample(talous)["category_worker_priority_bonus"], 3.0)
        self.assertEqual(staged_publish.ready_sample(thin_talous)["category_worker_priority_bonus"], 0.0)

    def test_ready_sample_is_dry_run_metadata_only(self) -> None:
        path = self._write("ready", "sample", _record("sample", source_words=250, blocks=2), age_hours=5)

        sample = staged_publish.ready_sample(path)

        self.assertEqual(sample["file"], "sample.json")
        self.assertEqual(sample["packet_id"], "sample")
        self.assertGreater(sample["priority_score"], 0)
        self.assertTrue(path.exists())

    def test_status_source_metrics_match_monica_selected_packet_metrics(self) -> None:
        record = _record("selected-metrics", source_words=120, blocks=2)
        record["packet"]["source_text"] = " ".join(["sana"] * 600)
        record["packet"]["clean_source_blocks"] = [
            {"source": "Testi 0", "text": " ".join(["sana"] * 60), "word_count": 60},
            {"source": "Testi 1", "text": " ".join(["sana"] * 60), "word_count": 60},
        ]
        path = self._write("ready", "selected-metrics", record, age_hours=1)

        data = staged_publish.read_queue_record(path)

        self.assertEqual(staged_publish.packet_source_words(data), 120)
        self.assertEqual(staged_publish.packet_source_blocks(data), 2)
        sample = staged_publish.ready_sample(path)
        self.assertEqual(sample["source_words"], 120)
        self.assertEqual(sample["source_blocks"], 2)


    @patch.object(staged_publish, "_run_monica")
    def test_monica_worker_records_near_short_repair_markers_in_outbox(self, run_mock) -> None:
        for suffix, stale_category, canonical_category in (
            ("talous", "Ulkomaat", "Talous"),
            ("ulkomaat", "Kotimaa", "Ulkomaat"),
        ):
            with self.subTest(
                stale_category=stale_category,
                canonical_category=canonical_category,
            ):
                packet_id = f"pkt-worker-near-short-{suffix}"
                record = _record(packet_id, source_words=330, blocks=3)
                record["packet"].update(
                    {
                        "packet_id": packet_id,
                        "story_confidence": 0.9,
                        "category": stale_category,
                        "category_hint": stale_category,
                        "selected_source_provenance_error": "",
                        "source_selection_outcome": "usable_source_packet",
                        "clean_source_blocks": [
                            {
                                "source": "Testi 1",
                                "source_url": "https://testi.example/story",
                                "source_domain": "testi.example",
                                "text": " ".join([f"sana{index}"] * 110),
                                "word_count": 110,
                            }
                            for index in range(3)
                        ],
                        "selected_source": {
                            "name": "Testi 1",
                            "url": "https://testi.example/story",
                            "domain": "testi.example",
                        },
                    }
                )
                record["original_article"]["_guessed_category"] = canonical_category
                path = self._write("ready", packet_id, record, age_hours=1)
                lead = (
                    "Aloituskappale sisältää riittävästi sanoja ja kuvaa asian taustan, "
                    "vaikutukset sekä jatkon lukijalle selkeästi, ja mukana on vielä lisää "
                    "varmistavia sanoja lukijalle nyt, jotta pituusraja täyttyy varmasti "
                    "tässä testissä nyt selvästi."
                )

                def structured_content(filler_words: int) -> str:
                    first = filler_words // 3
                    second = filler_words // 3
                    third = filler_words - first - second
                    return "\n\n".join(
                        [
                            lead,
                            "## Tausta",
                            " ".join(["sana"] * first),
                            " ".join(["sana"] * second),
                            "## Vaikutukset",
                            " ".join(["sana"] * third),
                        ]
                    )

                near_payload = {
                    "packet_id": packet_id,
                    "title": "Lähes valmis artikkeli",
                    "summary": "Lähes valmis yhteenveto.",
                    "content": structured_content(213),
                    "category": canonical_category,
                    "tags": ["talous", "testi", "korjaus"],
                    "summary_bullets": ["Yksi asia", "Toinen asia", "Kolmas asia"],
                    "content_type": "article",
                    "editorial_reviewed": True,
                    "confidence": 0.9,
                    "journalist_note": " ",
                    "source_usage": [
                        {
                            "source_url": "https://testi.example/story",
                            "used": True,
                            "dependent_claims": [
                                "Lähde tukee artikkelin testiväitettä."
                            ],
                        }
                    ],
                }
                repaired_payload = {
                    **near_payload,
                    "content": structured_content(264),
                }
                run_mock.side_effect = [
                    json.dumps(near_payload),
                    json.dumps(near_payload),
                    json.dumps(repaired_payload),
                ]

                status, _ = staged_publish.process_one_packet(
                    path, type("Args", (), {})()
                )

                self.assertEqual(status, "ok")
                outbox = json.loads(
                    (self.root / "outbox" / f"{packet_id}.json").read_text(
                        encoding="utf-8"
                    )
                )
                repair = outbox["repair"]
                self.assertEqual(repair["repair_attempt"], "source_backed_near_short")
                self.assertEqual(repair["pre_repair_word_count"], 247)
                self.assertGreaterEqual(repair["post_repair_word_count"], 250)
                self.assertEqual(repair["repair_result"], "published")
                self.assertTrue(repair["source_block_ids_used_for_repair"])
                self.assertEqual(
                    outbox["article"]["monica_repair"]["repair_attempt"],
                    "source_backed_near_short",
                )
                self.assertEqual(outbox["packet"]["category"], canonical_category)
                self.assertEqual(
                    outbox["packet"]["category_hint"], canonical_category
                )
                self.assertEqual(
                    outbox["packet"]["source_usage_contract"], "v1"
                )
                preflight = staged_publish.evaluate_publish_preflight(outbox)
                self.assertEqual(preflight.action, "publish")
                self.assertEqual(
                    preflight.categories,
                    (canonical_category,) * 3,
                )
                self.assertEqual(preflight.reasons, ())
                self.assertEqual(preflight.hidden_source_urls, ())

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


class CategoryDecisionTraceTests(unittest.TestCase):
    def test_retained_disagreements_include_actual_published_category(self) -> None:
        published = Path(__file__).resolve().parent / "queues" / "staged" / "published"
        expected = {
            "20260711T203153Z_b15231a0f0": {
                "guard": "Kotimaa",
                "writer": "Ulkomaat",
                "publisher": "Talous",
            },
            "20260713T061121Z_40f48c408f": {
                "guard": "Kotimaa",
                "writer": "Kotimaa",
                "publisher": "Talous",
            },
        }

        for packet_id, decisions in expected.items():
            with self.subTest(packet_id=packet_id):
                data = staged_publish.read_queue_record(published / f"{packet_id}.json")
                trace = staged_publish.category_decision_trace(data)
                self.assertEqual(trace["packet_id"], packet_id)
                self.assertEqual(trace["decisions"], decisions)
                self.assertTrue(trace["disagreement"])

    def test_stable_talous_trace_is_not_marked_as_disagreement(self) -> None:
        data = {
            "packet": {"packet_id": "stable-talous", "category": "Talous"},
            "payload": {"category": "Talous"},
            "article": {
                "category": "Talous",
                "title": "Yhtiön tulos kasvoi",
                "summary": "Liikevaihto ja tulos kasvoivat.",
                "content": "Yhtiö raportoi liikevaihdon ja tuloksen kasvusta.",
            },
        }

        trace = staged_publish.category_decision_trace(data)

        self.assertEqual(
            trace["decisions"],
            {"guard": "Talous", "writer": "Talous", "publisher": "Talous"},
        )
        self.assertFalse(trace["disagreement"])


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

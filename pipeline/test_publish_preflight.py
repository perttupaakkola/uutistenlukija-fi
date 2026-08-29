#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from . import staged_publish, publisher
    from .publish_preflight import evaluate_publish_preflight
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
    import publisher
    import staged_publish
    from publish_preflight import evaluate_publish_preflight


def _words(count: int, prefix: str = "sana") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _record(
    *,
    packet_category: str = "Ulkomaat",
    payload_category: str = "Ulkomaat",
    article_category: str = "Ulkomaat",
    source_blocks: list[dict] | None = None,
    article_words: int = 220,
    content_prefix: str = "",
) -> dict:
    source_blocks = source_blocks or [
        {
            "source": "Example News",
            "source_url": "https://example.test/story",
            "source_domain": "example.test",
            "text": _words(220, "source"),
            "word_count": 220,
        }
    ]
    article_content = " ".join(part for part in [content_prefix, _words(article_words, "article")] if part)
    return {
        "packet": {
            "packet_id": "packet-1",
            "category": packet_category,
            "clean_source_blocks": source_blocks,
        },
        "payload": {"category": payload_category},
        "article": {
            "title": "Testiuutinen",
            "category": article_category,
            "content": article_content,
            "source_url": "https://example.test/story",
        },
    }


class PublishPreflightTests(unittest.TestCase):
    def test_outbox_supply_summary_is_mutually_exclusive_and_reasoned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            publish = _record()
            review = _record(source_blocks=[{
                "source": "Example News",
                "source_url": "https://example.test/story",
                "source_domain": "example.test",
                "text": _words(100, "source"),
                "word_count": 100,
            }])
            reject = _record(
                packet_category="Kotimaa",
                payload_category="Ulkomaat",
                article_category="Ulkomaat",
            )
            paths = []
            before = {}
            for index, record in enumerate((publish, review, reject)):
                path = root / f"{index}.json"
                path.write_text(json.dumps(record), encoding="utf-8")
                paths.append(path)
                before[path] = path.read_bytes()

            summary = staged_publish.summarize_outbox_supply(paths)

            self.assertEqual(summary["raw_outbox"], 3)
            self.assertEqual(
                summary["action_counts"],
                {"publish": 1, "monica_review": 1, "reject": 1},
            )
            self.assertEqual(
                summary["primary_reason_buckets"]["publish"],
                {"eligible": 1},
            )
            self.assertEqual(
                summary["primary_reason_buckets"]["monica_review"],
                {"thin_distinct_source": 1},
            )
            self.assertEqual(
                summary["primary_reason_buckets"]["reject"],
                {"category_disagreement": 1},
            )
            self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_cmd_publish_writes_clean_runner_cycle_without_publishing_holds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp) / "staged"
            outbox = staged_root / "outbox"
            outbox.mkdir(parents=True)
            (staged_root / "failed").mkdir()
            review = _record(source_blocks=[{
                "source": "Example News",
                "source_url": "https://example.test/story",
                "source_domain": "example.test",
                "text": _words(100, "source"),
                "word_count": 100,
            }])
            reject = _record(
                packet_category="Kotimaa",
                payload_category="Ulkomaat",
                article_category="Ulkomaat",
            )
            paths = []
            for name, record in (("review.json", review), ("reject.json", reject)):
                path = outbox / name
                path.write_text(json.dumps(record), encoding="utf-8")
                paths.append(path)
            before = {path: path.read_bytes() for path in paths}
            outcome_path = Path(tmp) / "runner/staged-publish-cycle.json"
            args = SimpleNamespace(
                max_articles=3,
                dry_run=False,
                dedup_window=72,
                git_push=False,
                outcome_json=str(outcome_path),
            )

            with patch.object(staged_publish, "STAGED_ROOT", staged_root), \
                 patch.object(staged_publish, "run_quality_gate") as quality_gate:
                status = staged_publish.cmd_publish(args)

            self.assertEqual(status, 0)
            quality_gate.assert_not_called()
            self.assertEqual({path: path.read_bytes() for path in paths}, before)
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            self.assertEqual(outcome["schema"], staged_publish.PUBLISH_CYCLE_SCHEMA)
            self.assertTrue(outcome["admitted"])
            self.assertEqual(outcome["outcome"], "skip")
            self.assertEqual(outcome["result"], "no_publish_eligible_supply")
            self.assertEqual(outcome["supply"]["raw_outbox"], 2)
            self.assertEqual(
                outcome["supply"]["action_counts"],
                {"publish": 0, "monica_review": 1, "reject": 1},
            )
            self.assertEqual(outcome["attempted"], 0)
            self.assertEqual(outcome["published"], 0)
            self.assertEqual(outcome["held"], 1)
            self.assertEqual(outcome["rejected"], 1)

    def test_cmd_publish_writes_terminal_cycle_when_execution_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp) / "staged"
            (staged_root / "outbox").mkdir(parents=True)
            outcome_path = Path(tmp) / "runner/staged-publish-cycle.json"
            args = SimpleNamespace(
                max_articles=3,
                dry_run=False,
                dedup_window=72,
                git_push=False,
                outcome_json=str(outcome_path),
            )

            with (
                patch.object(staged_publish, "STAGED_ROOT", staged_root),
                patch.object(
                    staged_publish,
                    "load_outbox",
                    side_effect=RuntimeError("synthetic execution failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "synthetic execution failure"),
            ):
                staged_publish.cmd_publish(args)

            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            self.assertEqual(outcome["outcome"], "error")
            self.assertEqual(outcome["result"], "exception:RuntimeError")
            self.assertEqual(outcome["return_code"], 1)
            self.assertTrue(outcome["ts"])

    def test_matching_categories_and_public_source_pass(self) -> None:
        record = _record(
            packet_category="ulkomaat",
            payload_category="ULKOMAAT",
            article_category="Ulkomaat",
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "publish")
        self.assertEqual(result.categories, ("Ulkomaat", "Ulkomaat", "Ulkomaat"))
        self.assertEqual(result.distinct_source_words, 220)
        self.assertEqual(result.article_words, 220)
        self.assertEqual(result.reasons, ())

    def test_retained_concert_with_unanimous_wrong_category_routes_to_monica(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "queues/staged/failed/20260719T233133Z_1573541d16.json"
        )
        before = path.read_bytes()
        record = json.loads(before)

        result = evaluate_publish_preflight(record)
        eligible = staged_publish.apply_publish_preflight([(path, record)])

        self.assertEqual(result.action, "monica_review")
        self.assertTrue(result.requires_monica_review)
        self.assertEqual(result.categories, ("Ulkomaat", "Ulkomaat", "Ulkomaat"))
        self.assertEqual(result.reasons, ("entertainment_category_review",))
        self.assertEqual(eligible, [])
        self.assertEqual(path.read_bytes(), before)

    def test_concertinaed_does_not_trigger_entertainment_review(self) -> None:
        record = _record()
        record["payload"]["tags"] = ["viihde"]
        record["packet"]["source_text"] = (
            "The Bayeux Tapestry was concertinaed for transport to the exhibition."
        )
        before = deepcopy(record)

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "publish")
        self.assertFalse(result.requires_monica_review)
        self.assertNotIn("entertainment_category_review", result.reasons)
        self.assertEqual(record, before)

    def test_genuine_performance_terms_still_trigger_entertainment_review(self) -> None:
        for performance_term in ("concert", "concerts", "konsertti", "esiintyy"):
            with self.subTest(performance_term=performance_term):
                record = _record()
                record["payload"]["tags"] = ["viihde"]
                record["packet"]["headline_seed"] = (
                    f"Artist {performance_term} tonight"
                )

                result = evaluate_publish_preflight(record)

                self.assertEqual(result.action, "monica_review")
                self.assertTrue(result.requires_monica_review)
                self.assertEqual(result.reasons, ("entertainment_category_review",))

    def test_bayeux_packet_is_immutable_and_publish_eligible(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "fixtures/publish_preflight/bayeux-publish-eligible.json"
        )
        before = path.read_bytes()
        self.assertEqual(
            hashlib.sha256(before).hexdigest(),
            "1da8e5a8e12cc5e3146b7f2f952f2c7c79754ba7368fccb5c68cf4da24a67d52",
        )
        record = json.loads(before)
        original = deepcopy(record)

        result = evaluate_publish_preflight(record)
        eligible = staged_publish.apply_publish_preflight([(path, record)])

        self.assertEqual(result.action, "publish")
        self.assertFalse(result.requires_monica_review)
        self.assertEqual(result.reasons, ())
        self.assertEqual(eligible, [(path, record)])
        self.assertEqual(record, original)
        self.assertEqual(path.read_bytes(), before)

    def test_retained_bbc_brief_keeps_independent_density_holds(self) -> None:
        path = (
            Path(__file__).resolve().parent
            / "queues/staged/published/20260719T230120Z_8b790c104e.json"
        )
        before = path.read_bytes()
        record = json.loads(before)

        result = evaluate_publish_preflight(record)
        eligible = staged_publish.apply_publish_preflight([(path, record)])

        self.assertEqual(result.action, "reject")
        self.assertIn("category_disagreement", result.reasons)
        self.assertIn("thin_distinct_source", result.reasons)
        self.assertIn("article_source_ratio_exceeded", result.reasons)
        self.assertNotIn("entertainment_category_review", result.reasons)
        self.assertEqual(eligible, [])
        self.assertEqual(path.read_bytes(), before)

    def test_category_disagreement_rejects_before_publish(self) -> None:
        record = _record(packet_category="Kotimaa", payload_category="Ulkomaat", article_category="Ulkomaat")

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertIn("category_disagreement", result.reasons)

    def test_effective_publisher_category_must_match_packet_and_payload(self) -> None:
        record = _record(
            packet_category="Tiede",
            payload_category="Tiede",
            article_category="Tiede",
            content_prefix="Poliisi tutkii koulussa tapahtunutta ampumista.",
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.categories, ("Tiede", "Tiede", "Kotimaa"))
        self.assertEqual(result.action, "reject")
        self.assertIn("category_disagreement", result.reasons)

    def test_missing_or_unknown_category_rejects(self) -> None:
        missing = evaluate_publish_preflight(_record(payload_category=""))
        unknown = evaluate_publish_preflight(_record(article_category="Muu"))
        missing_packet = _record()
        missing_packet["packet"].pop("category")
        missing_packet["packet"]["category_hint"] = "Ulkomaat"

        self.assertEqual(missing.action, "reject")
        self.assertIn("category_unresolved", missing.reasons)
        self.assertEqual(unknown.action, "reject")
        self.assertIn("category_unresolved", unknown.reasons)
        packet_result = evaluate_publish_preflight(missing_packet)
        self.assertEqual(packet_result.action, "reject")
        self.assertIn("category_unresolved", packet_result.reasons)

    def test_every_selected_source_url_must_be_public(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public News",
                    "source_url": "https://public.test/story",
                    "text": _words(120, "public"),
                },
                {
                    "source": "Hidden News",
                    "source_url": "https://hidden.test/report",
                    "text": _words(120, "hidden"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://public.test/story",
                "content": "[Public News](https://public.test/story) " + _words(220, "article"),
                "journalist_note": "Hidden News: https://hidden.test/report",
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertEqual(result.hidden_source_urls, ("https://hidden.test/report",))
        self.assertIn("selected_source_not_public", result.reasons)

    def test_same_domain_different_public_url_does_not_bypass_source_check(self) -> None:
        record = _record()
        record["article"]["source_url"] = "https://example.test/different-story"

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertEqual(result.hidden_source_urls, ("https://example.test/story",))

    def test_shadowed_link_does_not_expose_selected_source(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public",
                    "source_url": "https://public.test/story",
                    "text": _words(110, "public"),
                },
                {
                    "source": "Shadowed",
                    "source_url": "https://shadowed.test/report",
                    "text": _words(110, "shadowed"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://public.test/story",
                "link": "https://shadowed.test/report",
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertEqual(result.hidden_source_urls, ("https://shadowed.test/report",))

    def test_truncated_description_does_not_expose_selected_source(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public",
                    "source_url": "https://public.test/story",
                    "text": _words(110, "public"),
                },
                {
                    "source": "Truncated",
                    "source_url": "https://truncated.test/report",
                    "text": _words(110, "truncated"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://public.test/story",
                "description": "x" * 156 + " https://truncated.test/report",
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertEqual(result.hidden_source_urls, ("https://truncated.test/report",))

    def test_fifth_summary_bullet_and_fourth_key_point_do_not_expose_sources(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public",
                    "source_url": "https://public.test/story",
                    "text": _words(80, "public"),
                },
                {
                    "source": "Fifth bullet",
                    "source_url": "https://fifth-bullet.test/report",
                    "text": _words(80, "bullet"),
                },
                {
                    "source": "Fourth key point",
                    "source_url": "https://fourth-key.test/report",
                    "text": _words(80, "key"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://public.test/story",
                "summary_bullets": [
                    "First",
                    "Second",
                    "Third",
                    "Fourth",
                    "Fifth https://fifth-bullet.test/report",
                ],
                "key_points": [
                    "First",
                    "Second",
                    "Third",
                    "Fourth https://fourth-key.test/report",
                ],
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertEqual(
            result.hidden_source_urls,
            (
                "https://fifth-bullet.test/report",
                "https://fourth-key.test/report",
            ),
        )

    def test_selected_source_block_without_url_rejects(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Missing URL",
                    "source_url": "",
                    "text": _words(220, "source"),
                }
            ]
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertIn("selected_source_url_missing", result.reasons)

    def test_all_distinct_selected_source_urls_can_be_exposed_inline(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "First",
                    "source_url": "https://first.test/a",
                    "text": _words(110, "first"),
                },
                {
                    "source": "Second",
                    "source_url": "https://second.test/b",
                    "text": _words(110, "second"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://first.test/a",
                "content": (
                    "[First](https://first.test/a) [Second](https://second.test/b) "
                    + _words(220, "article")
                ),
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "publish")
        self.assertEqual(result.hidden_source_urls, ())

    def test_structured_attributions_are_the_shared_public_projection(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "First",
                    "source_url": "https://first.test/a",
                    "text": _words(110, "first"),
                },
                {
                    "source": "Second",
                    "source_url": "https://second.test/b",
                    "text": _words(110, "second"),
                },
            ],
        )
        record["article"].update(
            {
                "source_url": "https://first.test/a",
                "source_attributions": [
                    {"name": "First", "url": "https://first.test/a"},
                    {"name": "Second", "url": "https://second.test/b"},
                ],
            }
        )

        result = evaluate_publish_preflight(record)
        markdown = publisher._article_to_markdown(
            record["article"],
            "2026-07-28T12:00:00+00:00",
        )

        self.assertEqual(result.action, "publish")
        self.assertEqual(result.hidden_source_urls, ())
        self.assertIn("source_attributions:", markdown)
        self.assertIn('url: "https://first.test/a"', markdown)
        self.assertIn('url: "https://second.test/b"', markdown)

    def test_same_article_alias_is_counted_once_before_public_check(self) -> None:
        rss_url = (
            "https://www.bbc.co.uk/news/articles/c70gkg62w0ro"
            "?at_medium=RSS&at_campaign=rss"
        )
        canonical_url = "https://www.bbc.com/news/articles/c70gkg62w0ro"
        yahoo_url = "https://www.yahoo.com/entertainment/music/articles/example.html"
        record = _record(
            source_blocks=[
                {
                    "source": "BBC World",
                    "source_url": rss_url,
                    "text": _words(110, "bbc-rss"),
                },
                {
                    "source": "BBC",
                    "source_url": canonical_url,
                    "text": _words(110, "bbc-canonical"),
                },
                {
                    "source": "Yahoo",
                    "source_url": yahoo_url,
                    "text": _words(110, "yahoo"),
                },
            ],
        )
        record["packet"]["source_usage"] = [
            {
                "source_url": canonical_url,
                "used": False,
                "dependent_claims": [],
            }
        ]
        record["article"].update(
            {
                "source_url": rss_url,
                "source_attributions": [
                    {"name": "BBC World", "url": rss_url},
                    {"name": "Yahoo", "url": yahoo_url},
                ],
            }
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "publish")
        self.assertEqual(len(result.selected_source_urls), 2)
        self.assertEqual(len(result.public_source_urls), 2)
        self.assertEqual(result.hidden_source_urls, ())

    def test_explicit_unused_source_without_dependent_claim_is_exempt(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public",
                    "source_url": "https://public.test/story",
                    "text": _words(220, "public"),
                },
                {
                    "source": "Unused",
                    "source_url": "https://unused.test/context",
                    "text": _words(20, "unused"),
                },
            ],
        )
        record["article"]["source_url"] = "https://public.test/story"
        record["packet"]["source_usage"] = [
            {
                "source_url": "https://unused.test/context",
                "used": False,
                "dependent_claims": [],
            }
        ]

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "publish")
        self.assertEqual(result.hidden_source_urls, ())

    def test_unused_bypass_with_dependent_claim_still_rejects(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "Public",
                    "source_url": "https://public.test/story",
                    "text": _words(220, "public"),
                },
                {
                    "source": "Hidden",
                    "source_url": "https://hidden.test/report",
                    "text": _words(20, "hidden"),
                },
            ],
        )
        record["article"]["source_url"] = "https://public.test/story"
        record["packet"]["source_usage"] = [
            {
                "source_url": "https://hidden.test/report",
                "used": False,
                "dependent_claims": ["A hidden-source claim remains in the article"],
            }
        ]
        record["packet"]["unused_source_urls"] = ["https://hidden.test/report"]

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertIn("source_usage_invalid", result.reasons)
        self.assertEqual(result.hidden_source_urls, ("https://hidden.test/report",))

    def test_v1_source_usage_contract_rejects_missing_selected_rows(self) -> None:
        record = _record(
            source_blocks=[
                {
                    "source": "First",
                    "source_url": "https://first.test/story",
                    "text": _words(110, "first"),
                },
                {
                    "source": "Second",
                    "source_url": "https://second.test/story",
                    "text": _words(110, "second"),
                },
            ],
        )
        record["packet"]["source_usage_contract"] = "v1"
        record["packet"]["source_usage"] = [
            {
                "source_url": "https://first.test/story",
                "used": True,
                "dependent_claims": ["Ensimmäinen lähde tukee pääväitettä."],
            }
        ]
        record["article"]["source_attributions"] = [
            {"name": "First", "url": "https://first.test/story"}
        ]

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertIn("source_usage_invalid", result.reasons)

    def test_contained_duplicate_blocks_count_once_and_route_to_monica(self) -> None:
        full = _words(190, "source")
        tokens = full.split()
        first_half_with_wrapper = _words(10, "wrapper") + " " + " ".join(tokens[:95])
        second_half_with_wrapper = _words(20, "boilerplate") + " " + " ".join(tokens[95:])
        record = _record(
            source_blocks=[
                {"source": "Aggregator", "source_url": "https://example.test/story", "text": full},
                {"source": "Aggregator", "source_url": "https://example.test/story", "text": first_half_with_wrapper},
                {"source": "Aggregator", "source_url": "https://example.test/story", "text": second_half_with_wrapper},
            ],
            article_words=230,
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "monica_review")
        self.assertTrue(result.requires_monica_review)
        self.assertEqual(result.distinct_source_words, 190)
        self.assertIn("thin_distinct_source", result.reasons)

    def test_article_above_source_ratio_routes_to_monica(self) -> None:
        result = evaluate_publish_preflight(_record(article_words=298))

        self.assertEqual(result.action, "monica_review")
        self.assertIn("article_source_ratio_exceeded", result.reasons)

    def test_exact_source_ratio_boundary_can_publish(self) -> None:
        result = evaluate_publish_preflight(_record(article_words=297))

        self.assertEqual(result.article_source_ratio, 1.35)
        self.assertEqual(result.action, "publish")

    def test_sensitive_thin_story_requires_monica_restraint_review(self) -> None:
        result = evaluate_publish_preflight(
            _record(
                source_blocks=[
                    {
                        "source": "Wire",
                        "source_url": "https://example.test/story",
                        "text": _words(148, "source"),
                    }
                ],
                article_words=274,
                content_prefix="Hyökkäys ja kuolema vaativat varovaista käsittelyä.",
            )
        )

        self.assertEqual(result.action, "monica_review")
        self.assertTrue(result.requires_monica_review)
        self.assertTrue(result.sensitive)
        self.assertIn("sensitive_thin_story", result.reasons)

    def test_sensitive_story_with_sufficient_distinct_evidence_can_publish(self) -> None:
        result = evaluate_publish_preflight(
            _record(article_words=220, content_prefix="Hyökkäys käsitellään varovaisesti.")
        )

        self.assertEqual(result.action, "publish")
        self.assertFalse(result.requires_monica_review)
        self.assertTrue(result.sensitive)

    def test_sensitive_well_sourced_entertainment_hold_is_not_labeled_thin(self) -> None:
        record = _record(article_words=220)
        record["payload"]["tags"] = ["viihde"]
        record["packet"]["headline_seed"] = (
            "Konsertti järjestettiin onnettomuuden jälkeen"
        )

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "monica_review")
        self.assertTrue(result.requires_monica_review)
        self.assertTrue(result.sensitive)
        self.assertEqual(result.distinct_source_words, 220)
        self.assertEqual(result.article_words, 220)
        self.assertEqual(result.article_source_ratio, 1.0)
        self.assertEqual(result.reasons, ("entertainment_category_review",))

    def test_malformed_packet_and_payload_fail_closed_without_crashing(self) -> None:
        record = _record()
        record["packet"] = ["not", "a", "mapping"]
        record["payload"] = "not a mapping"

        result = evaluate_publish_preflight(record)

        self.assertEqual(result.action, "reject")
        self.assertIn("category_unresolved", result.reasons)

    def test_evaluation_does_not_mutate_record(self) -> None:
        record = _record(article_words=298)
        original = deepcopy(record)

        evaluate_publish_preflight(record)

        self.assertEqual(record, original)

    def test_cmd_publish_does_not_reach_existing_gates_for_rejected_record(self) -> None:
        record = _record(packet_category="Kotimaa", payload_category="Ulkomaat", article_category="Ulkomaat")
        args = SimpleNamespace(max_articles=1, dry_run=True, dedup_window=72, git_push=False)

        with patch.object(staged_publish, "load_outbox", return_value=[(object(), record)]), \
             patch.object(staged_publish, "run_quality_gate") as quality_gate, \
             patch.object(staged_publish, "publish_articles") as publish_articles:
            status = staged_publish.cmd_publish(args)

        self.assertEqual(status, 0)
        quality_gate.assert_not_called()
        publish_articles.assert_not_called()

    def test_load_outbox_order_uses_versioned_packet_and_path_not_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp)
            outbox = staged_root / "outbox"
            outbox.mkdir()
            specs = [
                ("z-path.json", "20260804T010000Z_first"),
                ("a-path.json", "20260804T020000Z_second"),
                ("m-path.json", "20260804T030000Z_third"),
            ]
            paths = []
            for index, (name, packet_id) in enumerate(specs):
                record = _record()
                record["packet"]["packet_id"] = packet_id
                path = outbox / name
                path.write_text(json.dumps(record), encoding="utf-8")
                os.utime(path, (1_700_000_300 - index, 1_700_000_300 - index))
                paths.append(path)

            with patch.object(staged_publish, "STAGED_ROOT", staged_root):
                first_order = [path.name for path, _ in staged_publish.load_outbox()]
                for index, path in enumerate(paths):
                    os.utime(path, (1_600_000_000 + index, 1_600_000_000 + index))
                second_order = [path.name for path, _ in staged_publish.load_outbox()]

            self.assertEqual(first_order, ["z-path.json", "a-path.json", "m-path.json"])
            self.assertEqual(second_order, first_order)

    def test_cmd_publish_scans_past_six_held_records_to_eligible_seventh(self) -> None:
        args = SimpleNamespace(max_articles=1, dry_run=True, dedup_window=72, git_push=False)

        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp)
            outbox = staged_root / "outbox"
            outbox.mkdir()
            held_paths: list[Path] = []
            original_bytes: dict[Path, bytes] = {}
            base_mtime = 1_700_000_000
            for index in range(6):
                held = _record(
                    packet_category="Kotimaa",
                    payload_category="Ulkomaat",
                    article_category="Ulkomaat",
                )
                packet_id = f"20260804T00000{index + 1}Z_held-{index + 1}"
                held["packet"]["packet_id"] = packet_id
                path = outbox / f"{packet_id}.json"
                path.write_text(json.dumps(held), encoding="utf-8")
                os.utime(path, (base_mtime + index, base_mtime + index))
                held_paths.append(path)
                original_bytes[path] = path.read_bytes()

            eligible = _record()
            eligible["packet"]["packet_id"] = "20260804T000007Z_eligible-7"
            eligible["article"]["title"] = "Eligible seventh"
            eligible_path = outbox / "20260804T000007Z_eligible-7.json"
            eligible_path.write_text(json.dumps(eligible), encoding="utf-8")
            os.utime(eligible_path, (base_mtime + 6, base_mtime + 6))
            original_bytes[eligible_path] = eligible_path.read_bytes()

            later_eligible = _record()
            later_eligible["packet"]["packet_id"] = "20260804T000008Z_eligible-8"
            later_eligible["article"]["title"] = "Eligible eighth"
            later_eligible_path = outbox / "20260804T000008Z_eligible-8.json"
            later_eligible_path.write_text(json.dumps(later_eligible), encoding="utf-8")
            os.utime(later_eligible_path, (base_mtime + 7, base_mtime + 7))
            original_bytes[later_eligible_path] = later_eligible_path.read_bytes()

            with patch.object(staged_publish, "STAGED_ROOT", staged_root), \
                 patch.object(
                     staged_publish,
                     "run_quality_gate",
                     side_effect=lambda articles: SimpleNamespace(passed=articles, rejected=[]),
                 ) as quality_gate, \
                 patch.object(staged_publish, "filter_new_articles", side_effect=lambda articles: articles), \
                 patch.object(
                     staged_publish,
                     "check_published_duplicates",
                     side_effect=lambda articles, window_hours: articles,
                 ), \
                 patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
                 patch.object(
                     staged_publish,
                     "enrich_images_for_articles",
                     return_value={
                         "total": 1,
                         "images": 0,
                         "unsplash": 0,
                         "pexels": 0,
                         "generated": 0,
                         "category_fallback": 0,
                         "missing": 1,
                     },
                 ):
                status = staged_publish.cmd_publish(args)

            self.assertEqual(status, 0)
            quality_gate.assert_called_once_with([eligible["article"]])
            self.assertEqual(
                [path.name for path in held_paths],
                [f"20260804T00000{index}Z_held-{index}.json" for index in range(1, 7)],
            )
            self.assertEqual(
                {path: path.read_bytes() for path in original_bytes},
                original_bytes,
            )

    def test_cmd_publish_scans_past_quality_reject_to_later_pass(self) -> None:
        args = SimpleNamespace(max_articles=1, dry_run=False, dedup_window=72, git_push=False)

        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp)
            outbox = staged_root / "outbox"
            outbox.mkdir()
            failed = staged_root / "failed"
            failed.mkdir()
            base_mtime = 1_700_000_000
            records = [
                (
                    "20260804T000001Z_held-1.json",
                    "held-1",
                    _record(
                        packet_category="Kotimaa",
                        payload_category="Ulkomaat",
                        article_category="Ulkomaat",
                    ),
                ),
                ("20260804T000002Z_quality-reject.json", "quality-reject", _record()),
                ("20260804T000003Z_quality-pass.json", "quality-pass", _record()),
                ("20260804T000004Z_after-cap.json", "after-cap", _record()),
            ]
            original_bytes: dict[Path, bytes] = {}
            for index, (name, title, record) in enumerate(records):
                record["packet"]["packet_id"] = Path(name).stem
                record["article"]["title"] = title
                path = outbox / name
                path.write_text(json.dumps(record), encoding="utf-8")
                os.utime(path, (base_mtime + index, base_mtime + index))
                original_bytes[path] = path.read_bytes()

            def quality_result(articles: list[dict]) -> SimpleNamespace:
                article = articles[0]
                if article["title"] == "quality-reject":
                    return SimpleNamespace(passed=[], rejected=articles)
                return SimpleNamespace(passed=articles, rejected=[])

            with patch.object(staged_publish, "STAGED_ROOT", staged_root), \
                 patch.object(
                     staged_publish,
                     "run_quality_gate",
                     side_effect=quality_result,
                 ) as quality_gate, \
                 patch.object(
                     staged_publish,
                     "filter_new_articles",
                     side_effect=lambda articles: articles,
                 ) as filter_new_articles, \
                 patch.object(
                     staged_publish,
                     "check_published_duplicates",
                     side_effect=lambda articles, window_hours: articles,
                 ), \
                 patch.object(
                     staged_publish,
                     "dedup_within_batch",
                     side_effect=lambda articles: articles,
                 ), \
                 patch.object(
                     staged_publish,
                     "enrich_images_for_articles",
                     return_value={
                         "total": 1,
                         "images": 0,
                         "unsplash": 0,
                         "pexels": 0,
                         "generated": 0,
                         "category_fallback": 0,
                         "missing": 1,
                     },
                 ) as enrich_images, \
                 patch.object(
                     staged_publish,
                     "publish_articles",
                     return_value=[],
                 ) as publish_articles:
                status = staged_publish.cmd_publish(args)

            self.assertEqual(status, 0)
            self.assertEqual(
                [
                    [article["title"] for article in quality_call.args[0]]
                    for quality_call in quality_gate.call_args_list
                ],
                [["quality-reject"], ["quality-pass"]],
            )
            passed_article = records[2][2]["article"]
            filter_new_articles.assert_called_once_with([passed_article])
            enrich_images.assert_called_once_with([passed_article])
            publish_articles.assert_called_once_with([passed_article])

            held_path = outbox / "20260804T000001Z_held-1.json"
            rejected_path = outbox / "20260804T000002Z_quality-reject.json"
            passed_path = outbox / "20260804T000003Z_quality-pass.json"
            after_cap_path = outbox / "20260804T000004Z_after-cap.json"
            self.assertEqual(held_path.read_bytes(), original_bytes[held_path])
            self.assertFalse(rejected_path.exists())
            rejected = json.loads((failed / rejected_path.name).read_text(encoding="utf-8"))
            self.assertTrue(rejected["quality_gate_rejected"])
            self.assertNotIn("duplicate_rejected", rejected)
            self.assertEqual(passed_path.read_bytes(), original_bytes[passed_path])
            self.assertEqual(after_cap_path.read_bytes(), original_bytes[after_cap_path])

    def test_cmd_publish_applies_cap_after_dedup_and_leaves_unselected_unique(self) -> None:
        args = SimpleNamespace(max_articles=1, dry_run=False, dedup_window=72, git_push=False)

        with tempfile.TemporaryDirectory() as tmp:
            staged_root = Path(tmp)
            outbox = staged_root / "outbox"
            failed = staged_root / "failed"
            outbox.mkdir()
            failed.mkdir()
            records = [
                ("20260804T010000Z_published-duplicate.json", "published-duplicate"),
                ("20260804T020000Z_unique.json", "unique"),
                ("20260804T030000Z_unselected-unique.json", "unselected-unique"),
            ]
            by_title: dict[str, tuple[Path, dict, bytes]] = {}
            for index, (name, title) in enumerate(records):
                record = _record()
                record["packet"]["packet_id"] = Path(name).stem
                record["article"]["title"] = title
                path = outbox / name
                path.write_text(json.dumps(record), encoding="utf-8")
                os.utime(path, (1_700_100_000 + index, 1_700_100_000 + index))
                by_title[title] = (path, record, path.read_bytes())

            def published_dedup(articles: list[dict], window_hours: int) -> list[dict]:
                self.assertEqual(window_hours, 72)
                return [article for article in articles if article["title"] != "published-duplicate"]

            with patch.object(staged_publish, "STAGED_ROOT", staged_root), \
                 patch.object(
                     staged_publish,
                     "run_quality_gate",
                     side_effect=lambda articles: SimpleNamespace(passed=articles, rejected=[]),
                 ) as quality_gate, \
                 patch.object(staged_publish, "filter_new_articles", side_effect=lambda articles: articles), \
                 patch.object(staged_publish, "check_published_duplicates", side_effect=published_dedup), \
                 patch.object(staged_publish, "dedup_within_batch", side_effect=lambda articles: articles), \
                 patch.object(
                     staged_publish,
                     "enrich_images_for_articles",
                     return_value={
                         "total": 1,
                         "images": 0,
                         "unsplash": 0,
                         "pexels": 0,
                         "generated": 0,
                         "category_fallback": 0,
                         "missing": 1,
                     },
                 ), \
                 patch.object(staged_publish, "publish_articles", return_value=[]) as publish_articles:
                status = staged_publish.cmd_publish(args)

            self.assertEqual(status, 0)
            self.assertEqual(
                [call.args[0][0]["title"] for call in quality_gate.call_args_list],
                ["published-duplicate", "unique"],
            )
            publish_articles.assert_called_once_with([by_title["unique"][1]["article"]])
            duplicate_path = by_title["published-duplicate"][0]
            self.assertFalse(duplicate_path.exists())
            duplicate = json.loads((failed / duplicate_path.name).read_text(encoding="utf-8"))
            self.assertTrue(duplicate["duplicate_rejected"])
            self.assertNotIn("quality_gate_rejected", duplicate)
            self.assertEqual(
                by_title["unselected-unique"][0].read_bytes(),
                by_title["unselected-unique"][2],
            )


if __name__ == "__main__":
    unittest.main()

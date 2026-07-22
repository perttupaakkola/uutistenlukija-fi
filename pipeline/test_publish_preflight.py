#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from . import staged_publish
    from .publish_preflight import evaluate_publish_preflight
except ImportError:  # pragma: no cover - direct execution from pipeline cwd
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
        self.assertEqual(result.hidden_source_urls, ("https://hidden.test/report",))

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


if __name__ == "__main__":
    unittest.main()

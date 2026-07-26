#!/usr/bin/env python3
"""Deterministic lifecycle fixtures for utility guides."""

from __future__ import annotations

import copy
import unittest
from datetime import date
from pathlib import Path

from guide_lifecycle import evaluate_guide, load_guide, validate_guide


ROOT = Path(__file__).resolve().parents[1]


def words(count: int) -> str:
    return " ".join(f"sana{i}" for i in range(count))


def valid_meta() -> dict:
    return {
        "title": "Testiopas",
        "description": "Testioppaan kuvaus.",
        "date": "2026-07-01",
        "updated_at": "2026-07-01",
        "reviewed_at": "2026-07-01",
        "next_review_at": "2026-07-15",
        "expires_at": "2026-07-31",
        "correction_url": "mailto:info@uutistenlukija.fi",
        "search_terms": ["testi", "opas"],
        "sources": [
            {
                "name": "Ensimmäinen",
                "url": "https://one.example/checker",
                "official": True,
                "source_checked_at": "2026-07-01",
                "authoritative_checker": True,
            },
            {
                "name": "Toinen",
                "url": "https://two.example/stores",
                "official": True,
                "source_checked_at": "2026-07-01",
            },
            {
                "name": "Kolmas",
                "url": "https://three.example/locations",
                "official": True,
                "source_checked_at": "2026-07-01",
            },
        ],
    }


class GuideLifecycleTest(unittest.TestCase):
    def test_899_words_is_rejected(self) -> None:
        errors, count = validate_guide(valid_meta(), words(899))
        self.assertEqual(count, 899)
        self.assertTrue(any("outside 900-1500" in error for error in errors))

    def test_900_and_1500_words_are_accepted(self) -> None:
        for count in (900, 1500):
            with self.subTest(count=count):
                errors, actual = validate_guide(valid_meta(), words(count))
                self.assertEqual(actual, count)
                self.assertEqual(errors, [])

    def test_source_checker_and_date_bounds_fail_closed(self) -> None:
        cases: list[tuple[str, dict]] = []

        too_few_sources = valid_meta()
        too_few_sources["sources"] = too_few_sources["sources"][:2]
        cases.append(("sources", too_few_sources))

        no_checker = valid_meta()
        no_checker["sources"][0].pop("authoritative_checker")
        cases.append(("checker", no_checker))

        review_too_late = valid_meta()
        review_too_late["next_review_at"] = "2026-07-16"
        cases.append(("review bound", review_too_late))

        expiry_too_late = valid_meta()
        expiry_too_late["expires_at"] = "2026-08-01"
        cases.append(("expiry bound", expiry_too_late))

        stale_source_check = valid_meta()
        stale_source_check["sources"][1]["source_checked_at"] = "2026-06-30"
        cases.append(("source checked", stale_source_check))

        for label, meta in cases:
            with self.subTest(label=label):
                lifecycle = evaluate_guide(
                    meta,
                    words(900),
                    today=date(2026, 7, 2),
                )
                self.assertEqual(lifecycle.state, "invalid")
                self.assertFalse(lifecycle.discoverable)
                self.assertFalse(lifecycle.promoted)
                self.assertTrue(lifecycle.errors)

    def test_current_review_due_and_expired_discovery(self) -> None:
        meta = valid_meta()
        fixtures = (
            (date(2026, 7, 14), "current", True, True),
            (date(2026, 7, 15), "review_due", True, False),
            (date(2026, 7, 30), "review_due", True, False),
            (date(2026, 7, 31), "expired", False, False),
        )
        for today, state, discoverable, promoted in fixtures:
            with self.subTest(today=today):
                lifecycle = evaluate_guide(meta, words(900), today=today)
                self.assertEqual(lifecycle.state, state)
                self.assertEqual(lifecycle.discoverable, discoverable)
                self.assertEqual(lifecycle.promoted, promoted)

    def test_draft_and_noindex_fail_closed_from_discovery(self) -> None:
        for flag in ("draft", "noindex"):
            with self.subTest(flag=flag):
                meta = copy.deepcopy(valid_meta())
                meta[flag] = True
                lifecycle = evaluate_guide(
                    meta,
                    words(900),
                    today=date(2026, 7, 2),
                )
                self.assertEqual(lifecycle.state, flag)
                self.assertFalse(lifecycle.discoverable)
                self.assertFalse(lifecycle.promoted)
                self.assertEqual(lifecycle.errors, ())

    def test_missing_required_metadata_is_invalid(self) -> None:
        for field in (
            "title",
            "description",
            "reviewed_at",
            "updated_at",
            "next_review_at",
            "expires_at",
            "correction_url",
            "search_terms",
        ):
            with self.subTest(field=field):
                meta = copy.deepcopy(valid_meta())
                meta.pop(field)
                lifecycle = evaluate_guide(meta, words(900))
                self.assertEqual(lifecycle.state, "invalid")
                self.assertIn(f"missing required field: {field}", lifecycle.errors)

    def test_repository_guide_is_valid_and_current(self) -> None:
        path = ROOT / "content/oppaat/kauppojen-aukioloajat.md"
        meta, body = load_guide(path)
        lifecycle = evaluate_guide(meta, body, today=date(2026, 7, 26))
        self.assertEqual(lifecycle.state, "current")
        self.assertTrue(lifecycle.promoted)
        self.assertGreaterEqual(lifecycle.word_count, 900)
        self.assertLessEqual(lifecycle.word_count, 1500)


if __name__ == "__main__":
    unittest.main()

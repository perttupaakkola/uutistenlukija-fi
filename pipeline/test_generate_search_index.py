#!/usr/bin/env python3
"""Search discovery contracts for the guide hub and canonical guide."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
import unicodedata
from datetime import date
from pathlib import Path
from unittest.mock import patch

from generate_search_index import (
    GUIDES_DIR,
    OUTPUT_PATH,
    build_guide_hub_record,
    build_guide_record,
)
from guide_lifecycle import load_guide


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "/oppaat/kauppojen-aukioloajat/"
LEGACY = (
    "/paasiaisopas/kaupat-auki/",
    "/vappuopas/kaupat-auki/",
)


def normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def matches(record: dict, query: str) -> bool:
    haystack = normalize(
        " ".join(
            [
                str(record.get("title", "")),
                str(record.get("description", "")),
                str(record.get("category", "")),
                " ".join(record.get("search_terms", [])),
            ]
        )
    )
    return all(term in haystack for term in normalize(query).split())


class GenerateSearchIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            [sys.executable, "pipeline/generate_search_index.py"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        cls.records = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

    def test_hub_and_current_guide_are_emitted_once_as_oppaat(self) -> None:
        hub = build_guide_hub_record()
        self.assertIsNotNone(hub)
        self.assertEqual(hub["url"], "/oppaat/")
        self.assertEqual(hub["category"], "Oppaat")

        guide = build_guide_record(
            GUIDES_DIR / "kauppojen-aukioloajat.md",
            today=date(2026, 7, 26),
        )
        self.assertIsNotNone(guide)
        self.assertEqual(guide["url"], CANONICAL)
        self.assertEqual(guide["category"], "Oppaat")

        urls = [record["url"] for record in self.records]
        self.assertEqual(urls.count("/oppaat/"), 1)
        self.assertEqual(urls.count(CANONICAL), 1)
        for legacy in LEGACY:
            self.assertNotIn(legacy, urls)

    def test_required_queries_surface_the_canonical_once(self) -> None:
        for query in ("oppaat", "kaupat auki", "aukioloajat", "pyhäpäivä"):
            with self.subTest(query=query):
                urls = [
                    record["url"]
                    for record in self.records
                    if matches(record, query)
                ]
                self.assertEqual(urls.count(CANONICAL), 1)
                for legacy in LEGACY:
                    self.assertNotIn(legacy, urls)

    def test_review_due_stays_searchable_without_freshness_signal(self) -> None:
        record = build_guide_record(
            GUIDES_DIR / "kauppojen-aukioloajat.md",
            today=date(2026, 8, 9),
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["date"], "")

    def test_guide_fails_closed_from_search_at_exact_expiry(self) -> None:
        record = build_guide_record(
            GUIDES_DIR / "kauppojen-aukioloajat.md",
            today=date(2026, 8, 25),
        )
        self.assertIsNone(record)

    def test_draft_and_noindex_guides_fail_closed_from_search(self) -> None:
        path = GUIDES_DIR / "kauppojen-aukioloajat.md"
        source_meta, body = load_guide(path)
        for flag in ("draft", "noindex"):
            with self.subTest(flag=flag):
                meta = copy.deepcopy(source_meta)
                meta[flag] = True
                with patch(
                    "generate_search_index.load_guide",
                    return_value=(meta, body),
                ):
                    record = build_guide_record(
                        path,
                        today=date(2026, 7, 26),
                    )
                self.assertIsNone(record)

    def test_client_search_consumes_terms_and_labels_oppaat(self) -> None:
        client = (ROOT / "static/js/search.js").read_text(encoding="utf-8")
        self.assertIn("oppaat: 'Oppaat'", client)
        self.assertIn("item.search_terms", client)
        self.assertIn("[title, summary, category, searchTerms]", client)


if __name__ == "__main__":
    unittest.main()

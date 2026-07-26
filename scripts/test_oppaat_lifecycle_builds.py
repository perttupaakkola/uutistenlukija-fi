#!/usr/bin/env python3
"""Assert deterministic review-due and expired Hugo render states."""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path

from test_oppaat_built_contract import (
    GUIDE_PATH,
    GUIDE_URL,
    HUB_PATH,
    HUB_URL,
    canonical_values,
    meta_content,
    read_page,
    schemas,
    sitemap_locations,
)


class BuiltLifecycleStateTest(unittest.TestCase):
    review_due: Path
    expired: Path

    def test_review_due_is_indexable_but_not_promoted(self) -> None:
        guide = read_page(self.review_due, GUIDE_PATH)
        hub = read_page(self.review_due, HUB_PATH)
        self.assertEqual(canonical_values(guide), [GUIDE_URL])
        self.assertEqual(meta_content(guide, "robots"), [])
        self.assertIn("Oppaan määräaikaistarkistus on tehtävä", guide)
        self.assertNotIn("class=guide-card>", hub)
        self.assertIn("Yhtään opasta ei ole juuri nyt voimassa ja tarkistettuna", hub)

        locations = sitemap_locations(self.review_due / "sitemap.xml")
        self.assertEqual(locations.count(HUB_URL), 1)
        self.assertEqual(locations.count(GUIDE_URL), 1)
        collection = next(
            item
            for item in schemas(hub)
            if item.get("@type") == "CollectionPage"
        )
        self.assertEqual(collection["mainEntity"]["itemListElement"], [])

    def test_expired_keeps_self_canonical_html_but_fails_closed(self) -> None:
        guide = read_page(self.expired, GUIDE_PATH)
        hub = read_page(self.expired, HUB_PATH)
        self.assertEqual(canonical_values(guide), [GUIDE_URL])
        self.assertEqual(meta_content(guide, "robots"), ["noindex,follow"])
        self.assertIn("Tämän oppaan voimassaolo on päättynyt", guide)
        self.assertNotIn("class=guide-card>", hub)

        locations = sitemap_locations(self.expired / "sitemap.xml")
        self.assertEqual(locations.count(HUB_URL), 1)
        self.assertEqual(locations.count(GUIDE_URL), 0)
        collection = next(
            item
            for item in schemas(hub)
            if item.get("@type") == "CollectionPage"
        )
        self.assertEqual(collection["mainEntity"]["itemListElement"], [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_due", type=Path)
    parser.add_argument("expired", type=Path)
    args = parser.parse_args()
    BuiltLifecycleStateTest.review_due = args.review_due.resolve()
    BuiltLifecycleStateTest.expired = args.expired.resolve()
    unittest.main(argv=["test_oppaat_lifecycle_builds.py"])


if __name__ == "__main__":
    main()

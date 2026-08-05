#!/usr/bin/env python3
"""Focused regressions for the daily recap generator and article selection."""

from html.parser import HTMLParser
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import generate_kooste


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "layouts" / "paivan-kooste" / "single.html"
AUGUST_4_RECAP = ROOT / "content" / "paivan-kooste" / "2026-08-04.md"


class KoostePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.card_links: list[str] = []
        self.empty_message = False
        self.image_links: list[str] = []
        self.sections: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "section" and "kooste-section" in classes:
            self.sections.append(values.get("id") or "")
        if tag == "a" and "kooste-card__link" in classes:
            self.card_links.append(values.get("href") or "")
        if tag == "a" and "kooste-card__image-wrap" in classes:
            self.image_links.append(values.get("href") or "")
        if tag == "p" and "kooste-empty" in classes:
            self.empty_message = True


def article(date: str, category: str) -> str:
    return f"""---
title: "Test article"
date: {date}
categories:
  - {category}
author: "Toimitus"
draft: false
---
"""


class GenerateKoosteTest(unittest.TestCase):
    def test_scan_posts_reads_block_style_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            posts = Path(temp_dir)
            fixtures = (
                ("kotimaa.md", "2026-08-04T05:00:00+00:00", "Kotimaa"),
                ("ulkomaat.md", "2026-08-04T12:00:00+00:00", "Ulkomaat"),
                ("talous.md", "2026-08-04T19:00:00+00:00", "Talous"),
            )
            for name, date, category in fixtures:
                (posts / name).write_text(article(date, category), encoding="utf-8")

            with mock.patch.object(generate_kooste, "POSTS_DIR", posts):
                active, total = generate_kooste.scan_posts(
                    generate_kooste.parse_article_date("2026-08-04T00:00:00Z"),
                    min_articles=3,
                )

        self.assertEqual(total, 3)
        self.assertEqual(active, ["kotimaa", "ulkomaat", "talous"])

    def test_august_4_recap_records_source_derived_sections(self) -> None:
        frontmatter = generate_kooste.parse_frontmatter(
            AUGUST_4_RECAP.read_text(encoding="utf-8")
        )
        self.assertEqual(
            frontmatter["sections"],
            ["kotimaa", "ulkomaat", "talous"],
        )

    def test_template_appends_the_matched_article_not_the_recap_page(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{{ $article := . }}", template)
        self.assertIn("$matched = $matched | append $article", template)
        self.assertNotIn("{{ $matched = $matched | append $ }}", template)
        self.assertIn(
            'href="{{ $article.RelPermalink }}" class="kooste-card__image-wrap"',
            template,
        )
        self.assertNotIn(
            'href="{{ $.RelPermalink }}" class="kooste-card__image-wrap"',
            template,
        )

    @unittest.skipUnless(os.environ.get("HUGO_OUTPUT_DIR"), "requires a Hugo build")
    def test_built_august_4_recap_contains_eight_unique_story_links(self) -> None:
        page = (
            Path(os.environ["HUGO_OUTPUT_DIR"])
            / "paivan-kooste"
            / "2026-08-04"
            / "index.html"
        )
        self.assertTrue(page.is_file(), f"missing built recap: {page}")
        parser = KoostePageParser()
        parser.feed(page.read_text(encoding="utf-8"))

        self.assertEqual(
            parser.sections,
            ["kooste-kotimaa", "kooste-ulkomaat", "kooste-talous"],
        )
        self.assertEqual(len(parser.card_links), 8)
        self.assertEqual(len(set(parser.card_links)), 8)
        self.assertTrue(all(link.startswith("/posts/") for link in parser.card_links))
        self.assertEqual(parser.image_links, parser.card_links)
        self.assertNotIn("/paivan-kooste/2026-08-04/", parser.card_links)
        self.assertFalse(parser.empty_message)


if __name__ == "__main__":
    unittest.main()

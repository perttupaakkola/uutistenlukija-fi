#!/usr/bin/env python3
"""Focused Hugo regression for the article-scoped OPE-507 deck seam."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET_NAME = (
    "2026-06-25-raystaspaaskyjen-pesinta-viivastyttaa-"
    "hailuodon-lauttojen-si.md"
)
CONTROL_NAME = "2026-06-29-hailuodon-kiintea-tieyhteys-avautuu-liikenteelle.md"
TARGET_SLUG = TARGET_NAME.removesuffix(".md")
CONTROL_SLUG = CONTROL_NAME.removesuffix(".md")
APPROVED_DESCRIPTION = (
    "Hailuodon lauttojen siirto viivästyy, sillä lautoilla pesivillä "
    "uhanalaisilla räystäspääskyillä on yli sata poikasta."
)


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.position = 0
        self.h1_position: int | None = None
        self.hero_position: int | None = None
        self.deck_nodes: list[dict[str, object]] = []
        self._current_deck: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.position += 1
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        if tag == "h1" and self.h1_position is None:
            self.h1_position = self.position
        if "article-hero" in classes and self.hero_position is None:
            self.hero_position = self.position
        if tag == "p" and attr_map.get("data-ope507-hailuoto-deck") == "true":
            self._current_deck = {
                "position": self.position,
                "classes": classes,
                "text": [],
            }

    def handle_data(self, data: str) -> None:
        if self._current_deck is not None:
            self._current_deck["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._current_deck is not None:
            self._current_deck["text"] = "".join(
                self._current_deck["text"]
            ).strip()
            self.deck_nodes.append(self._current_deck)
            self._current_deck = None


def parse_article(html: str) -> ArticleParser:
    parser = ArticleParser()
    parser.feed(html)
    return parser


class HailuotoDeckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory(prefix="ope507-deck-")
        scratch = Path(cls.tempdir.name)
        content_dir = scratch / "content" / "posts"
        output_dir = scratch / "public"
        content_dir.mkdir(parents=True)
        for name in (TARGET_NAME, CONTROL_NAME):
            shutil.copy2(ROOT / "content" / "posts" / name, content_dir / name)

        hugo = os.environ.get(
            "HUGO_BIN",
            "/home/pertt/.openclaw/workspace-alex/.bin/hugo",
        )
        subprocess.run(
            [
                hugo,
                "--environment",
                "production",
                "--minify",
                "--contentDir",
                str(content_dir.parent),
                "--destination",
                str(output_dir),
                "--baseURL",
                "https://uutistenlukija.fi/",
                "--cleanDestinationDir",
                "--disableKinds",
                "home,section,taxonomy,term,RSS,sitemap,robotsTXT,404",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        cls.target_html = (
            output_dir / "posts" / TARGET_SLUG / "index.html"
        ).read_text(encoding="utf-8")
        cls.control_html = (
            output_dir / "posts" / CONTROL_SLUG / "index.html"
        ).read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_target_renders_exact_deck_once_between_h1_and_hero(self) -> None:
        parsed = parse_article(self.target_html)
        self.assertEqual(len(parsed.deck_nodes), 1)
        deck = parsed.deck_nodes[0]
        self.assertEqual(deck["text"], APPROVED_DESCRIPTION)
        self.assertEqual(
            deck["classes"],
            {"article-ingress", "article-ingress--hailuoto"},
        )
        self.assertIsNotNone(parsed.h1_position)
        self.assertIsNotNone(parsed.hero_position)
        self.assertLess(parsed.h1_position, deck["position"])
        self.assertLess(deck["position"], parsed.hero_position)

    def test_control_article_does_not_receive_the_ope507_seam(self) -> None:
        parsed = parse_article(self.control_html)
        self.assertEqual(parsed.deck_nodes, [])


if __name__ == "__main__":
    unittest.main()

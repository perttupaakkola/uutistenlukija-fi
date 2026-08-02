#!/usr/bin/env python3
"""Regression contract for the mobile homepage discovery story target."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_TEMPLATE = ROOT / "layouts" / "index.html"
CRITICAL_CSS = ROOT / "layouts" / "partials" / "critical-css.html"
PORTAL_CSS = (
    ROOT / "assets" / "css" / "portal-overhaul.css",
    ROOT / "static" / "css" / "portal-overhaul.css",
)


def compact_css(path: Path) -> str:
    return re.sub(r"\s+", "", path.read_text(encoding="utf-8")).replace(";}", "}")


class HomepageStoryCardTapTargetTest(unittest.TestCase):
    def test_opinion_card_headline_keeps_article_link_contract(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        card = template.split('<article class="portal-opinion-card">', 1)[1].split(
            "</article>", 1
        )[0]

        self.assertIn('<h3><a href="{{ $story.RelPermalink }}"', card)
        self.assertIn('data-track="homepage_discovery_click"', card)
        self.assertIn('data-rank="{{ add $rank 1 }}"', card)

    def test_mobile_opinion_card_headline_is_a_44px_target(self) -> None:
        expected = (
            "@media(max-width:900px){"
            ".portal-opinion-cardh3a{display:block;min-height:44px;padding-block:2px}"
            "}"
        )

        self.assertIn(expected, compact_css(CRITICAL_CSS))
        for stylesheet in PORTAL_CSS:
            with self.subTest(stylesheet=stylesheet.relative_to(ROOT)):
                self.assertIn(expected, compact_css(stylesheet))

        self.assertEqual(
            PORTAL_CSS[0].read_bytes(),
            PORTAL_CSS[1].read_bytes(),
            "assets/static portal stylesheet copies must stay identical",
        )


if __name__ == "__main__":
    unittest.main()

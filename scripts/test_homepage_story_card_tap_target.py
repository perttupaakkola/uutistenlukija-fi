#!/usr/bin/env python3
"""Regression contracts for accessible homepage discovery targets."""

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
    def test_talous_link_is_unique_and_follows_the_four_story_grid(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        section = template.split(
            '<section class="portal-editorials portal-discovery"', 1
        )[1].split("</section>", 1)[0]
        link = (
            '<a class="portal-discovery__talous-link" '
            'href="/categories/talous/">Kaikki Talous-uutiset</a>'
        )

        self.assertEqual(template.count(link), 1)
        self.assertGreater(section.index(link), section.rfind("</div>"))
        self.assertIn(
            '$discoveryPool := where $sorted "Permalink" "not in" $seen',
            section,
        )
        self.assertIn("$discoveryStories := first 4 $discoveryPool", section)
        self.assertIn("$discoveryStories = first 3 $discoveryStories", section)
        self.assertIn(
            "$discoveryStories = $discoveryStories | append $newestUnseenTalous",
            section,
        )
        self.assertIn("$seen = $seen | append $story.Permalink", section)

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

    def test_talous_link_is_compact_visible_and_keyboard_accessible(self) -> None:
        expected = (
            ".portal-discovery__talous-link{display:inline-flex;align-items:center;"
            "width:fit-content;min-height:44px;margin-top:8px;"
            "color:var(--portal-blue,#082867);font-family:var(--font-sans);"
            "font-size:13px;font-weight:760;line-height:1.3;"
            "text-decoration:underline;text-underline-offset:3px}"
        )
        dark_mode = (
            ':root[data-theme="dark"].portal-discovery__talous-link{color:#8ab4ff}'
        )

        for stylesheet in (CRITICAL_CSS, *PORTAL_CSS):
            compact = compact_css(stylesheet)
            with self.subTest(stylesheet=stylesheet.relative_to(ROOT)):
                self.assertIn(expected, compact)
                self.assertIn(dark_mode, compact)

        self.assertEqual(
            PORTAL_CSS[0].read_bytes(),
            PORTAL_CSS[1].read_bytes(),
            "assets/static portal stylesheet copies must stay identical",
        )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression contract for mobile homepage ``Nostot`` metadata."""

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


class HomepageNostotMetadataTest(unittest.TestCase):
    def test_source_metadata_preserves_story_link_and_order(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        card = template.split('<article class="portal-opinion-card">', 1)[1].split(
            "</article>", 1
        )[0]

        kicker = '<span class="portal-kicker">{{ $cat }}</span>'
        headline = '<h3><a href="{{ .RelPermalink }}">{{ .Title }}</a></h3>'
        source = (
            '{{ with .Params.source_name }}<span class="portal-opinion-card__source">'
            "{{ . }}</span>{{ end }}"
        )
        timestamp = '<span class="portal-opinion-card__time">'

        self.assertLess(card.index(kicker), card.index(headline))
        self.assertLess(card.index(headline), card.index(source))
        self.assertLess(card.index(source), card.index(timestamp))
        self.assertEqual(card.count("href="), 1)
        self.assertNotIn("data-track", card)

    def test_mobile_metadata_has_scoped_readability_contract(self) -> None:
        expected = (
            ".portal-opinion-card__source{display:none}",
            ".portal-opinion-card.portal-kicker{color:#082867!important;font-size:13px;"
            "line-height:1.25}",
            ".portal-opinion-card__source{display:inline-flex;align-items:center;"
            "min-height:24px;color:#344154;font-size:13px;font-weight:700;line-height:1.35}",
            ".portal-opinion-card__time{display:inline-flex;align-items:center;"
            "min-height:24px;color:#4b5566;font-size:13px;font-weight:650;line-height:1.35}",
            ".portal-opinion-card__source+.portal-opinion-card__time::before{content:\"·\";"
            "margin:0.4rem;color:#94a3b8}",
            '[data-theme="dark"].portal-opinion-card.portal-kicker{color:#b8cdf5!important}',
            '[data-theme="dark"].portal-opinion-card__source{color:#f3f5f7}',
            '[data-theme="dark"].portal-opinion-card__time{color:#cbd5e1}',
        )

        for stylesheet in (CRITICAL_CSS, *PORTAL_CSS):
            compact = compact_css(stylesheet)
            with self.subTest(stylesheet=stylesheet.relative_to(ROOT)):
                for rule in expected:
                    self.assertIn(rule, compact)

        self.assertEqual(
            PORTAL_CSS[0].read_bytes(),
            PORTAL_CSS[1].read_bytes(),
            "assets/static portal stylesheet copies must stay identical",
        )


if __name__ == "__main__":
    unittest.main()

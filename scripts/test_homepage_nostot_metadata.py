#!/usr/bin/env python3
"""Regression contract for homepage ``Löydä lisää`` discovery metadata."""

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


class HomepageDiscoveryMetadataTest(unittest.TestCase):
    def test_discovery_uses_fresh_unseen_published_story_contract(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        card = template.split('<article class="portal-opinion-card">', 1)[1].split(
            "</article>", 1
        )[0]

        kicker = '<span class="portal-kicker">{{ $cat }}</span>'
        headline = '<h3><a href="{{ $story.RelPermalink }}"'
        source = (
            '{{ with $story.Params.source_name }}<span class="portal-opinion-card__source">'
            "{{ . }}</span>{{ end }}"
        )
        timestamp = '<span class="portal-opinion-card__time">'

        self.assertIn('<h2 id="editorials-title">Löydä lisää</h2>', template)
        self.assertIn(
            '{{ $discoveryPool := where $sorted "Permalink" "not in" $seen }}',
            template,
        )
        self.assertIn('{{ range $rank, $story := first 4 $discoveryPool }}', template)
        self.assertIn('{{ $seen = $seen | append $story.Permalink }}', template)
        self.assertLess(card.index(kicker), card.index(headline))
        self.assertLess(card.index(headline), card.index(source))
        self.assertLess(card.index(source), card.index(timestamp))
        self.assertEqual(card.count("href="), 1)
        self.assertNotIn("<img", card)
        self.assertIn('data-track="homepage_discovery_click"', card)
        self.assertIn('data-placement="homepage_find_more"', card)
        self.assertIn('data-rank="{{ add $rank 1 }}"', card)
        self.assertIn('data-category="{{ $cat }}"', card)

    def test_discovery_reuses_compact_editorial_card_layout(self) -> None:
        expected = (
            ".portal-discovery.portal-editorials__grid{"
            "grid-template-columns:repeat(4,minmax(0,1fr))}",
            ".portal-discovery.portal-opinion-card{"
            "grid-template-columns:minmax(0,1fr);gap:0}",
            "@media(max-width:900px){.portal-discovery.portal-editorials__grid{"
            "grid-template-columns:minmax(0,1fr)}}",
        )
        for stylesheet in PORTAL_CSS:
            compact = compact_css(stylesheet)
            with self.subTest(stylesheet=stylesheet.relative_to(ROOT)):
                for rule in expected:
                    self.assertIn(rule, compact)

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

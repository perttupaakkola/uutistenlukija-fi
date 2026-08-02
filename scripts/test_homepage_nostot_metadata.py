#!/usr/bin/env python3
"""Regression contract for homepage ``Löydä lisää`` discovery metadata."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
import html
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_TEMPLATE = ROOT / "layouts" / "index.html"
CRITICAL_CSS = ROOT / "layouts" / "partials" / "critical-css.html"
PORTAL_CSS = (
    ROOT / "assets" / "css" / "portal-overhaul.css",
    ROOT / "static" / "css" / "portal-overhaul.css",
)
HUGO_BIN = shutil.which("hugo") or "/workspace/hugo"


def compact_css(path: Path) -> str:
    return re.sub(r"\s+", "", path.read_text(encoding="utf-8")).replace(";}", "}")


class HomepageDiscoveryMetadataTest(unittest.TestCase):
    def _render_discovery_fixture(self, *, include_unseen_talous: bool) -> dict:
        with tempfile.TemporaryDirectory(prefix="homepage-discovery-") as tmp:
            root = Path(tmp)
            content_dir = root / "content"
            posts_dir = content_dir / "posts"
            public_dir = root / "public"
            posts_dir.mkdir(parents=True)

            newest = datetime(2020, 1, 31, 12, tzinfo=timezone.utc)
            fixed_categories = {
                3: "Talous",
                4: "Kotimaa",
                5: "Ulkomaat",
                6: "Tiede",
            }
            for rank in range(1, 17):
                category = fixed_categories.get(rank, "Kulttuuri")
                if include_unseen_talous and rank == 14:
                    category = "Talous"
                published = newest - timedelta(hours=rank)
                (posts_dir / f"fixture-story-{rank:02d}.md").write_text(
                    "---\n"
                    f'title: "Fixture story {rank:02d}"\n'
                    f"date: {published.isoformat()}\n"
                    f'categories: ["{category}"]\n'
                    'source_name: "Fixture source"\n'
                    "draft: false\n"
                    "---\n\n"
                    f"Fixture summary {rank:02d}.\n",
                    encoding="utf-8",
                )

            command = (
                HUGO_BIN,
                "--source",
                str(ROOT),
                "--contentDir",
                str(content_dir),
                "--destination",
                str(public_dir),
                "--cleanDestinationDir",
                "--quiet",
            )
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"Hugo fixture render failed:\n{completed.stdout}\n{completed.stderr}",
            )
            rendered = (public_dir / "index.html").read_text(encoding="utf-8")

        section_match = re.search(
            r'<section class="portal-editorials portal-discovery".*?'
            r'(?=<section class="portal-river")',
            rendered,
            re.DOTALL,
        )
        self.assertIsNotNone(section_match, "rendered discovery section missing")
        section = section_match.group(0)
        cards = [
            {
                "href": href,
                "category": category,
                "title": html.unescape(re.sub(r"<[^>]+>", "", title)).strip(),
            }
            for href, category, title in re.findall(
                r'<h3><a href="([^"]+)"[^>]*data-track="homepage_discovery_click"'
                r'[^>]*data-category="([^"]+)">(.*?)</a></h3>',
                section,
                re.DOTALL,
            )
        ]
        preceding_hrefs = set(
            re.findall(r'href="([^"]+)"', rendered[: section_match.start()])
        )
        return {"cards": cards, "preceding_hrefs": preceding_hrefs}

    def test_discovery_includes_newest_unseen_talous_candidate(self) -> None:
        rendered = self._render_discovery_fixture(include_unseen_talous=True)

        self.assertEqual(len(rendered["cards"]), 4)
        self.assertEqual(
            [card["title"] for card in rendered["cards"]],
            [
                "Fixture story 10",
                "Fixture story 11",
                "Fixture story 12",
                "Fixture story 14",
            ],
        )
        self.assertEqual(
            [card["category"] for card in rendered["cards"]].count("Talous"),
            1,
        )
        self.assertTrue(
            all(
                card["href"] not in rendered["preceding_hrefs"]
                for card in rendered["cards"]
            )
        )

    def test_discovery_falls_back_to_newest_four_without_unseen_talous(self) -> None:
        rendered = self._render_discovery_fixture(include_unseen_talous=False)

        self.assertEqual(len(rendered["cards"]), 4)
        self.assertEqual(
            [card["title"] for card in rendered["cards"]],
            [
                "Fixture story 10",
                "Fixture story 11",
                "Fixture story 12",
                "Fixture story 13",
            ],
        )
        self.assertEqual(
            [card["category"] for card in rendered["cards"]].count("Talous"),
            0,
        )
        self.assertTrue(
            all(
                card["href"] not in rendered["preceding_hrefs"]
                for card in rendered["cards"]
            )
        )

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
        self.assertIn('{{ $discoveryStories := first 4 $discoveryPool }}', template)
        self.assertIn(
            '{{ $talousCandidates := where $discoveryPool ".Params.categories" '
            '"intersect" (slice "Talous") }}',
            template,
        )
        self.assertIn(
            '{{ $selectedTalous := where $discoveryStories ".Params.categories" '
            '"intersect" (slice "Talous") }}',
            template,
        )
        self.assertIn('{{ $discoveryStories = first 3 $discoveryStories }}', template)
        self.assertIn(
            '{{ $discoveryStories = $discoveryStories | append $newestUnseenTalous }}',
            template,
        )
        self.assertIn('{{ range $rank, $story := $discoveryStories }}', template)
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

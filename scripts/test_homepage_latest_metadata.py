#!/usr/bin/env python3
"""Regression contract for mobile homepage latest-list metadata."""

from pathlib import Path
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


class HomepageLatestMetadataTest(unittest.TestCase):
    def test_lead_uses_newest_eligible_story_before_older_visual_story(self) -> None:
        fixtures = (
            ("Newest fallback lead", "2020-01-31T12:00:00+00:00", "Talous", True),
            ("Live fallback story", "2020-01-30T12:00:00+00:00", "Kotimaa", True),
            ("Older visual story", "2020-01-29T12:00:00+00:00", "Ulkomaat", False),
            ("Tiede fallback story", "2020-01-28T12:00:00+00:00", "Tiede", True),
        )
        with tempfile.TemporaryDirectory(prefix="homepage-lead-") as tmp:
            root = Path(tmp)
            posts_dir = root / "content" / "posts"
            public_dir = root / "public"
            posts_dir.mkdir(parents=True)
            for rank, (title, published, category, fallback) in enumerate(fixtures, 1):
                image = (
                    f"/images/categories/{category.lower()}.jpg"
                    if fallback
                    else "/images/articles/older-visual-story.jpg"
                )
                image_source = "category_fallback" if fallback else "generated"
                (posts_dir / f"fixture-{rank}.md").write_text(
                    "---\n"
                    f'title: "{title}"\n'
                    f"date: {published}\n"
                    f'categories: ["{category}"]\n'
                    f'image: "{image}"\n'
                    f'image_source: "{image_source}"\n'
                    f"image_category_fallback: {str(fallback).lower()}\n"
                    'source_name: "Fixture source"\n'
                    "draft: false\n"
                    "---\n\n"
                    f"{title} fixture content.\n",
                    encoding="utf-8",
                )

            completed = subprocess.run(
                (
                    HUGO_BIN,
                    "--source",
                    str(ROOT),
                    "--contentDir",
                    str(root / "content"),
                    "--destination",
                    str(public_dir),
                    "--cleanDestinationDir",
                    "--quiet",
                ),
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

        lead = re.search(
            r'<article class="portal-lead">(.*?)</article>', rendered, re.DOTALL
        )
        self.assertIsNotNone(lead, "rendered homepage lead missing")
        self.assertIn("Newest fallback lead", lead.group(1))
        self.assertNotIn("Older visual story", lead.group(1))

        teasers = re.search(
            r'<div class="portal-center-list".*?</div>\s*</div>',
            rendered,
            re.DOTALL,
        )
        self.assertIsNotNone(teasers, "rendered homepage teaser list missing")
        self.assertIn("Older visual story", teasers.group(0))

    def test_source_metadata_preserves_story_links_and_order(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        card = template.split('<article class="portal-row-card{{', 1)[1].split(
            "</article>", 1
        )[0]

        kicker = '<span class="portal-kicker">{{ $cat }}</span>'
        headline = '<h3><a href="{{ .RelPermalink }}">{{ .Title }}</a></h3>'
        summary = '<p>{{ .Summary | truncate 120 }}</p>'
        source = (
            '{{ with .Params.source_name }}<span class="portal-row-card__source">'
            "{{ . }}</span>{{ end }}"
        )
        timestamp = '<span class="portal-row-card__time">'

        self.assertLess(card.index(kicker), card.index(headline))
        self.assertLess(card.index(headline), card.index(summary))
        self.assertLess(card.index(summary), card.index(source))
        self.assertLess(card.index(source), card.index(timestamp))
        self.assertEqual(card.count('href="{{ .RelPermalink }}"'), 2)
        self.assertNotIn("data-track", card)

    def test_category_fallback_and_runtime_failure_are_image_free(self) -> None:
        template = INDEX_TEMPLATE.read_text(encoding="utf-8")
        card = template.split('<article class="portal-row-card{{', 1)[1].split(
            "</article>", 1
        )[0]

        self.assertIn(
            '(strings.Contains $img "/images/categories/")',
            template,
        )
        self.assertIn("portal-row-card--no-image", card)
        self.assertIn("{{ if not $isCategoryFallback }}", card)
        self.assertIn("card.classList.add('portal-row-card--no-image')", card)
        self.assertIn("thumb.hidden=true", card)
        self.assertNotIn("this.src=", card)

        expected_rules = (
            ".portal-row-card.portal-row-card--no-image{"
            "grid-template-columns:minmax(0,1fr)}",
            ".portal-row-card--no-image>div{grid-column:1/-1;min-width:0}",
            ".portal-row-card--no-image.portal-row-card__thumb{display:none}",
        )
        for stylesheet in PORTAL_CSS:
            compact = compact_css(stylesheet)
            with self.subTest(stylesheet=stylesheet.relative_to(ROOT)):
                for rule in expected_rules:
                    self.assertIn(rule, compact)

    def test_mobile_metadata_has_scoped_readability_contract(self) -> None:
        expected = (
            ".portal-row-card__source{display:none}",
            ".portal-row-card__source{display:inline-flex;align-items:center;"
            "min-height:24px;color:#344154;font-size:13px;font-weight:700;line-height:1.35}",
            ".portal-row-card__time{display:inline-flex;align-items:center;"
            "min-height:24px;color:#4b5566;font-size:13px;font-weight:650;line-height:1.35}",
            ".portal-row-card__source+.portal-row-card__time::before{content:\"·\";"
            "margin:0.4rem;color:#94a3b8}",
            '[data-theme="dark"].portal-row-card__source{color:#f3f5f7}',
            '[data-theme="dark"].portal-row-card__time{color:#cbd5e1!important}',
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

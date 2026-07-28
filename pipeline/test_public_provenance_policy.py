#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
PROJECT_DIR = PIPELINE_DIR.parent

_spec = importlib.util.spec_from_file_location("daily_briefing", PIPELINE_DIR / "daily_briefing.py")
if _spec is None or _spec.loader is None:
    raise RuntimeError("Could not load daily_briefing.py")
daily_briefing = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = daily_briefing
_spec.loader.exec_module(daily_briefing)

BANNED_STRINGS = (
    "Lähde:",
    "Alkuperäinen artikkeli",
    "Lisätietoja alkuperäisestä jutusta",
    "story__source",
    "article-end-note--source",
)

ACTIVE_TEMPLATE_PATHS = (
    PROJECT_DIR / "layouts" / "_default" / "single.html",
    PROJECT_DIR / "layouts" / "_default" / "page.html",
    PROJECT_DIR / "layouts" / "partials" / "article-body.html",
    PROJECT_DIR / "layouts" / "analysis" / "single.html",
)

LEGACY_TEMPLATE_PATH = PROJECT_DIR / "layouts" / "partials" / "source-article-link.html"
SHARED_TEMPLATE_PATH = PROJECT_DIR / "layouts" / "partials" / "article-source-attribution.html"


class PublicProvenancePolicyTests(unittest.TestCase):
    def assert_clean(self, text: str, *, context: str) -> None:
        for banned in BANNED_STRINGS:
            self.assertNotIn(banned, text, f"{context} leaked banned string: {banned}")

    def test_active_templates_are_clean(self) -> None:
        for path in ACTIVE_TEMPLATE_PATHS:
            self.assertTrue(path.exists(), f"Missing template: {path}")
            self.assert_clean(path.read_text(encoding="utf-8"), context=str(path))

    def test_article_source_partial_requires_a_name_and_url(self) -> None:
        adapter = LEGACY_TEMPLATE_PATH.read_text(encoding="utf-8")
        shared = SHARED_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertEqual(adapter.strip(), '{{ partial "article-source-attribution.html" . }}')
        self.assertIn("if and $sourceName $sourceUrl", shared)
        self.assertIn('href="{{ $sourceUrl }}"', shared)
        self.assertIn("{{ $sourceName }}", shared)
        self.assertIn("$page.Params.source_attributions", shared)
        self.assertIn('href="{{ .url }}"', shared)
        self.assertIn("{{ .name }}", shared)

    def test_daily_briefing_render_hides_internal_sources(self) -> None:
        article = daily_briefing.Article(
            title="Testiotsikko",
            published_at=datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
            description="Tiivis kuvaus päivän tärkeästä jutusta.",
            source_name="Internal Source Only",
            source_domain="internal.example",
            category="Kotimaa",
            url="https://uutistenlukija.fi/posts/testi/",
            body=(
                "Tämä on riittävän pitkä runkoteksti, jotta esikatselu rakentuu normaalisti. "
                "Sisäinen lähdetieto ei saa näkyä julkisessa HTML- tai tekstiesikatselussa."
            ),
            path=PROJECT_DIR / "content" / "posts" / "testi.md",
        )

        html_preview = daily_briefing.render_html_preview(
            date(2026, 4, 22),
            [article],
            datetime(2026, 4, 22, 9, 0, tzinfo=timezone.utc),
        )
        plaintext_preview = daily_briefing.build_plaintext_preview(date(2026, 4, 22), [article])

        self.assert_clean(html_preview, context="daily_briefing html")
        self.assert_clean(plaintext_preview, context="daily_briefing plaintext")
        self.assertNotIn("Internal Source Only", html_preview)
        self.assertNotIn("Internal Source Only", plaintext_preview)
        self.assertNotIn("internal.example", html_preview)
        self.assertNotIn("internal.example", plaintext_preview)

    def test_tracked_newsletter_archives_are_clean(self) -> None:
        newsletter_dir = PROJECT_DIR / "static" / "newsletter"
        html_files = sorted(newsletter_dir.glob("daily-*.html"))
        self.assertTrue(html_files, "No daily newsletter archives found")
        for path in html_files:
            self.assert_clean(path.read_text(encoding="utf-8"), context=str(path))


if __name__ == "__main__":
    unittest.main()

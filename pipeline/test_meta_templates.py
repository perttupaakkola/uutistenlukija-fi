#!/usr/bin/env python3
"""Regression tests for SEO metadata template rendering."""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.test_templates import render_frontmatter

ROOT = Path(__file__).resolve().parents[1]
HUGO = Path("/workspace/hugo")
CONTENT_TEST_DIR = ROOT / "content" / "test"


class MetaTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(HUGO.exists(), f"Hugo binary missing: {HUGO}")
        self.output_root = Path(tempfile.mkdtemp(prefix="meta-template-test-"))
        CONTENT_TEST_DIR.mkdir(parents=True, exist_ok=True)
        self.article_path = CONTENT_TEST_DIR / "seo-boundary.md"

    def tearDown(self) -> None:
        try:
            self.article_path.unlink()
        except FileNotFoundError:
            pass
        try:
            if CONTENT_TEST_DIR.exists() and not any(CONTENT_TEST_DIR.iterdir()):
                CONTENT_TEST_DIR.rmdir()
        except OSError:
            pass
        shutil.rmtree(self.output_root, ignore_errors=True)

    def render_article(self, frontmatter: dict, body: str = "Leipäteksti.") -> str:
        self.article_path.write_text(
            f"{render_frontmatter(frontmatter)}\n\n{body}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(HUGO), "--minify", "-D", "--destination", str(self.output_root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.output_root / "test" / "seo-boundary" / "index.html").read_text(encoding="utf-8")

    def meta_content(self, html_text: str, selector: str) -> str:
        patterns = {
            "title": r"<title>(.*?)</title>",
            "description": r'<meta name=description content="(.*?)"',
            "og_description": r'<meta property="og:description" content="(.*?)"',
        }
        match = re.search(patterns[selector], html_text)
        self.assertIsNotNone(match, f"Missing metadata field: {selector}")
        return html.unescape(match.group(1))

    def test_article_meta_title_and_description_do_not_end_with_ellipsis(self) -> None:
        page = self.render_article(
            {
                "draft": True,
                "title": "Trumpin kerrotaan hyväksyneen suunnitelman FDA-johtajan erottamisesta kesken kiistan",
                "date": "2026-05-09T00:00:00Z",
                "categories": ["Ulkomaat"],
                "description": (
                    "Trumpin kerrotaan hyväksyneen suunnitelman FDA-johtajan erottamisesta sen jälkeen, "
                    "kun hallinnon sisäinen kiista paisui julkisuuteen ja viranomaiset valmistautuivat "
                    "seuraaviin päätöksiin terveyspolitiikassa."
                ),
            }
        )

        title = self.meta_content(page, "title")
        description = self.meta_content(page, "description")
        og_description = self.meta_content(page, "og_description")

        self.assertNotIn("…", title)
        self.assertLessEqual(len(title), 60)
        self.assertEqual(title, "Trumpin kerrotaan hyväksyneen suunnitelman | Uutistenlukija")
        self.assertNotIn("…", description)
        self.assertLessEqual(len(description), 155)
        self.assertEqual(description, og_description)
        self.assertFalse(description.endswith((" ", ",", ".", ";", ":", "-", "–")))


if __name__ == "__main__":
    unittest.main()

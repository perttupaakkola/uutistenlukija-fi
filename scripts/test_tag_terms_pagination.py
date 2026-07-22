#!/usr/bin/env python3
"""Regression tests for bounded, globally sorted tag-term pagination."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "layouts" / "taxonomy" / "tag.terms.html"
META_TITLE = ROOT / "layouts" / "partials" / "meta-title.html"
HUGO = Path("/workspace/hugo")


class TagTermsPaginationTests(unittest.TestCase):
    def test_tag_terms_grid_uses_title_sorted_paginator(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")
        meta_title = META_TITLE.read_text(encoding="utf-8")

        self.assertIn("{{ $paginator := .Paginate (.Pages.ByTitle) }}", template)
        self.assertIn("$paginator = .Paginate (.Pages.ByTitle)", meta_title)
        self.assertIn("{{ range $paginator.Pages }}", template)
        self.assertIn(
            '{{ partial "pagination.html" (dict "Paginator" $paginator) }}',
            template,
        )
        self.assertNotIn("{{ range .Pages }}", template)
        self.assertNotIn("{{ range $tags }}", template)

    @unittest.skipUnless(HUGO.is_file(), "workspace Hugo binary is unavailable")
    def test_rendered_pages_are_globally_sorted_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="tag-terms-render-") as temp_dir:
            site = Path(temp_dir)
            (site / "content" / "posts").mkdir(parents=True)
            (site / "layouts" / "_default").mkdir(parents=True)
            (site / "layouts" / "taxonomy").mkdir(parents=True)
            (site / "layouts" / "partials").mkdir(parents=True)

            (site / "hugo.toml").write_text(
                """baseURL = 'https://example.test/'
title = 'Fixture'
disableKinds = ['home', 'RSS', 'sitemap', 'robotsTXT', '404']

[pagination]
pagerSize = 30

[taxonomies]
tag = 'tags'
""",
                encoding="utf-8",
            )
            (site / "layouts" / "_default" / "baseof.html").write_text(
                """<!doctype html><html><head>
{{ partial "meta-title.html" . }}
</head><body>{{ block "main" . }}{{ end }}</body></html>
""",
                encoding="utf-8",
            )
            shutil.copy2(TEMPLATE, site / "layouts" / "taxonomy" / "tag.terms.html")
            for name in ("meta-title.html", "page-title-core.html", "pagination.html"):
                shutil.copy2(
                    ROOT / "layouts" / "partials" / name,
                    site / "layouts" / "partials" / name,
                )

            expected = [f"Tag {index:03d}" for index in range(65)]
            scrambled = expected[::2][::-1] + expected[1::2]
            for index, tag in enumerate(scrambled):
                (site / "content" / "posts" / f"post-{index:03d}.md").write_text(
                    "\n".join(
                        [
                            "+++",
                            f'title = "Post {index:03d}"',
                            f'tags = ["{tag}"]',
                            "+++",
                            "Fixture body.",
                        ]
                    ),
                    encoding="utf-8",
                )

            result = subprocess.run(
                [
                    str(HUGO),
                    "--source",
                    str(site),
                    "--destination",
                    str(site / "public"),
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            page_paths = [
                site / "public" / "tags" / "index.html",
                site / "public" / "tags" / "page" / "2" / "index.html",
                site / "public" / "tags" / "page" / "3" / "index.html",
            ]
            rendered_pages: list[list[str]] = []
            for path in page_paths:
                self.assertTrue(path.is_file(), f"missing rendered page: {path}")
                html = path.read_text(encoding="utf-8")
                rendered_pages.append(
                    re.findall(
                        r'<span class="tag-term-name">#\s*([^<]+?)\s*</span>',
                        html,
                    )
                )
                self.assertIn('class="pagination"', html)

            self.assertEqual([len(page) for page in rendered_pages], [30, 30, 5])
            self.assertEqual([tag for page in rendered_pages for tag in page], expected)
            self.assertFalse(
                (site / "public" / "tags" / "page" / "4" / "index.html").exists()
            )
            page_two = page_paths[1].read_text(encoding="utf-8")
            self.assertIn("sivu 2", page_two)


if __name__ == "__main__":
    unittest.main()

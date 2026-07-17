#!/usr/bin/env python3
"""Regression contract for the article category return link."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ".single-article>.category-label--badge"


class ArticleCategoryNavigationTest(unittest.TestCase):
    def test_category_link_stays_above_the_article_headline(self) -> None:
        page = (ROOT / "layouts/_default/page.html").read_text(encoding="utf-8")
        partial = (ROOT / "layouts/partials/category-badge.html").read_text(encoding="utf-8")

        badge = '{{ partial "category-badge.html" (dict "category" $primaryCategory "link" true) }}'
        article = page.index('<article class="single-article">')
        self.assertLess(page.index(badge, article), page.index("<h1>{{ .Title }}</h1>", article))
        self.assertIn('href="/categories/{{ $slug }}/"', partial)

    def test_article_category_link_is_a_scoped_mobile_return_target(self) -> None:
        critical = (ROOT / "layouts/partials/critical-css.html").read_text(encoding="utf-8")
        style = (ROOT / "themes/uutistenlukija/static/css/style.css").read_text(encoding="utf-8")

        for css in (critical, style):
            with self.subTest(stylesheet=css[:24]):
                compact = css.replace(" ", "")
                self.assertIn(SELECTOR, compact)
                rule = compact[compact.index(SELECTOR) : compact.index(SELECTOR) + 240]
                self.assertIn("min-height:44px", rule)
                self.assertIn(SELECTOR + "::before", compact)
                cue = compact[
                    compact.index(SELECTOR + "::before") : compact.index(SELECTOR + "::before") + 120
                ]
                self.assertIn('content:"←"', cue)


if __name__ == "__main__":
    unittest.main()

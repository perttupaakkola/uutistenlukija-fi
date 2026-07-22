#!/usr/bin/env python3
"""Regression test for bounded rendering of the tag-terms index."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "layouts" / "taxonomy" / "tag.terms.html"


class TagTermsPaginationTests(unittest.TestCase):
    def test_tag_terms_grid_uses_existing_paginator_page(self) -> None:
        template = TEMPLATE.read_text(encoding="utf-8")

        self.assertIn("{{ $paginator := .Paginator }}", template)
        self.assertIn("{{ range $paginator.Pages }}", template)
        self.assertIn(
            '{{ partial "pagination.html" (dict "Paginator" $paginator) }}',
            template,
        )
        self.assertNotIn("{{ range .Pages }}", template)
        self.assertNotIn("{{ range $tags }}", template)


if __name__ == "__main__":
    unittest.main()

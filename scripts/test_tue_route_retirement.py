#!/usr/bin/env python3
"""Regression checks for the retired public support route."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.validate_public_surface import FORBIDDEN_PUBLIC_PATHS


ROOT = Path(__file__).resolve().parents[1]
FOOTERS = (
    ROOT / "layouts/partials/footer.html",
    ROOT / "themes/uutistenlukija/layouts/partials/footer.html",
)


class TueRouteRetirementTest(unittest.TestCase):
    def test_support_section_source_is_retired(self) -> None:
        self.assertFalse((ROOT / "content/tue/_index.md").exists())

    def test_public_surface_validator_blocks_retired_outputs(self) -> None:
        self.assertIn(Path("tue/index.html"), FORBIDDEN_PUBLIC_PATHS)
        self.assertIn(Path("tue/index.xml"), FORBIDDEN_PUBLIC_PATHS)

    def test_worker_bypasses_stale_asset_cache_for_retired_route(self) -> None:
        worker = (ROOT / "static/_worker.js").read_text(encoding="utf-8")
        self.assertIn("pathname === '/tue'", worker)
        self.assertIn("pathname === '/tue/'", worker)
        self.assertIn("pathname.startsWith('/tue/')", worker)

    def test_footers_do_not_link_to_retired_route(self) -> None:
        for footer in FOOTERS:
            with self.subTest(footer=footer.relative_to(ROOT)):
                markup = footer.read_text(encoding="utf-8")
                self.assertNotIn('href="/tue/"', markup)

    def test_public_sources_have_no_placeholder_or_payment_link(self) -> None:
        public_roots = (
            ROOT / "content",
            ROOT / "layouts",
            ROOT / "themes/uutistenlukija/layouts",
            ROOT / "static",
        )
        for public_root in public_roots:
            for path in public_root.rglob("*"):
                if not path.is_file() or path.suffix not in {
                    ".html",
                    ".js",
                    ".json",
                    ".md",
                    ".txt",
                    ".xml",
                }:
                    continue
                with self.subTest(path=path.relative_to(ROOT)):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    self.assertNotIn("PLACEHOLDER", text)
                    self.assertNotIn("buymeacoffee.com", text)


if __name__ == "__main__":
    unittest.main()

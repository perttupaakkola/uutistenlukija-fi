#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from . import backfill_images
except ImportError:  # pragma: no cover
    import backfill_images


class BackfillImagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.content = Path(self.tmp.name)
        self.patch = patch.object(backfill_images, "CONTENT_DIR", self.content)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _post(self, name: str, date: str, image: str = "") -> Path:
        image_line = f'image: "{image}"\n' if image else ""
        path = self.content / name
        path.write_text(
            "---\n"
            f'title: "{name}"\n'
            f"date: {date}\n"
            f"{image_line}"
            "categories: [Kotimaa]\n"
            "---\n\nBody\n",
            encoding="utf-8",
        )
        return path

    def test_find_missing_image_articles_prioritizes_newest_and_skips_existing_images(self) -> None:
        old = self._post("old.md", "2026-05-01T00:00:00Z")
        newest = self._post("newest.md", "2026-05-09T12:00:00Z")
        self._post("has-image.md", "2026-05-10T00:00:00Z", image="/images/articles/existing.jpg")
        middle = self._post("middle.md", "2026-05-08T00:00:00Z")

        missing = backfill_images.find_missing_image_articles(limit=2)

        self.assertEqual(missing, [newest, middle])
        self.assertNotIn(old, missing)

    def test_category_fallback_source_returns_explicit_image_fields(self) -> None:
        result = backfill_images.fetch_image("Title", "Talous", "slug", "category")

        self.assertEqual(result["source"], "category_fallback")
        self.assertEqual(result["url"], "/images/categories/talous.jpg")
        self.assertEqual(result["thumb_url"], "/images/categories/talous.jpg")
        self.assertEqual(result["alt"], "Talous-uutiset")

    def test_inject_image_fields_does_not_leave_old_image_keys(self) -> None:
        text = "---\ntitle: Test\nimage_alt: old\ncategories: [Kotimaa]\n---\n\nBody\n"
        updated = backfill_images._inject_image_fields(text, {
            "url": "https://example.com/img.jpg",
            "alt": "Alt",
            "credit": "Credit",
            "image_source_url": "https://example.com/source",
            "thumb_url": "https://example.com/thumb.jpg",
        })

        self.assertIn('image: "https://example.com/img.jpg"', updated)
        self.assertIn('image_alt: "Alt"', updated)
        self.assertNotIn('image_alt: old', updated)


if __name__ == "__main__":
    unittest.main()

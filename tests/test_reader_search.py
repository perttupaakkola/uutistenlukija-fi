"""Offline contract tests for the bounded first-party reader search."""
import json
import tempfile
import unittest
from pathlib import Path

from news_mvp import site


class ReaderSearch(unittest.TestCase):
    @staticmethod
    def item(title="Päiväkotien syysloma", summary="Ohjelma julkaistiin.",
             path="/uutiset/paivakotien-syysloma-0123456789ab/",
             created_at="2026-10-07T08:15:30+00:00"):
        # Extra job/draft values are deliberately private-looking: the projection
        # must never serialize them or any tuple fields after the canonical link.
        job = {"created_at": created_at, "packet": "PRIVATE_PACKET", "debug": "/srv/private"}
        draft = {"title": title, "summary": summary,
                 "paragraphs": [{"text": "PRIVATE_FULL_TEXT"}], "source_rights": "PRIVATE_RIGHTS"}
        return (job, draft, path, "visible date", "fixture", {"local_path": "/private/image"}, "/image.jpg")

    def test_index_is_exact_listing_projection_with_original_dates(self):
        eligible = [self.item()]
        # Represents a withdrawn/duplicate record that the established listing
        # boundary did not admit. The search writer receives only listing_items.
        excluded = self.item(title="WITHDRAWN_DUPLICATE_SECRET",
                             path="/uutiset/excluded-abcdef012345/",
                             created_at="2026-10-07T09:00:00+00:00")
        document = site.search_index_json(eligible)
        rows = json.loads(document)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"title", "summary", "path", "published"})
        self.assertEqual(rows[0]["published"], "2026-10-07T08:15:30Z")
        self.assertEqual(rows[0]["path"], eligible[0][2])
        self.assertNotIn(excluded[1]["title"], document)
        for private_value in ("PRIVATE_PACKET", "PRIVATE_FULL_TEXT", "PRIVATE_RIGHTS",
                              "/srv/private", "/private/image", "dateModified"):
            self.assertNotIn(private_value, document)

    def test_surface_is_noindex_and_keeps_literal_google_fallbacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site.render_search_surface(root, [self.item()])
            html = (root / "haku/index.html").read_text(encoding="utf-8")
            rows = json.loads((root / "assets/search-index.json").read_text(encoding="utf-8"))
        self.assertIn('<meta name="robots" content="noindex,nofollow">', html)
        self.assertNotIn('rel="canonical"', html)
        self.assertEqual(html.count('action="https://www.google.com/search"'), 2)
        self.assertEqual(html.count('name="sitesearch" value="uutistenlukija.fi"'), 2)
        self.assertIn('data-first-party-action="/haku/"', html)
        self.assertIn("Ilman JavaScriptiä lomake avaa sivustoon rajatun Google-haun.", html)
        self.assertEqual(rows[0]["title"], "Päiväkotien syysloma")

    def test_dedicated_missing_page_search_remains_google_only(self):
        form = site.search_form_html()
        self.assertIn('action="https://www.google.com/search"', form)
        self.assertIn('name="sitesearch" value="uutistenlukija.fi"', form)
        self.assertIn("Hae uutisia Googlesta", form)
        self.assertNotIn("data-first-party-action", form)


if __name__ == "__main__":
    unittest.main()

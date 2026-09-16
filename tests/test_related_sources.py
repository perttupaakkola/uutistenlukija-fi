"""Contracts for related-coverage search (the synthesis input).

The pipeline historically shipped one source per article, hardcoded as "A", so the writer
could only restate a single publisher. These tests pin the properties that make multi-source
packets safe: every related source is a real fetched page, indexes and same-publisher copies
are never counted as corroboration, freshness is the page's own date, and any failure falls
back to the single-source behaviour rather than inventing coverage.
"""

import unittest

from news_mvp import related
from news_mvp.related import (
    build_query, find_related, is_hub_page, strip_navigation, extract_published,
)


class QueryBuilding(unittest.TestCase):
    def test_drops_stopwords_and_keeps_content_words(self):
        query = build_query("Ministeri Tavio vierailee Virossa")
        self.assertIn("Tavio", query)
        self.assertIn("Virossa", query)
        self.assertNotIn("ja", query.split())

    def test_empty_or_junk_title_yields_no_query(self):
        self.assertEqual(build_query(""), "")
        self.assertEqual(build_query(None), "")
        self.assertEqual(build_query("ja on ei"), "")


class HubPageDetection(unittest.TestCase):
    def test_section_indexes_are_not_corroboration(self):
        for url in (
            "https://um.fi/tiedotteet",
            "https://valtioneuvosto.fi/ajankohtaista/uutiset",
            "https://example.fi/uutiset/",
            "https://example.fi/",
        ):
            self.assertTrue(is_hub_page(url), url)

    def test_real_article_urls_pass(self):
        for url in (
            "https://yle.fi/a/74-20245993",
            "https://um.fi/ajankohtaista/-/asset_publisher/gc654PySnjTX/content/ministeri-tavio-vierailee-virossa",
            "https://www.merinova.fi/uutiset/pk-yritysbarometri-yritysten-nakymat-vahvistuvat",
        ):
            self.assertFalse(is_hub_page(url), url)


class NavigationStripping(unittest.TestCase):
    def test_removes_a_ministry_menu_run(self):
        menu = ("Valtioneuvosto Valtioneuvoston kanslia Puolustusministeriö Ulkoministeriö "
                "Valtiovarainministeriö Työ- ja elinkeinoministeriö Oikeusministeriö "
                "Sisäministeriö Ympäristöministeriö Ministeri Tavio vierailee Virossa.")
        out = strip_navigation(menu)
        self.assertNotIn("Puolustusministeriö", out)
        self.assertIn("Tavio", out)

    def test_leaves_normal_prose_untouched(self):
        prose = ("Helsingin kaupunki kertoo, että uusi kirjasto avataan syyskuussa. "
                 "Kaupungin mukaan rakennustyöt ovat edenneet aikataulussa.")
        self.assertEqual(strip_navigation(prose), prose)

    def test_normalises_soft_hyphens(self):
        self.assertNotIn("\u00ad", strip_navigation("viestintä\u00administeriö kertoi asiasta."))


class PublicationDate(unittest.TestCase):
    def test_reads_article_published_time_with_timezone(self):
        raw = b'<html><head><meta property="article:published_time" content="2026-09-16T10:58+03:00"></head></html>'
        self.assertEqual(extract_published(raw), "2026-09-16T10:58:00+03:00")

    def test_rejects_a_naive_timestamp(self):
        """A timestamp with no timezone cannot be placed in the freshness window."""
        raw = b'<html><head><meta property="article:published_time" content="2026-09-16T10:58"></head></html>'
        self.assertIsNone(extract_published(raw))

    def test_returns_none_when_no_date_is_present(self):
        self.assertIsNone(extract_published(b"<html><body>no dates here</body></html>"))


class FailureDegradesSafely(unittest.TestCase):
    def test_search_failure_returns_no_related_sources(self):
        def broken(query, limit):
            raise RuntimeError("search backend down")

        self.assertEqual(find_related("Otsikko tasta", "https://a.fi/uutinen-x", broken), [])

    def test_offtopic_and_blocked_domains_are_never_used(self):
        def search(query, limit):
            return [
                {"url": "https://fi.wikipedia.org/wiki/Jotain", "title": "Wikipedia"},
                {"url": "https://www.facebook.com/post/12345", "title": "FB"},
                {"url": "https://a.fi/uutinen-x", "title": "Same publisher"},
                {"url": "https://um.fi/tiedotteet", "title": "Index"},
            ]

        self.assertEqual(find_related("Otsikko tasta", "https://a.fi/uutinen-x", search), [])


if __name__ == '__main__':
    unittest.main()

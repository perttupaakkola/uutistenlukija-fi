"""Invariant tests for the SEO metadata layer.

These assert behaviour contracts (a date is not a sentence end; untrusted text cannot
close a script tag), not snapshots of current output.
"""
import json
import re
import unittest

from news_mvp import seo


class Description(unittest.TestCase):
    def test_short_summary_is_returned_whole(self):
        text = "Lyhyt yhteenveto tästä uutisesta."
        self.assertEqual(seo.meta_description(text), text)

    def test_ordinal_date_is_not_treated_as_sentence_end(self):
        # Live regression: the Jakomäki article truncated to "...alkaa 14." which reads
        # as a broken snippet. A Finnish ordinal date must not end a sentence.
        summary = ("Helsingin kaupungin mukaan Jakomäen ja Vaaralan lampialueen kunnostuksen "
                   "ensimmäinen vaihe alkaa 14. syyskuuta 2026 ja kestää arviolta heinäkuun "
                   "2027 loppuun. Työssä parannetaan ulkoilureittejä.")
        result = seo.meta_description(summary)
        self.assertFalse(result.rstrip().endswith("14."), result)
        self.assertLessEqual(len(result), seo.DESCRIPTION_MAX)

    def test_truncates_at_a_real_sentence_boundary(self):
        summary = ("Ensimmäinen virke on tarpeeksi pitkä jotta se ylittää rajan selvästi. "
                   "Toinen virke jatkaa asiaa eteenpäin ja kertoo lisää yksityiskohtia. "
                   "Kolmas virke jää rajan ulkopuolelle kokonaan tässä tapauksessa.")
        result = seo.meta_description(summary)
        self.assertTrue(result.endswith("."), result)
        self.assertLessEqual(len(result), seo.DESCRIPTION_MAX)

    def test_paragraph_fallback_when_summary_is_thin(self):
        result = seo.meta_description("Lyhyt.", ["Täydennysteksti tähän mukaan lukijalle."])
        self.assertIn("Täydennysteksti", result)

    def test_never_exceeds_limit(self):
        for length in (10, 100, 158, 159, 500, 5000):
            result = seo.meta_description("sana " * length)
            self.assertLessEqual(len(result), seo.DESCRIPTION_MAX, f"length={length}")


class Titles(unittest.TestCase):
    def test_short_title_unchanged(self):
        self.assertEqual(seo.meta_title("Lyhyt otsikko"), "Lyhyt otsikko")

    def test_long_title_is_bounded(self):
        result = seo.meta_title("Sana " * 40)
        self.assertLessEqual(len(result), seo.TITLE_MAX + 1)


class HeadBlock(unittest.TestCase):
    def test_emits_core_metadata(self):
        head = seo.article_head("Otsikko", "Kuvaus", "/uutiset/x/",
                                published="2026-09-16T08:40:00+00:00")
        for needle in ('name="description"', 'property="og:title"', 'property="og:url"',
                       'name="twitter:card"', 'property="article:published_time"'):
            self.assertIn(needle, head)

    def test_og_image_absolute_url(self):
        head = seo.article_head("O", "K", "/uutiset/x/", image_url="/media/abc.jpg")
        self.assertIn("https://uutistenlukija.fi/media/abc.jpg", head)

    def test_no_image_means_no_image_tags(self):
        head = seo.article_head("O", "K", "/uutiset/x/")
        self.assertNotIn("og:image", head)
        self.assertIn("summary", head)


class JsonLd(unittest.TestCase):
    def _payload(self, html_block):
        inner = re.search(r">(\{.*\})<", html_block, re.S).group(1)
        return json.loads(inner.replace("\\u003c", "<"))

    def test_valid_news_article(self):
        block = seo.news_article_jsonld("Otsikko", "Kuvaus", "/uutiset/x/",
                                        "2026-09-16T08:40:00+00:00", None, category="Kotimaa")
        data = self._payload(block)
        self.assertEqual(data["@type"], "NewsArticle")
        self.assertEqual(data["inLanguage"], "fi")
        self.assertEqual(data["articleSection"], "Kotimaa")

    def test_script_tag_injection_is_escaped(self):
        block = seo.news_article_jsonld("</script><script>alert(1)</script>", "K",
                                        "/uutiset/x/", "2026-09-16T08:40:00+00:00", None)
        inner = re.search(r">(\{.*\})<", block, re.S).group(1)
        self.assertNotIn("</script>", inner)
        self.assertEqual(self._payload(block)["@type"], "NewsArticle")

    def test_citations_carry_source_urls(self):
        block = seo.news_article_jsonld("O", "K", "/uutiset/x/",
                                        "2026-09-16T08:40:00+00:00", None,
                                        sources=[{"title": "Lähde", "url": "https://example.fi/a"},
                                                 {"title": "Ei urlia"}])
        self.assertEqual(len(self._payload(block)["citation"]), 1)


if __name__ == "__main__":
    unittest.main()

"""Callsite regressions for the one reviewed Kuopio programme link."""
import html
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from news_mvp import site
from news_mvp.editorial import digest


ARTICLE_ID = "5cd5fcd61b42b6fadb0631d1de7662633b42576e25f9a61fc5c7f2dad208e6a6"
ARTICLE_ROUTE = "/uutiset/kuopion-vanhustenviikko-tuo-kulttuuria-kohtaamisia-5cd5fcd61b42/"
TITLE = "Kuopion Vanhustenviikko tuo kulttuuria ja kohtaamisia"
SOURCE = (
    "https://www.kuopio.fi/2026/10/05/"
    "kuopion-vanhustenviikolla-kohtaamisia-kulttuuria-ja-yhteisia-elamyksia/"
)
LABEL = "www.kuopio.fi/vanhustenviikko2026"
DESTINATION = "https://www.kuopio.fi/vanhustenviikko2026"
TEXT = (
    "Vanhustyön keskusliiton avoimia verkkoluentoja voi kaupungin mukaan seurata myös "
    "yhteisissä etäkatsomoissa: maanantaina Nilsiässä, keskiviikkona Juankoskella ja "
    "perjantaina Maaningalla. Katsomoissa on lisäksi kevyttä tuolijumppaa. Koko "
    "tapahtumaohjelma on osoitteessa www.kuopio.fi/vanhustenviikko2026."
)
OTHER_TEXT = "Vanhustenviikon muut tiedot säilyvät tavallisena tekstinä."


class FakeStore:
    def __init__(self, job):
        self.job = job

    def articles(self):
        return [self.job]

    def mark_rendered(self, _ids):
        pass


class ParagraphParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self._href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_data(self, data):
        self.text.append(data)
        if self._href is not None:
            self._link_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._link_text)))
            self._href = None
            self._link_text = []


class ProgrammeLink(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.render_number = 0

    @staticmethod
    def _source(source_id, url):
        return {
            "id": source_id,
            "url": url,
            "publisher": "Kuopion kaupunki",
            "title": "Vanhustenviikon testilähde",
            "published_at": "2026-10-05T08:00:00+03:00",
        }

    def _job(self, *, job_id=ARTICLE_ID, text=TEXT, sources=None, source_ids=None):
        sources = sources or [self._source("A", SOURCE)]
        source_ids = source_ids or ["A"]
        packet = {
            "fixture": True,
            "story_key": "programme-link-callsite-fixture",
            "sources": sources,
            "image": None,
        }
        draft = {
            "title": TITLE,
            "summary": "Rajattu testijuttu Vanhustenviikon tapahtumista.",
            "category": "Kotimaa",
            "paragraphs": [
                {"text": text, "source_ids": source_ids},
                {"text": OTHER_TEXT, "source_ids": [sources[0]["id"]]},
            ],
            "image": None,
        }
        review = {
            "approved": True,
            "draft_sha256": digest(draft),
            "reasons": ["Synthetic callsite regression fixture."],
        }
        return {
            "id": job_id,
            "packet": json.dumps(packet),
            "draft": json.dumps(draft),
            "review": json.dumps(review),
            "created_at": "2026-10-05T09:00:00+03:00",
        }

    def _render(self, job):
        self.render_number += 1
        output = self.root / str(self.render_number)
        site.render_site(FakeStore(job), output, public=False)
        article = output / site.article_path(job) / "index.html"
        page = article.read_text(encoding="utf-8")
        content = re.search(r'<div class="content">(.*?)</div>', page, re.S).group(1)
        return page, re.findall(r"<p>(.*?)</p>", content, re.S)

    @staticmethod
    def _plain_paragraph(text, source_ids, sources):
        numbers = {source["id"]: index for index, source in enumerate(sources, 1)}
        citations = " ".join(
            f'<a href="#lahde-{numbers[source_id]}">[{numbers[source_id]}]</a>'
            for source_id in source_ids
        )
        return html.escape(text, quote=True) + f' <span class="citations">{citations}</span>'

    def _assert_plain(self, job, text, source_ids, sources):
        page, paragraphs = self._render(job)
        self.assertEqual(paragraphs[0], self._plain_paragraph(text, source_ids, sources))
        self.assertNotIn(f'href="{DESTINATION}"', page)

    def test_positive_one_link_at_render_site_callsite(self):
        job = self._job()
        self.assertEqual("/" + site.article_path(job), ARTICLE_ROUTE)
        page, paragraphs = self._render(job)
        before, after = TEXT.split(LABEL)
        expected = (
            html.escape(before, quote=True)
            + f'<a href="{DESTINATION}">{LABEL}</a>'
            + html.escape(after, quote=True)
            + ' <span class="citations"><a href="#lahde-1">[1]</a></span>'
        )
        self.assertEqual(paragraphs[0], expected)
        self.assertEqual(page.count(f'href="{DESTINATION}"'), 1)
        self.assertEqual(
            paragraphs[1],
            self._plain_paragraph(OTHER_TEXT, ["A"], [self._source("A", SOURCE)]),
        )

    def test_text_and_original_citation_are_unchanged(self):
        _page, paragraphs = self._render(self._job())
        parsed = ParagraphParser()
        parsed.feed("<p>" + paragraphs[0] + "</p>")
        self.assertEqual("".join(parsed.text), TEXT + " [1]")
        self.assertEqual(parsed.links, [(DESTINATION, LABEL), ("#lahde-1", "[1]")])

    def test_other_article_is_plain(self):
        sources = [self._source("A", SOURCE)]
        job = self._job(job_id="0" * 64, sources=sources)
        self._assert_plain(job, TEXT, ["A"], sources)

    def test_exact_source_not_cited_is_plain(self):
        sources = [
            self._source("A", SOURCE),
            self._source("B", "https://www.kuopio.fi/other-source/"),
        ]
        job = self._job(sources=sources, source_ids=["B"])
        self._assert_plain(job, TEXT, ["B"], sources)

    def test_source_nearmatch_is_plain(self):
        sources = [self._source("A", SOURCE + "?redirect=evil")]
        job = self._job(sources=sources)
        self._assert_plain(job, TEXT, ["A"], sources)

    def test_text_drift_is_plain(self):
        changed = TEXT + " extra"
        sources = [self._source("A", SOURCE)]
        job = self._job(text=changed, sources=sources)
        self._assert_plain(job, changed, ["A"], sources)

    def test_hostile_text_is_escaped_and_plain(self):
        changed = TEXT + "<script>alert(1)</script>"
        sources = [self._source("A", SOURCE)]
        job = self._job(text=changed, sources=sources)
        page, paragraphs = self._render(job)
        self.assertEqual(paragraphs[0], self._plain_paragraph(changed, ["A"], sources))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", paragraphs[0])
        self.assertNotIn(f'href="{DESTINATION}"', page)

    def test_duplicate_label_is_plain(self):
        changed = TEXT + LABEL
        sources = [self._source("A", SOURCE)]
        job = self._job(text=changed, sources=sources)
        self._assert_plain(job, changed, ["A"], sources)


if __name__ == "__main__":
    unittest.main()

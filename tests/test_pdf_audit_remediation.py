"""Focused regressions for the 2026-09-30 PDF-audit remediation.

All records are synthetic and render only into temporary directories. No test sends
mail, touches production state or invokes a network boundary.
"""
import copy
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import test_generated_integrity as generated
from news_mvp import site
from news_mvp.editorial import digest


SEED = "test_generated_binding_keeps_text_provenance_and_not_applicable_marker"
CAPTION = "AI-generoitu kuva. Ei valokuva tapahtumasta."


class FakeStore:
    def __init__(self, jobs):
        self.jobs = jobs

    def articles(self):
        return list(self.jobs)

    def mark_rendered(self, _ids):
        pass


class PdfAuditRemediation(unittest.TestCase):
    def setUp(self):
        case = generated.GeneratedIntegrity(SEED)
        case.setUp()
        self.addCleanup(case.doCleanups)
        packet, draft = case.generated()
        self.case = case
        self.template = case.ready(packet, draft)

    def clone(self, index, *, title=None, source_url=None, publisher=None,
              category=None, status=None):
        job = dict(self.template)
        job["id"] = hashlib.sha256(f"pdf-remediation:{index}".encode()).hexdigest()
        job["created_at"] = (datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
                             - timedelta(minutes=index)).isoformat()
        packet = copy.deepcopy(json.loads(job["packet"]))
        draft = copy.deepcopy(json.loads(job["draft"]))
        if title is not None:
            draft["title"] = title
        if source_url is not None:
            packet["sources"][0]["url"] = source_url
        if publisher is not None:
            packet["sources"][0]["publisher"] = publisher
        if category is not None:
            draft["category"] = category
        if status is not None:
            packet["article_status"] = status
        job["packet"] = json.dumps(packet)
        job["draft"] = json.dumps(draft)
        review = json.loads(job["review"])
        review["draft_sha256"] = digest(draft)
        job["review"] = json.dumps(review)
        return job

    def render(self, jobs, public=True, output=None):
        output = output or Path(tempfile.mkdtemp(dir=self.case.root))
        site.render_site(FakeStore(jobs), output, self.case.state, public=public)
        return output

    def test_article_opening_has_no_process_label_and_caption_is_hero_only(self):
        output = self.render([self.template])
        html = (output / site.article_path(self.template) / "index.html").read_text()
        opening = html.split('<figure class="article-hero">', 1)[0].split(
            '<article class="story single-article">', 1)[1]
        visible = re.sub(r"<[^>]+>", " ", opening).casefold()
        self.assertNotIn("tekoäly", visible)
        self.assertNotIn("automa", visible)
        self.assertNotIn("vastuuvapaus", visible)
        self.assertLess(opening.index("<h1>"), opening.index('class="article-meta"'))
        self.assertLess(opening.index('class="article-meta"'), opening.index('class="lead"'))
        self.assertEqual(html.count(CAPTION), 1)
        hero = re.search(r'<figure class="article-hero">(.*?)</figure>', html, re.S).group(1)
        self.assertRegex(hero, rf'<img .*><figcaption class="article-hero-caption">{re.escape(CAPTION)}</figcaption>')
        lower = html.split('</figure>', 1)[1]
        self.assertIn("Tuotantotiedot", lower)
        self.assertIn("Lähdetarkistus ja julkaisuportit ovat automatisoituja", lower)

    def test_archive_pages_are_finite_canonical_and_stale_children_are_pruned(self):
        jobs = [self.clone(index) for index in range(65)]
        output = self.render(jobs)
        for base in ("tuoreimmat", "categories/kulttuuri"):
            pages = [output / base / "index.html",
                     output / base / "sivu/2/index.html",
                     output / base / "sivu/3/index.html"]
            self.assertTrue(all(path.is_file() for path in pages))
            expected = [30, 30, 5]
            self.assertEqual([path.read_text().count('<article class="portal-feed-item')
                              for path in pages], expected)
            self.assertIn(f'href="/{base}/sivu/2/"', pages[0].read_text())
            self.assertIn(f'href="/{base}/"', pages[1].read_text())
            self.assertIn(f'https://uutistenlukija.fi/{base}/sivu/3/', pages[2].read_text())
        self.render(jobs[:1], output=output)
        self.assertFalse((output / "tuoreimmat/sivu/2").exists())
        self.assertFalse((output / "categories/kulttuuri/sivu/2").exists())

    def test_confirmed_duplicate_leaves_addresses_but_not_discovery_surfaces(self):
        title = "Vantaa uudistaa Kyytitien päiväkodin"
        first = self.clone(
            1, title=title,
            source_url="https://example.invalid/tiedote/vantaa-kyytitien-paivakoti-uudistetaan",
        )
        second = self.clone(
            2, title=title,
            source_url="https://example.invalid/tiedote/vantaa-kyytitien-paivakoti-uudistetaaan",
        )
        output = self.render([first, second], public=False)
        latest = (output / "tuoreimmat/index.html").read_text()
        self.assertEqual(latest.count('<article class="portal-feed-item'), 1)
        self.assertEqual((output / "rss.xml").read_text().count("<item>"), 1)
        self.assertTrue((output / site.article_path(first) / "index.html").is_file())
        self.assertTrue((output / site.article_path(second) / "index.html").is_file())

    def test_withdrawal_fixture_hides_deck_prose_and_image(self):
        created = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
        job = self.clone(0, status={
            "kind": "withdrawn",
            "at": (created + timedelta(hours=1)).isoformat(),
            "note": "Julkaisuperustetta ei voitu enää vahvistaa.",
        })
        output = self.render([job], public=False)
        html = (output / site.article_path(job) / "index.html").read_text()
        article = html.split('<article class="story single-article">', 1)[1].split("</article>", 1)[0]
        self.assertIn("Juttu on poistettu", article)
        self.assertIn("Julkaisuperustetta ei voitu enää vahvistaa.", article)
        self.assertNotIn(json.loads(job["draft"])["summary"], article)
        self.assertNotIn('<div class="content">', article)
        self.assertNotIn('<figure class="article-hero">', article)
        self.assertNotIn(job["id"], (output / "rss.xml").read_text())

    def test_human_time_sources_and_reuse_are_distinct(self):
        output = self.render([self.template])
        html = (output / site.article_path(self.template) / "index.html").read_text()
        sources = html.split('<section class="sources">', 1)[1].split("</section>", 1)[0]
        reuse = html.split('<section class="source-reuse">', 1)[1].split("</section>", 1)[0]
        self.assertIn("1 uutislähde", sources)
        self.assertRegex(sources, r'Lähteen päiväys: <time datetime="[^"]+">\d{1,2}\.\d{1,2}\.\d{4} klo \d{2}\.\d{2}</time>')
        self.assertNotIn("Jakelu ja tekstin käyttöehdot", sources)
        self.assertIn("eivät erillistä vahvistavaa lähdettä", reuse)

    def test_related_render_rejects_same_municipality_without_shared_topic(self):
        shared = {"publisher": "Oulun kaupunki", "category": "Kotimaa"}
        anchor = self.clone(
            1,
            title="Kirjasto saa uuden lukusalin",
            source_url="https://www.ouka.fi/a",
            **shared,
        )
        unrelated = self.clone(
            2,
            title="Jalkapallokenttä suljetaan remontin vuoksi",
            source_url="https://www.ouka.fi/b",
            **shared,
        )
        related = self.clone(
            3,
            title="Kirjaston lukusali avautuu syksyllä",
            source_url="https://www.ouka.fi/c",
            **shared,
        )

        def record(job):
            return json.loads(job["packet"]), json.loads(job["draft"])

        packet, draft = record(anchor)
        unrelated_packet, unrelated_draft = record(unrelated)
        related_packet, related_draft = record(related)
        self.assertEqual(
            site.related_story_score(packet, draft, unrelated_packet, unrelated_draft),
            0,
        )
        self.assertGreaterEqual(
            site.related_story_score(packet, draft, related_packet, related_draft),
            4,
        )

        output = self.render([anchor, unrelated, related], public=False)
        anchor_html = (output / site.article_path(anchor) / "index.html").read_text()
        anchor_related = anchor_html.split('<section class="related">', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn("/" + site.article_path(related), anchor_related)
        self.assertNotIn("/" + site.article_path(unrelated), anchor_related)

        unrelated_html = (output / site.article_path(unrelated) / "index.html").read_text()
        self.assertNotIn('<section class="related">', unrelated_html)

    def test_related_render_requires_topic_before_category_publisher_and_host_boosts(self):
        shared = {"publisher": "Example municipality", "category": "Kotimaa"}
        anchor = self.clone(
            11,
            title="Kirjaston remontti alkaa lokakuussa",
            source_url="https://example.invalid/news/a",
            **shared,
        )
        unrelated = self.clone(
            12,
            title="Jalkapallojoukkue voitti mestaruuden",
            source_url="https://example.invalid/news/b",
            **shared,
        )
        related = self.clone(
            13,
            title="Kirjaston remontti valmistuu keväällä",
            source_url="https://example.invalid/news/c",
            **shared,
        )

        def record(job):
            return json.loads(job["packet"]), json.loads(job["draft"])

        packet, draft = record(anchor)
        unrelated_packet, unrelated_draft = record(unrelated)
        related_packet, related_draft = record(related)
        self.assertEqual(
            site.related_story_score(packet, draft, unrelated_packet, unrelated_draft),
            0,
        )
        self.assertGreaterEqual(
            site.related_story_score(packet, draft, related_packet, related_draft),
            4,
        )

        output = self.render([anchor, unrelated, related], public=False)
        anchor_html = (output / site.article_path(anchor) / "index.html").read_text()
        anchor_related = anchor_html.split('<section class="related">', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn("/" + site.article_path(related), anchor_related)
        self.assertNotIn("/" + site.article_path(unrelated), anchor_related)

        unrelated_html = (output / site.article_path(unrelated) / "index.html").read_text()
        self.assertNotIn('<section class="related">', unrelated_html)

    def test_about_and_actions_do_not_publish_an_unverified_contact(self):
        output = self.render([self.template])
        rendered = "\n".join(path.read_text() for path in output.rglob("*.html"))
        about = (output / "tietoja/index.html").read_text()
        self.assertNotIn("mailto:", rendered.casefold())
        self.assertNotIn("info@uutistenlukija", rendered.casefold())
        self.assertIn("Varmistettua yleisön yhteydenottokanavaa ei julkaista", about)
        article = (output / site.article_path(self.template) / "index.html").read_text()
        self.assertIn('href="/tietoja/#korjaukset"', article)
        self.assertIn('data-share-url="https://uutistenlukija.fi/', article)

    def test_scoped_normal_text_contrast_rules_exceed_four_point_five(self):
        compatibility = (site.ROOT / "static/style.css").read_text()
        portal = (site.ROOT / "static/css/portal-overhaul.css").read_text()
        theme = (site.ROOT / "static/css/style.css").read_text()
        self.assertIn(
            ':root[data-theme="dark"] .portal-feed-item__meta a{color:#8ab4ff}',
            compatibility,
        )
        self.assertIn(
            '[data-theme="dark"] .portal-river .portal-module-head a { color: #8ab4ff; }',
            portal,
        )
        self.assertRegex(
            theme,
            r"\.site-footer-copyright\s*\{[^}]*background:\s*#0a0b0d;[^}]*color:\s*#808080;",
        )

        def luminance(rgb):
            channels = [value / 255 for value in rgb]
            linear = [value / 12.92 if value <= 0.04045
                      else ((value + 0.055) / 1.055) ** 2.4
                      for value in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(foreground, background):
            lighter, darker = sorted((luminance(foreground), luminance(background)),
                                     reverse=True)
            return (lighter + 0.05) / (darker + 0.05)

        self.assertGreaterEqual(contrast((138, 180, 255), (16, 18, 20)), 4.5)
        self.assertGreaterEqual(contrast((128, 128, 128), (10, 11, 13)), 4.5)

    def test_datetime_uses_utc_machine_value_and_helsinki_dst(self):
        self.assertEqual(site.semantic_datetime("2026-03-29T00:30:00Z"),
                         ("2026-03-29T00:30:00Z", "29.3.2026 klo 02.30"))
        self.assertEqual(site.semantic_datetime("2026-03-29T01:30:00Z"),
                         ("2026-03-29T01:30:00Z", "29.3.2026 klo 04.30"))

    def test_writer_prompt_keeps_process_out_of_title_and_deck(self):
        prompt = (site.ROOT / "prompts/writer.md").read_text().casefold()
        self.assertIn("älä lisää otsikkoon tai summary-ingressiin tekoälyä", prompt)
        self.assertIn("ensimmäinen kappale vie uutista eteenpäin", prompt)
        self.assertIn("säilytä lähteiden epävarmuudet", prompt)


if __name__ == "__main__":
    unittest.main()

"""Regression checks for public/private site metadata.

Every record is synthetic and confined to the temporary ReleaseV2 state; each
render writes to temporary output and no publish or network call is made.
"""
import copy
import json
import re
import unittest
from unittest.mock import patch

import test_release_v2 as base
from news_mvp import official, publish, site
from news_mvp.store import database


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\uFE0F]")
FOOTER_RE = re.compile(r"<footer\b.*?</footer\s*>", re.I | re.S)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
ATTR_RE = re.compile(r'([a-zA-Z][\w:-]*)\s*=\s*"([^"]*)"')
JSONLD_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


class TinyStore:
    """One-job store for a private render; mark_rendered is intentionally a no-op."""

    def __init__(self, job):
        self.jobs = [job]

    def articles(self):
        return list(self.jobs)

    def mark_rendered(self, *args, **kwargs):
        pass


class SiteMetadata(unittest.TestCase):
    def setUp(self):
        case = base.ReleaseV2("source_fetch")
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.base = case
        self.state = case.state
        self.packet = case.packet
        self.draft = case.draft
        self.job = case.ready()

    @staticmethod
    def _attrs(tag):
        return {key.lower(): value for key, value in ATTR_RE.findall(tag)}

    def _tags(self, text, name):
        return [self._attrs(tag) for tag in re.findall(rf"<{name}\b[^>]*>", text, re.I)]

    def _jsonld(self, text):
        return [json.loads(raw) for raw in JSONLD_RE.findall(text)]

    def _site_root(self, output):
        pages = [path.parent for path in output.rglob("index.html")]
        self.assertTrue(pages, f"no rendered index.html under {output}")
        return min(pages, key=lambda path: (len(path.parts), str(path)))

    def _page(self, output, job):
        path = self._site_root(output) / site.article_path(job).lstrip("/")
        return path if path.suffix else path / "index.html"

    def _read(self, output, job):
        return self._page(output, job).read_text(encoding="utf-8")

    def _footer_hrefs(self, text):
        match = FOOTER_RE.search(text)
        if not match:
            return []
        return [
            self._attrs(tag).get("href", "")
            for tag in re.findall(r"<a\b[^>]*>", match.group(0), re.I)
        ]

    def _required_footer_links(self, text):
        hrefs = self._footer_hrefs(text)
        self.assertTrue(hrefs, "public page footer has no links")
        self.assertGreaterEqual(len(set(hrefs)), 3, f"public footer links: {hrefs}")
        for required in ("/tietosuoja/", "/lahteet/", "/rss.xml"):
            self.assertIn(required, hrefs, f"public footer is missing {required}: {hrefs}")

    def _render_public(self):
        with database(self.state) as store:
            with patch.object(publish, "cmd", return_value=base.COMMIT):
                site_path, receipt = publish.public_bundle(store, self.job, self.state)
        return site_path

    def _render_private(self, store, name):
        output = self.base.root / name
        output.mkdir()
        site.render_site(store, output, self.state, public=False)
        return output

    def test_public_home_metadata_and_jsonld(self):
        output = self._render_public()
        home = (self._site_root(output) / "index.html").read_text(encoding="utf-8")
        metas = self._tags(home, "meta")
        named = {tag.get("name"): tag.get("content") for tag in metas if tag.get("name")}
        properties = {tag.get("property"): tag.get("content") for tag in metas if tag.get("property")}
        self.assertEqual(named.get("description"), site.HOME_DESCRIPTION)
        self.assertEqual(properties.get("og:site_name"), site.SITE_NAME)
        self.assertEqual(properties.get("og:type"), "website")
        self.assertIn(site.SITE_NAME, properties.get("og:title", ""))
        self.assertEqual(properties.get("og:description"), site.HOME_DESCRIPTION)
        self.assertRegex(named.get("twitter:card", ""), r"^summary(?:_large_image)?$")
        self.assertIn(site.SITE_NAME, named.get("twitter:title", ""))
        self.assertEqual(named.get("twitter:description"), site.HOME_DESCRIPTION)
        links = self._tags(home, "link")
        self.assertEqual(
            [tag.get("href") for tag in links if tag.get("rel") == "canonical"],
            [site.SITE_URL],
        )
        feeds = [
            tag.get("href", "")
            for tag in links
            if tag.get("rel") == "alternate" and "rss" in (tag.get("type") or "")
        ]
        self.assertEqual(len(feeds), 1)
        self.assertTrue(feeds[0].endswith(".xml"), feeds)
        title = TITLE_RE.search(home).group(1)
        self.assertIn(site.SITE_NAME, title)
        self.assertIsNone(EMOJI_RE.search(title), f"emoji in public title: {title!r}")
        self._required_footer_links(home)
        payloads = self._jsonld(home)
        websites = [payload for payload in payloads if payload.get("@type") == "WebSite"]
        self.assertEqual(len(websites), 1)
        self.assertEqual(websites[0].get("name"), site.SITE_NAME)
        self.assertEqual(websites[0].get("url"), site.SITE_URL)
        self.assertEqual(websites[0].get("description"), site.HOME_DESCRIPTION)
        item_lists = [payload for payload in payloads if payload.get("@type") == "ItemList"]
        self.assertEqual(len(item_lists), 1)
        self.assertIn(
            {
                "@type": "ListItem",
                "position": 1,
                "url": site.SITE_URL + site.article_path(self.job),
                "name": self.draft["title"],
            },
            item_lists[0]["itemListElement"],
        )
        article = self._read(output, self.job)
        self.assertIn("Helsingin kaupunki", article)
        self.assertIn(
            "Teksti on tuotettu tekoälyn avulla ja tarkastettu erillisessä lähdetarkistuksessa.",
            article,
        )

    def test_private_page_excludes_public_navigation(self):
        with database(self.state) as store:
            private_output = self._render_private(store, "private-page")
        private = self._read(private_output, self.job)
        robots = [
            tag.get("content", "")
            for tag in self._tags(private, "meta")
            if tag.get("name") == "robots"
        ]
        self.assertTrue(any("noindex" in content for content in robots), f"robots: {robots}")
        canonical = [
            tag.get("href", "")
            for tag in self._tags(private, "link")
            if tag.get("rel") == "canonical"
        ]
        self.assertFalse(
            [href for href in canonical if href.startswith("http")],
            f"private page exposes a public canonical: {canonical}",
        )
        feeds = [
            tag
            for tag in self._tags(private, "link")
            if "application/rss+xml" in (tag.get("type") or "")
        ]
        self.assertEqual(feeds, [])
        self.assertEqual(self._footer_hrefs(private), [])
        public_output = self._render_public()
        self._required_footer_links(self._read(public_output, self.job))

    def test_image_metadata_and_jsonld_escaping(self):
        dimensions = site.image_dimensions
        self.assertEqual(site.GENERATED_IMAGE_FALLBACK, (1536, 1024))
        self.assertEqual(
            dimensions({"pixels": {"width": 1200, "height": 800}, "width": 640, "height": 480}),
            (1200, 800),
        )
        self.assertEqual(
            dimensions({"pixels": {"width": 0, "height": 0}, "width": 640, "height": 480}),
            (640, 480),
        )
        self.assertEqual(dimensions({"generated": True}), site.GENERATED_IMAGE_FALLBACK)
        self.assertEqual(dimensions({"generated": True, "width": 640, "height": 480}), (640, 480))
        self.assertEqual(dimensions({"width": 640, "height": 480}), (640, 480))
        self.assertIsNone(dimensions({}))
        self.assertIsNone(dimensions({"width": 0, "height": 480}))
        self.assertIsNone(dimensions({"width": True, "height": 480}))
        self.assertEqual(
            site.image_size_attributes({"pixels": {"width": 1200, "height": 800}}),
            ' width="1200" height="800" decoding="async"',
        )
        self.assertEqual(
            site.image_size_attributes({"width": 640, "height": 480}),
            ' width="640" height="480" decoding="async"',
        )
        self.assertEqual(site.image_size_attributes({"width": 0, "height": 480}), ' decoding="async"')
        payload = {
            "@type": "Article",
            "headline": "</script><script>alert('x')</script>",
            "text": "a & b < c > d",
            "name": "Helsingin kaupunki",
        }
        tag = site.jsonld_script(payload)
        self.assertTrue(tag.startswith('<script type="application/ld+json">'))
        self.assertTrue(tag.endswith("</script>"))
        self.assertEqual(tag.count("</script>"), 1)
        raw = tag[len('<script type="application/ld+json">') : -len("</script>")]
        self.assertNotIn("<", raw)
        self.assertNotIn(">", raw)
        self.assertNotIn("&", raw)
        self.assertEqual(json.loads(raw), payload)

    def test_article_reuse_license_and_private_provider_terms(self):
        output = self._render_public()
        reuse = self.packet["sources"][0]["reuse"]
        article = self._read(output, self.job)
        self.assertIn(reuse["license"], article)
        self.assertIn(reuse["license_url"], article)
        self.assertEqual(site.short_license_label(reuse["license_url"]), "CC BY 4.0")
        self.assertIn("CC BY 4.0", article)

        variant = copy.deepcopy(self.job)
        government = official.reuse(official.policy()["providers"]["valtioneuvosto"])
        packet = json.loads(variant["packet"])
        packet["sources"][0]["reuse"] = government
        variant["packet"] = json.dumps(packet)
        private_output = self._render_private(TinyStore(variant), "private-reuse")
        private = self._read(private_output, variant)
        self.assertIn(government["license"], private)
        self.assertIn(government["license_url"], private)
        self.assertEqual(site.short_license_label(government["license_url"]), "")
        self.assertNotIn("CC BY 4.0", private)


if __name__ == "__main__":
    unittest.main()

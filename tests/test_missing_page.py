"""Offline tests for the public 404 body: honest copy, usable exits, no index claim.

Pages are parsed as HTML rather than matched with string surgery, so each assertion
names the element or attribute it depends on. No network, no state, no publishing.
"""
import re
import unittest
from html.parser import HTMLParser

from news_mvp import site

GOOGLE = "https://www.google.com/search"
CONSENT_IDS = {"consent-settings", "consent-dialog", "consent-title", "consent-accept",
               "consent-reject", "consent-close"}


class _Parser(HTMLParser):
    """Tag/attribute and visible-text capture, with <main> tracked separately."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.visible = []
        self.main_tags = []
        self.main_visible = []
        self._skip = 0
        self._main = 0

    def handle_starttag(self, tag, attrs):
        parsed = {name: value or "" for name, value in attrs}
        self.tags.append((tag, parsed))
        if tag == "main":
            self._main += 1
        if self._main:
            self.main_tags.append((tag, parsed))
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "main" and self._main:
            self._main -= 1
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        self.visible.append(data)
        if self._main:
            self.main_visible.append(data)


def parse(html):
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser


def text_of(parts):
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def elements(parser, tag, scope=None, **match):
    found = []
    for name, attrs in (parser.main_tags if scope == "main" else parser.tags):
        if name == tag and all(attrs.get(key) == value for key, value in match.items()):
            found.append(attrs)
    return found


def consent_elements(parser):
    """Consent/privacy UI of a page, as parsed elements."""
    return [(tag, attrs) for tag, attrs in parser.tags
            if attrs.get("id") in CONSENT_IDS
            or attrs.get("src", "").split("/")[-1] in ("consent.js", "analytics.js")]


class MissingPage(unittest.TestCase):
    def setUp(self):
        self.html = site.missing_page()
        self.doc = parse(self.html)
        self.text = text_of(self.doc.main_visible)

    def test_valid_archive_paths_render_a_full_page(self):
        for path in ("/", "/sivu/2/"):
            with self.subTest(path=path):
                html = site.missing_page(path)
                self.assertTrue(html.startswith("<!doctype html>"))
                document = parse(html)
                self.assertEqual(len(elements(document, "h1", scope="main")), 1)
                self.assertIn("Sivua ei löytynyt", text_of(document.main_visible))

    def test_copy_says_the_page_is_missing_and_the_link_may_be_stale(self):
        self.assertIn("Sivua ei löytynyt", self.text)
        self.assertIn("Vanha linkki voi viitata sisältöön, jota ei enää julkaista.", self.text)
        self.assertIn("Siirry uusimpiin uutisiin", self.text)
        self.assertIn("Hae Googlesta", self.text)
        self.assertNotIn("Emme palauttaneet", self.text)
        self.assertNotRegex(self.text, r"(ohjaamme|uudelleenohjaus|korvaava|siirretty)")

    def test_default_page_has_no_archive_link_and_promises_no_archive(self):
        for call in (site.missing_page(), site.missing_page("/"), site.missing_page(None)):
            with self.subTest(call=call[:40]):
                document = parse(call)
                self.assertEqual(elements(document, "a", scope="main", href="/"), [{"href": "/"}])
                self.assertEqual([attrs for attrs in elements(document, "a", scope="main")
                                  if attrs["href"].startswith("/sivu/")], [])
                body = text_of(document.main_visible)
                self.assertNotIn("Arkiston sivu", body)
                self.assertNotIn("arkisto", body.lower())
                self.assertIn("uusimmat uutiset ja haku", body)

    def test_supplied_archive_path_links_only_that_archive_page(self):
        path = "/sivu/2/"
        document = parse(site.missing_page(path))
        self.assertEqual(elements(document, "a", scope="main", href=path), [{"href": path}])
        for attrs in elements(document, "a", scope="main"):
            self.assertIn(attrs["href"], ("/", path))
        body = text_of(document.main_visible)
        self.assertIn("Arkiston sivu 2", body)
        self.assertNotIn("uusimmat uutiset ja haku", body)

    def test_invalid_archive_paths_are_rejected(self):
        invalid = ["", " ", "/sivu/", "/sivu/1/", "/sivu/0/", "/sivu/01/", "/sivu/02/", "/sivu/007/",
                   "/sivu/2", "/sivu/2//", "/sivu/2/?a=1", "//sivu/2/", "sivu/2/", "/sivu/2/#x",
                   "/sivu/-2/", "/sivu/+2/", "/sivu/2.0/", "/sivu/2 /", "/sivu/ 2/", "/SIVU/2/",
                   "https://evil.example/sivu/2/", '/sivu/2/"><script>alert(1)</script>',
                   "/sivu/2/</a><script>alert(1)</script>", "javascript:alert(1)",
                   2, 2.0, True, False, ["/sivu/2/"], {"/sivu/2/"}, object()]
        for value in invalid:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    site.missing_page(value)
                with self.assertRaises(ValueError):
                    site.archive_page_path(value)

    def test_noindex_without_canonical_og_or_private_banner(self):
        robots = elements(self.doc, "meta", name="robots")
        self.assertEqual(len(robots), 1)
        self.assertIn("noindex", robots[0]["content"])
        self.assertEqual(elements(self.doc, "link", rel="canonical"), [])
        self.assertEqual(elements(self.doc, "meta", property="og:url"), [])
        self.assertEqual(elements(self.doc, "meta", name="description"), [])
        self.assertEqual(elements(self.doc, "script", type="application/ld+json"), [])
        self.assertNotIn("canonical", self.html)
        self.assertNotIn("Yksityinen esikatselu", self.html)
        self.assertEqual(elements(self.doc, "div", **{"class": "preview"}), [])
        self.assertNotIn("Tämä paikallinen versio", self.html)
        self.assertNotIn("/assets/", self.html)

    def test_public_assets_and_consent_match_a_public_page(self):
        public = parse(site.page("T", "<p>x</p>", "/"))
        self.assertEqual(consent_elements(self.doc), consent_elements(public))
        self.assertTrue(consent_elements(self.doc))
        self.assertEqual(elements(self.doc, "link", rel="stylesheet"),
                         elements(public, "link", rel="stylesheet"))
        for asset in ("/mvp-assets/style.css", "/mvp-assets/consent.js", "/mvp-assets/analytics.js"):
            self.assertIn(asset, self.html)
        self.assertIn((site.ROOT / "static/consent.html").read_text(), self.html)
        self.assertIn('<a href="/tietosuoja/">Tietosuoja</a>', self.html)

    def test_search_form_is_labelled_google_search_scoped_to_the_site(self):
        form = elements(self.doc, "form", role="search")
        self.assertEqual(len(form), 2)
        for attrs in form:
            self.assertEqual(attrs["action"], GOOGLE)
            self.assertEqual(attrs["method"].lower(), "get")
            self.assertEqual(attrs["role"], "search")
        query = elements(self.doc, "input", name="q")
        self.assertEqual(len(query), 2)
        self.assertEqual({attrs["type"] for attrs in query}, {"search"})
        self.assertEqual({attrs.get("value", "") for attrs in query}, {""})
        self.assertEqual({attrs["id"] for attrs in query},
                         {"header-search-input", "missing-search-input"})
        labels = [attrs for attrs in elements(self.doc, "label")
                  if attrs.get("for") in {"header-search-input", "missing-search-input"}]
        self.assertEqual(len(labels), 2)
        self.assertIn("Hae uutisia Googlesta", self.text)
        self.assertIn("Googlen omalla sivulla", self.text)
        self.assertEqual(elements(self.doc, "input", type="hidden"),
                         [{"type": "hidden", "name": "sitesearch", "value": "uutistenlukija.fi"},
                          {"type": "hidden", "name": "sitesearch", "value": "uutistenlukija.fi"}])
        self.assertEqual(site.SEARCH_SITE, "uutistenlukija.fi")
        self.assertNotIn("q=", self.html)

    def test_no_refresh_redirect_or_inline_handler(self):
        self.assertNotIn("refresh", self.html.lower())
        for attrs in elements(self.doc, "meta"):
            self.assertNotIn(attrs.get("http-equiv", "").lower(), ("refresh", "location"))
        for word in ("location.href", "location.replace", "location.assign",
                     "window.location", "document.location", "setTimeout", "<noscript"):
            self.assertNotIn(word, self.html)
        for tag, attrs in self.doc.tags:
            self.assertEqual([name for name in attrs if name.startswith("on")], [], (tag, attrs))

    def test_page_defaults_are_unchanged(self):
        public = site.page("T", "<p>x</p>", "/")
        self.assertIn('<link rel="canonical" href="https://uutistenlukija.fi/">', public)
        self.assertNotIn("noindex", public)
        private = site.page("T", "<p>x</p>")
        self.assertIn("noindex,nofollow", private)
        self.assertIn('<div class="preview">Yksityinen esikatselu · ei julkaistu</div>', private)
        self.assertIn('/assets/style.css', private)


if __name__ == "__main__":
    unittest.main()

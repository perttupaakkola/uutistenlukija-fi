"""R5 regressions: actual Hugo/base templates, old archives and real guide sources.

Offline, bounded fixture only. No JS, requests, providers or production build.
"""
import os
import json
from html import unescape
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
HUGO = os.environ.get('HUGO_BIN', '/home/pertt/.openclaw/workspace/bin/hugo')
LEAVES = ('matkat', 'merkitys', 'paivamaarat', 'perinteet-lapset', 'ruoka')


class ArchiveHonesty(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ul-archive-honesty-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.site = Path(cls.temp.name)
        shutil.copytree(ROOT / 'layouts', cls.site / 'layouts')
        (cls.site / 'assets/css').mkdir(parents=True)
        shutil.copy(ROOT / 'assets/css/404.css', cls.site / 'assets/css/404.css')
        for section in ('categories', 'paasiaisopas', 'vappuopas', 'oppaat'):
            shutil.copytree(ROOT / 'content' / section, cls.site / 'content' / section)
        # Only the digest landing is a related target; don't copy daily archives.
        (cls.site / 'content/paivan-kooste').mkdir()
        shutil.copy(ROOT / 'content/paivan-kooste/_index.md', cls.site / 'content/paivan-kooste/_index.md')
        shutil.copy(ROOT / 'content/evasteet.md', cls.site / 'content/evasteet.md')
        (cls.site / 'content/posts').mkdir()
        cls.categories = sorted(p.parent.name for p in (ROOT / 'content/categories').glob('*/_index.md'))
        for category in cls.categories:
            # Politics deliberately empty; Talous deliberately old and paginated.
            count = 35 if category == 'talous' else (0 if category == 'politiikka' else 1)
            for i in range(count):
                (cls.site / f'content/posts/{category}-{i:02}.md').write_text(
                    f'---\ntitle: "{category} fixture {i:02}"\ndate: 2026-01-01T12:{i:02}:00Z\n'
                    f'categories: ["{category.title()}"]\n---\nOffline archive fixture.\n')
        # Resolve all real related/focus links, not fabricated destination stubs.
        category_template = (ROOT / 'layouts/taxonomy/category.html').read_text()
        for route in re.findall(r'"url" "(/posts/[^"]+)/"', category_template):
            source = ROOT / 'content' / (route.lstrip('/') + '.md')
            if not source.is_file():
                raise AssertionError(f'Missing real focus source: {source}')
            shutil.copy(source, cls.site / 'content/posts')
        (cls.site / 'hugo.toml').write_text('''baseURL="https://fixture.invalid/"
title="Uutistenlukija"
languageCode="fi"
timeZone="UTC"
disableKinds=["RSS","sitemap","robotsTXT"]
[markup.goldmark.renderer]
unsafe=true
[taxonomies]
category="categories"
tag="tags"
''')
        result = subprocess.run([HUGO, '--source', str(cls.site), '--destination', str(cls.site / 'public'), '--cacheDir', str(cls.site / 'cache'), '--noBuildLock'], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        size = sum(p.stat().st_size for p in cls.site.rglob('*') if p.is_file())
        if size > 32 * 1024 * 1024:
            raise AssertionError(f'Fixture exceeded 32 MiB: {size}')
        inputs = list((cls.site / 'content').rglob('*.md'))
        if len(inputs) > 100:
            raise AssertionError(f'Fixture exceeded 100 content inputs: {len(inputs)}')
        if evidence := os.environ.get('UL_ARCHIVE_EVIDENCE'):
            destination = Path(evidence)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / 'hugo-output.txt').write_text(result.stdout + result.stderr)
            (destination / 'fixture-size.json').write_text(json.dumps({'content_inputs': len(inputs), 'total_bytes': size}))
            for route in ['kategoriat/talous', 'kategoriat/talous/page/2', 'categories/politiikka', 'paasiaisopas', 'vappuopas', 'oppaat/kauppojen-aukioloajat'] + [f'paasiaisopas/{leaf}' for leaf in LEAVES]:
                shutil.copy(cls.site / 'public' / route / 'index.html', destination / (route.replace('/', '-') + '.html'))

    def page(self, route):
        return unescape((self.site / 'public' / route.strip('/') / 'index.html').read_text())

    def capture(self, pattern, html):
        match = re.search(pattern, html, re.S)
        self.assertIsNotNone(match, pattern)
        assert match is not None
        return match.group(1)

    def test_every_rendered_category_related_and_focus_link_resolves(self):
        checked = []
        for category in self.categories:
            route = '/kategoriat/talous/' if category == 'talous' else '/categories/' + category + '/'
            pages = [route, route + 'page/2/'] if category == 'talous' else [route]
            for page in pages:
                html = self.page(page)
                navs = re.findall(r'<nav class="(?:category-related-links|category-focus-links__list)"[^>]*>(.*?)</nav>', html, re.S)
                for nav in navs:
                    links = re.findall(r'href="([^"]+)"', nav)
                    self.assertTrue(links)
                    for link in links:
                        with self.subTest(page=page, link=link):
                            target = self.page(urlsplit(link).path)
                            self.assertIn('<link rel="canonical"', target)
                            # Related category links must be direct, not alias documents.
                            if '/categories/' in link or '/kategoriat/' in link:
                                canonical = self.capture(r'<link rel="canonical" href="([^"]+)"', target)
                                self.assertEqual(urlsplit(canonical).path, link)
                                self.assertNotIn('http-equiv="refresh"', target.lower())
                            checked.append((page, link))
        # 3 related maps x 3 links; Talous second page repeats 3 + 5 focus links.
        self.assertEqual(len(checked), 22)
        self.assertIn(('/kategoriat/talous/', '/categories/teknologia/'), checked)

    def test_old_talous_page_two_has_time_neutral_seo(self):
        for route in ('/kategoriat/talous/', '/kategoriat/talous/page/2/'):
            html = self.page(route)
            title = self.capture(r'<title>(.*?)</title>', html)
            self.assertIn('Talousuutiset', title)
            self.assertNotRegex(title.casefold(), r'tänään|juuri nyt')
            self.assertIn('arkisto', title.casefold())
            canonical = self.capture(r'<link rel="canonical" href="([^"]+)"', html)
            self.assertEqual(urlsplit(canonical).path, route)
        header = self.page('/kategoriat/talous/page/2/').split('<header class="portal-list-header">', 1)[1].split('</header>', 1)[0]
        self.assertIn('2026-01-01T', header)

    def test_historical_hub_incoming_hours_claims_are_explicitly_expired(self):
        for route in ('paasiaisopas', 'vappuopas'):
            with self.subTest(route=route):
                html = self.page(route)
                paragraphs = re.findall(r'<p>(.*?)</p>', html, re.S)
                incoming = [p for p in paragraphs if 'href="/oppaat/kauppojen-aukioloajat/"' in p]
                self.assertEqual(len(incoming), 1)
                paragraph = incoming[0].casefold()
                self.assertIn('tarkistuslinkit', paragraph)
                self.assertIn('voimassaolo on päättynyt', paragraph)
                self.assertIn('ei ole vahvistettu', paragraph)
                self.assertNotIn('ajantasaisesta', paragraph)
                self.assertNotIn('nykyiset poikkeusaukiolot tarkistetaan', paragraph)

    def test_all_five_old_easter_leaves_have_visible_archive_warning(self):
        self.assertEqual(len(LEAVES), 5)
        for leaf in LEAVES:
            with self.subTest(leaf=leaf):
                route = f'/paasiaisopas/{leaf}/'
                html = self.page(route)
                header = html.split('<header class="portal-article-header', 1)[1].split('</header>', 1)[0]
                self.assertIn('aria-label="Oppaan arkistotila"', header)
                self.assertIn('Historiallinen opas', header)
                self.assertIn('ei ole tarkistettu nykyhetkeä varten', header)
                self.assertIn('eikä sitä pidä käyttää ajantasaisena oppaana', header)
                self.assertIn('2026-03-27T', header)
                self.assertNotIn('Päivitetty', header)
                canonical = self.capture(r'<link rel="canonical" href="([^"]+)"', html)
                self.assertEqual(urlsplit(canonical).path, route)

    def test_expired_guide_aliases_and_legal_page_remain_unchanged(self):
        guide = self.page('/oppaat/kauppojen-aukioloajat/')
        self.assertIn('noindex,follow', guide)
        self.assertIn('voimassaoloa ei ole jatkettu', guide)
        self.assertIn('https://www.k-ryhma.fi/kauppojen-aukioloajat', guide)
        # Legacy hours URLs are Worker redirects, not Hugo alias documents.
        worker = (ROOT / 'static/_worker.js').read_text()
        for route in ('paasiaisopas/kaupat-auki', 'vappuopas/kaupat-auki'):
            self.assertIn(f"['/{route}', '/oppaat/kauppojen-aukioloajat/']", worker)
        self.assertIn('Tarkistusta odottavat oppaat', self.page('/oppaat/'))
        legal = self.page('/evasteet/')
        self.assertNotIn('Oppaan arkistotila', legal)
        self.assertNotIn('class="ai-disclosure"', legal)
        self.assertEqual((self.site / 'content/evasteet.md').read_bytes(), (ROOT / 'content/evasteet.md').read_bytes())

    def test_zero_politics_has_neutral_description_and_no_latest(self):
        html = self.page('/categories/politiikka/')
        header = html.split('<header class="portal-list-header">', 1)[1].split('</header>', 1)[0]
        self.assertNotIn('Syvällistä analyysia', html)
        self.assertIn('Politiikan uutisarkisto', header)
        self.assertNotIn('Uusin tämän sivun juttu:', header)
        self.assertIn('Tässä kategoriassa ei ole vielä artikkeleita', html)


if __name__ == '__main__':
    unittest.main()

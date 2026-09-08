"""Bounded offline category coverage proof using actual templates and descriptions."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from html import unescape

ROOT = Path(__file__).resolve().parents[2]
HUGO = os.environ.get('HUGO_BIN', '/home/pertt/.openclaw/workspace/bin/hugo')


class CategoryCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ul-category-coverage-')
        cls.site = Path(cls.temp.name)
        shutil.copytree(ROOT / 'layouts', cls.site / 'layouts')
        (cls.site / 'assets/css').mkdir(parents=True)
        shutil.copy(ROOT / 'assets/css/404.css', cls.site / 'assets/css/404.css')
        shutil.copytree(ROOT / 'content/categories', cls.site / 'content/categories')
        (cls.site / 'content/posts').mkdir(parents=True)
        cls.categories = sorted(p.parent.name for p in (ROOT / 'content/categories').glob('*/_index.md'))
        for category in cls.categories:
            for i in range(35 if category == 'kulttuuri' else 2):
                (cls.site / f'content/posts/{category}-{i:02}.md').write_text(
                    f'---\ntitle: "{category} fixture {i:02}"\ndate: 2026-01-01T12:{i:02}:00Z\n'
                    f'categories: ["{category.title()}"]\n---\nOffline category fixture.\n')
        (cls.site / 'hugo.toml').write_text('''baseURL="https://fixture.invalid/"
title="Uutistenlukija"
languageCode="fi"
timeZone="UTC"
disableKinds=["RSS","sitemap","robotsTXT"]
[taxonomies]
category="categories"
tag="tags"
''')
        result = subprocess.run([HUGO, '--source', str(cls.site), '--destination', str(cls.site / 'public'), '--cacheDir', str(cls.site / 'cache'), '--noBuildLock'], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        if sum(p.stat().st_size for p in cls.site.rglob('*') if p.is_file()) > 12 * 1024 * 1024:
            raise AssertionError('Bounded fixture exceeded 12 MiB')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def page(self, category, page=1):
        route = 'kategoriat/talous' if category == 'talous' else 'categories/' + category
        if page != 1:
            route += f'/page/{page}'
        return unescape((self.site / 'public' / route / 'index.html').read_text())

    def test_every_category_has_truthful_order_frequency_and_instant(self):
        for category in self.categories:
            with self.subTest(category=category):
                html = self.page(category)
                header = html.split('<header class="portal-list-header">', 1)[1].split('</header>', 1)[0]
                self.assertIn('Jutut julkaisuajan mukaan. Aiheiden julkaisutiheys vaihtelee.', header)
                self.assertIn('Uusin tämän sivun juttu:', header)
                self.assertIn('2026-01-01T14:', header)
                self.assertIn('Suomen aikaa', header)
                self.assertIn(f'{category} fixture', html)

    def test_old_culture_archive_does_not_claim_current_debate(self):
        html = self.page('kulttuuri')
        header = html.split('<header class="portal-list-header">', 1)[1].split('</header>', 1)[0]
        self.assertNotIn('juuri nyt', header.casefold())
        self.assertNotIn('puhutuimmat', header.casefold())
        self.assertIn('kulttuuri', header.casefold())

    def test_second_archive_page_has_own_latest_instant(self):
        first = self.page('kulttuuri')
        second = self.page('kulttuuri', 2)
        def instant(html):
            header = html.split('<header class="portal-list-header">', 1)[1].split('</header>', 1)[0]
            match = re.search(r'<time[^>]*datetime="([^"]+)"', header)
            self.assertIsNotNone(match)
            assert match is not None
            return match.group(1)
        self.assertGreater(instant(first), instant(second))
        self.assertIn('Uusin tämän sivun juttu:', second)
        self.assertIn('kulttuuri fixture', second)


if __name__ == '__main__':
    unittest.main()

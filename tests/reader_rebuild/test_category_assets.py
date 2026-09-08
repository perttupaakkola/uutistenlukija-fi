"""R6: bounded real Hugo render; no production content, pipeline or network.

HUGO_BIN selects the installed Hugo. UL_CATEGORY_TEST_SCRATCH optionally retains
one fixture for local browser resource checks (otherwise a TemporaryDirectory).
"""
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
HUGO = os.environ.get('HUGO_BIN', '/home/pertt/.openclaw/workspace/bin/hugo')
CATEGORIES = ('kotimaa', 'talous', 'ulkomaat', 'kulttuuri', 'teknologia', 'tiede', 'urheilu')
GENERIC_ALT = 'Kuvituskuva – ei kuva uutisen tapahtumasta'


def display(cat):
    return f'/images/illustrations/{cat}.' + ('jpg' if cat == 'kotimaa' else 'webp')


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.images, self.preloads, self.mapping = [], [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img':
            self.images.append(attrs)
        if tag == 'link' and attrs.get('as') == 'image':
            self.preloads.append(attrs)
        if 'data-mapped' in attrs:
            self.mapping.append(attrs['data-mapped'])


def build_fixture(site):
    # Actual base, production layouts, theme and config; only content is synthetic.
    shutil.copytree(ROOT / 'layouts', site / 'layouts')
    shutil.copytree(ROOT / 'themes', site / 'themes')
    shutil.copytree(ROOT / 'assets', site / 'assets')
    shutil.copytree(ROOT / 'data', site / 'data')
    shutil.copytree(ROOT / 'static/images/categories', site / 'static/images/categories')
    shutil.copy(ROOT / 'static/images/logo.png', site / 'static/images/logo.png')
    shutil.copytree(ROOT / 'static/js', site / 'static/js', dirs_exist_ok=True)
    (site / 'static/css').mkdir(exist_ok=True)
    shutil.copy(ROOT / 'assets/css/portal-overhaul.css', site / 'static/css/portal-overhaul.css')
    (site / 'hugo.toml').write_text((ROOT / 'hugo.toml').read_text() + '\n[build]\nnoJSConfigInAssets = true\n')
    posts = site / 'content/posts'
    posts.mkdir(parents=True)
    # Explicit generic, absent image, thumbnail-only generic; all seven categories.
    for cat in CATEGORIES:
        for index in range(3):
            params = {'title': f'Fixture {cat} {index}', 'date': f'2026-01-01T12:0{index}:00Z',
                      'categories': [cat.title()], 'tags': [cat], 'description': 'Offline category fixture',
                      'image_alt': 'Not an actual depiction of this headline'}
            if index == 2:
                params.update(image=f'/images/categories/{cat}.jpg?v=fixture#image',
                              image_credit='Retained fixture credit', image_source_url='https://example.invalid/credit',
                              image_caption='Kuvituskuva')
            elif index == 0:
                params.update(image_thumb=f'/images/categories/{cat}.jpg')
            (posts / f'{cat}-{index}.md').write_text('---\n' + json.dumps(params) + '\n---\nFixture body.\n')
    # Exercise section list as well as taxonomy/category; a fixture-only explicit
    # caller also covers retained alternate image partials, not a rewritten mock.
    components = site / 'layouts/_default/component-cases.html'
    components.write_text('''{{ define "main" }}
{{ range where .Site.RegularPages "Section" "posts" }}
  {{ if .Params.image }}{{ partial "taxonomy-featured.html" . }}{{ end }}
{{ end }}
{{ $posts := (where .Site.RegularPages "Section" "posts").ByDate.Reverse }}
{{ partial "hero-cluster.html" (dict "lead" (index $posts 0) "followups" (first 3 (after 1 $posts))) }}
{{ partial "card-image.html" (dict "img" "/missing-fixture.jpg" "fallback" "/images/categories/talous.jpg" "eager" true) }}
{{ range .Params.urls }}<i data-mapped="{{ partial "display-image.html" . }}"></i>{{ end }}
{{ end }}''')
    urls = [f'/images/categories/{cat}.jpg?v=x#fragment' for cat in CATEGORIES]
    urls += ['/images/categories/unknown.jpg', '/images/categories/talous.jpg.bak',
             '/images/articles/talous.jpg', 'https://example.invalid/images/categories/talous.jpg',
             '//example.invalid/images/categories/kotimaa.jpg',
             '/proxy?url=/images/categories/talous.jpg', '/images/categories/talous.svg', '']
    (site / 'content/component-cases.md').write_text('---\n' + json.dumps({'title': 'Component cases', 'layout': 'component-cases', 'urls': urls}) + '\n---\n')
    proc = subprocess.run([HUGO, '--source', str(site), '--destination', str(site / 'public'),
                           '--baseURL', 'http://127.0.0.1:18776/', '--noBuildLock',
                           '--cacheDir', str(site / 'cache')], capture_output=True, text=True, timeout=60)
    (site / 'hugo-output.txt').write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise AssertionError(proc.stdout + proc.stderr)
    size = sum(p.stat().st_size for p in site.rglob('*') if p.is_file())
    if size > 32 * 1024 * 1024:
        raise AssertionError(f'Fixture exceeded 32 MiB budget: {size}')
    return urls


class CategoryAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = os.environ.get('UL_CATEGORY_TEST_SCRATCH')
        cls.tmp = None
        if scratch:
            cls.site = Path(scratch)
            cls.site.mkdir(parents=True, exist_ok=False)
        else:
            cls.tmp = tempfile.TemporaryDirectory(prefix='ul-category-assets-')
            cls.site = Path(cls.tmp.name)
        cls.urls = build_fixture(cls.site)
        print('Fixture:', cls.site)

    @classmethod
    def tearDownClass(cls):
        if cls.tmp:
            cls.tmp.cleanup()

    def page(self, route):
        return (self.site / 'public' / route / 'index.html').read_text()

    def test_exact_local_mapping_preserves_suffix_not_external_or_near_matches(self):
        expected = [display(cat) + '?v=x#fragment' for cat in CATEGORIES] + self.urls[len(CATEGORIES):]
        self.assertEqual(Elements(self.page('component-cases')).mapping, expected)

    def test_every_category_feature_and_feed_really_use_derivatives(self):
        for cat in CATEGORIES:
            with self.subTest(category=cat):
                html = self.page('categories/' + cat)
                self.assertIn('portal-list-feature', html)
                self.assertIn('portal-feed-item__thumb', html)
                images = [img for img in Elements(html).images if img.get('class') != 'portal-logo__image']
                self.assertEqual(len(images), 3)
                self.assertTrue(all(urlsplit(img['src']).path == display(cat) for img in images), images)
                self.assertTrue(all(img['alt'] == GENERIC_ALT for img in images), images)

    def test_sections_tags_alternate_partials_and_fallbacks(self):
        for route in ['posts', 'component-cases'] + ['tags/' + cat for cat in CATEGORIES]:
            with self.subTest(route=route):
                images = Elements(self.page(route)).images
                self.assertGreater(len(images), 0)
                for img in images:
                    self.assertFalse(img['src'].startswith('/images/categories/'), img)
                    self.assertNotIn('/images/categories/', img.get('onerror', ''))
                    if '/images/illustrations/' in img['src']:
                        self.assertEqual(img['alt'], GENERIC_ALT)

    def test_article_hero_preload_credit_and_no_image_fallback(self):
        for cat in CATEGORIES:
            for index in (1, 2):
                with self.subTest(category=cat, index=index):
                    html = self.page(f'posts/{cat}-{index}')
                    elements = Elements(html)
                    hero = next(img for img in elements.images if img.get('class') == 'article-hero-img')
                    self.assertEqual(urlsplit(hero['src']).path, display(cat))
                    self.assertEqual(hero['alt'], GENERIC_ALT)
                    self.assertNotIn('/images/categories/', hero['onerror'])
                    self.assertIn('Kuvituskuva', html)
                    if index == 2:
                        self.assertEqual(elements.preloads[0]['href'], hero['src'])
                        self.assertIn('Retained fixture credit', html)
                        self.assertIn('https://example.invalid/credit', html)

    def test_rendered_error_handlers_recover_to_display_urls(self):
        # Execute the actual HTML-decoded handlers, including Hugo's JS escaping.
        handlers = []
        for route in ['posts', 'component-cases'] + ['categories/' + cat for cat in CATEGORIES] + ['posts/' + cat + '-2' for cat in CATEGORIES]:
            handlers += [img['onerror'] for img in Elements(self.page(route)).images if 'onerror' in img]
        script = '''const handlers = JSON.parse(process.argv[1]);
const urls = handlers.map(handler => {
  const image = {dataset: {}, classList: {add(){}}, closest(){return {classList:{add(){}}}}};
  Function(handler).call(image);
  return image.src;
});
console.log(JSON.stringify(urls));'''
        proc = subprocess.run(['node', '-e', script, json.dumps(handlers)], capture_output=True, text=True, timeout=10, check=True)
        urls = json.loads(proc.stdout)
        self.assertEqual(len(urls), len(handlers))
        self.assertGreater(len(urls), 20)
        self.assertTrue(all(urlsplit(url).path in {display(cat) for cat in CATEGORIES} for url in urls), urls)

    def test_derivative_bytes_format_pixels_and_original_hashes(self):
        from PIL import Image
        manifest = json.loads((ROOT / 'tests/reader_rebuild/category-assets.json').read_text())
        self.assertEqual(set(row['category'] for row in manifest['assets']), set(CATEGORIES) - {'kotimaa'})
        for row in manifest['assets']:
            with self.subTest(category=row['category']):
                original = ROOT / row['original']['path']
                result = ROOT / row['result']['path']
                for key, path in [('original', original), ('result', result)]:
                    self.assertEqual(path.stat().st_size, row[key]['bytes'])
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row[key]['sha256'])
                self.assertLess(result.stat().st_size, 120_000)
                self.assertLess(result.stat().st_size, original.stat().st_size // 4)
                with Image.open(original) as source:
                    source = source.convert('RGB')
                    source.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    encoded = io.BytesIO()
                    source.save(encoded, format='WEBP', quality=80, method=6)
                    # Compare decoded pixels: differing libwebp versions needn't
                    # produce the same encoder bytes. Checked-in bytes are hashed.
                    with Image.open(result) as actual, Image.open(io.BytesIO(encoded.getvalue())) as rebuilt:
                        self.assertEqual(actual.format, 'WEBP')
                        self.assertEqual(actual.size, source.size)
                        self.assertEqual(actual.tobytes(), rebuilt.tobytes())


if __name__ == '__main__':
    unittest.main()

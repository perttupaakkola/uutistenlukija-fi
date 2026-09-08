"""Offline reader fixtures only: no pipeline imports, network, JS or live builds.

Run with PYTHONDONTWRITEBYTECODE=1. Hugo renders fewer than 30 fixture content inputs
under the lane scratch directory, never the repository's production content.
"""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from html import unescape

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(os.environ.get('UL_READER_TEST_SCRATCH', str(Path(tempfile.gettempdir()) / 'uutistenlukija-reader-tests')))
HUGO = os.environ.get('HUGO_BIN', '/home/pertt/.openclaw/workspace/bin/hugo')
ARTICLES = [
    '2026-09-07-kysely-lahes-puolet-ajaa-renkaat-lain-edellyttamalle-minimit',
    '2026-09-07-hallinto-oikeuksien-valituksiin-valmistellaan-etukateismaksu',
    '2026-09-02-thln-jatevesitutkimus-kokaiinin-kaytto-kasvoi-lahes-koko-suo',
]

class TimeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nested = False
    def handle_starttag(self, tag, attrs):
        if tag == 'time':
            self.nested |= self.depth > 0
            self.depth += 1
    def handle_endtag(self, tag):
        if tag == 'time':
            self.depth -= 1

class ReaderFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(prefix='fixture-', dir=SCRATCH)
        cls.site = Path(cls.tmp.name)
        shutil.copytree(ROOT / 'layouts', cls.site / 'layouts')
        # 404 asset is local. No provider/module/theme downloads or production assets.
        (cls.site / 'assets/css').mkdir(parents=True)
        shutil.copy(ROOT / 'assets/css/404.css', cls.site / 'assets/css/404.css')
        (cls.site / 'hugo.toml').write_text('''baseURL = "https://fixture.invalid/"
title = "Uutistenlukija"
languageCode = "fi"
timeZone = "UTC"
disableKinds = ["RSS", "sitemap", "robotsTXT"]
[params]
ga4_id = "G-FIXTURE"
[markup.goldmark.renderer]
unsafe = true
[taxonomies]
category = "categories"
tag = "tags"
''')
        (cls.site / 'content/posts').mkdir(parents=True)
        for slug in ARTICLES:
            shutil.copy(ROOT / 'content/posts' / (slug + '.md'), cls.site / 'content/posts')
        for i in range(16):
            (cls.site / f'content/posts/latest-{i:02}.md').write_text(f'''---
title: "Fixture latest {i:02}"
date: 2026-09-07T10:{59-i:02}:00Z
categories: [Kotimaa]
description: "Summary {i:02}"
author: "Toimitus"
image: "/images/categories/kotimaa.jpg"
image_alt: "An event this image does not depict"
---
Fixture article text.
''')
        (cls.site / 'content/posts/escaping.md').write_text('---\n' + json.dumps({'title': 'A "quote" </script><script>alert(1)</script> & more', 'date': '2026-01-01', 'categories': ['Kotimaa']}) + '\n---\nFixture body.\n')
        shutil.copy(ROOT / 'content/evasteet.md', cls.site / 'content/evasteet.md')
        (cls.site / 'content/information-fixture.md').write_text('---\ntitle: Information fixture\nauthor: Fixture author\n---\nInformational fixture body, not a news article.\n')
        shutil.copytree(ROOT / 'content/tilaa', cls.site / 'content/tilaa')
        shutil.copytree(ROOT / 'content/uutiskirje', cls.site / 'content/uutiskirje')
        shutil.copytree(ROOT / 'content/oppaat', cls.site / 'content/oppaat')
        # Exercise actual shared partials across DST and published/update distinction.
        (cls.site / 'content/time-cases.md').write_text('---\ntitle: Time cases\nlayout: time-cases\n---\n')
        (cls.site / 'layouts/_default/time-cases.html').write_text('''{{ define "main" }}
{{ range slice "2026-01-15T12:00:00Z" "2026-07-15T12:00:00Z" "2026-03-29T00:30:00Z" "2026-03-29T01:30:00Z" "2026-10-25T00:30:00Z" "2026-10-25T01:30:00Z" "2026-09-02T21:35:00Z" }}{{ partial "absolute-date.html" . }}{{ end }}
{{ partial "relative-date.html" (dict "Date" (time.AsTime "2026-07-01T12:00:00Z") "Params" (dict "published_at" "2026-01-01T12:00:00Z" "updated_at" "2026-08-01T12:00:00Z")) }}
{{ partial "image-alt.html" (dict "Title" "Event" "Params" (dict "image" "/images/articles/real.jpg" "image_alt" "Actual image caption")) }}
{{ end }}''')
        result = subprocess.run([HUGO, '--source', str(cls.site), '--destination', str(cls.site / 'public'), '--cacheDir', str(cls.site / 'cache'), '--noBuildLock'], capture_output=True, text=True, timeout=60)
        (SCRATCH / 'hugo-fixture-output.txt').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.output = cls.site / 'public'
        packet = SCRATCH / 'rendered'
        packet.mkdir(exist_ok=True)
        for route, name in [('', 'home'), ('uutiskirje', 'newsletter'), ('posts/' + ARTICLES[0], 'tyre'), ('posts/' + ARTICLES[1], 'speaker'), ('posts/' + ARTICLES[2], 'sampling'), ('oppaat/kauppojen-aukioloajat', 'guide'), ('time-cases', 'times')]:
            shutil.copy(cls.output / route / 'index.html', packet / (name + '.html'))
        if sum(p.stat().st_size for p in cls.site.rglob('*') if p.is_file()) > 8 * 1024 * 1024:
            raise AssertionError('Fixture exceeded 8 MiB budget')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, route):
        return unescape((self.output / route / 'index.html').read_text())

    def test_latest_includes_lead_and_is_chronological(self):
        html = self.page('')
        river = html.split('class="portal-river"', 1)[1]
        titles = re.findall(r'<h3><a[^>]*>(Fixture latest \d+)</a></h3>', river)
        self.assertEqual(titles, [f'Fixture latest {i:02}' for i in range(12)])
        self.assertIn('Summary 00', html.split('class="portal-day-digest"', 1)[1])
        for false_label in ['Luetuimmat', 'Mitä tänään', 'Päivän pääuutiset', 'Löydä lisää']:
            self.assertNotIn(false_label, html)

    def test_newsletter_renders_content_without_unproved_signup(self):
        html = self.page('uutiskirje')
        main = html.split('<main', 1)[1].split('</main>', 1)[0]
        self.assertIn('lähetysaikataulua ei ole vahvistettu', main)
        self.assertIn('Aiemmat tilaukset säilyvät', main)
        self.assertNotIn('/api/subscribe', main)
        self.assertNotIn('ei ole vielä artikkeleita', main)
        self.assertNotIn('Kiitos tilauksesta', main)

    def test_real_rendered_tracking_contract(self):
        page = self.output / 'posts' / ARTICLES[0] / 'index.html'
        result = subprocess.run(['node', str(ROOT / 'scripts/test_event_tracking_consent.js'), str(page)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        escaped = self.output / 'posts/escaping/index.html'
        raw = escaped.read_text()
        script = next(s for s in re.findall(r'<script[^>]*>(.*?)</script>', raw, re.S) if 'visible_dwell_v2' in s)
        title = json.loads(re.search(r'var _articleTitle = (.*);', script).group(1))
        self.assertEqual(title, 'A "quote" </script><script>alert(1)</script> & more')
        self.assertNotIn('<script>alert(1)</script>', raw)
        result = subprocess.run(['node', str(ROOT / 'scripts/test_event_tracking_consent.js'), str(escaped)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_holiday_landing_has_no_unverified_promise(self):
        html = self.page('tilaa/pyhapaivien-kaupat-auki')
        main = html.split('<main', 1)[1].split('</main>', 1)[0]
        self.assertIn('lähetysaikataulua ei ole vahvistettu', main)
        self.assertNotIn('<form', main)
        self.assertNotIn('holiday_hours_signup_view', main)
        self.assertNotIn('Tilaa maksuton', html)
        cta = (ROOT / 'layouts/partials/holiday-hours-reminder-cta.html').read_text()
        self.assertNotIn('<script', cta)
        self.assertNotIn('Tilaa maksuton', cta)

    def test_informational_pages_do_not_inherit_news_claims(self):
        for route in ('evasteet', 'information-fixture'):
            with self.subTest(route=route):
                html = self.page(route)
                self.assertNotIn('Tämä juttu perustuu useisiin uutislähteisiin', html)
                self.assertNotIn('class="ai-disclosure"', html)
                self.assertNotIn('class="author-bio"', html)
        self.assertIn('Fixture author', self.page('information-fixture'))
        self.assertIn('Informational fixture body, not a news article.', self.page('information-fixture'))
        self.assertEqual((self.site/'content/evasteet.md').read_bytes(), (ROOT/'content/evasteet.md').read_bytes())
        news = self.page('posts/latest-00')
        self.assertIn('class="ai-disclosure"', news)
        self.assertIn('class="author-bio"', news)
        self.assertIn('Tämä juttu perustuu useisiin uutislähteisiin', news)
        self.assertIn('Ilmoita virheestä', news)

    def test_helsinki_absolute_dst_and_publication(self):
        html = self.page('time-cases')
        for stamp in ['2026-01-15T14:00:00+02:00', '2026-07-15T15:00:00+03:00', '2026-03-29T02:30:00+02:00', '2026-03-29T04:30:00+03:00', '2026-10-25T03:30:00+03:00', '2026-10-25T03:30:00+02:00', '2026-09-03T00:35:00+03:00', '2026-01-01T14:00:00+02:00']:
            self.assertTrue(stamp in html, stamp)
        self.assertIn('Suomen aikaa', html)
        self.assertIn('Actual image caption', html)
        self.assertNotIn('sitten', html)
        for path in self.output.rglob('*.html'):
            parser = TimeParser(); parser.feed(path.read_text())
            self.assertFalse(parser.nested, str(path))

    def test_article_schema_sources_and_disclosure(self):
        for slug in ARTICLES:
            html = self.page('posts/' + slug)
            schemas = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]
            types = [x.get('@type') for x in schemas]
            self.assertIn('NewsArticle', types)
            self.assertIn('BreadcrumbList', types)
            self.assertNotIn('FAQPage', types)
            article = next(x for x in schemas if x.get('@type') == 'NewsArticle')
            original = subprocess.run(['git', 'show', 'e5c8ff8c94448ec1499bf978f7190765efabaddb:content/posts/' + slug + '.md'], cwd=ROOT, capture_output=True, text=True, check=True).stdout
            current = (ROOT / 'content/posts' / (slug + '.md')).read_text()
            for key in ['date', 'source_url', 'source_name']:
                self.assertEqual(re.search(r'^'+key+r': (.+)$', original, re.M).group(1), re.search(r'^'+key+r': (.+)$', current, re.M).group(1))
            self.assertTrue(article['datePublished'].startswith(slug[:10]))
            self.assertIn('lähteisiin perustuvia', html)
            self.assertIn('Ilmoita virheestä', html)
            self.assertNotIn('kirjoittaa alkuperäisiä', html)
            self.assertIn('Kuvituskuva – ei kuva uutisen tapahtumasta', html)
            self.assertIn('/images/illustrations/kotimaa.jpg' if 'hallinto-' not in slug else '/images/illustrations/talous.webp', html)
        tyre = self.page('posts/' + ARTICLES[0])
        self.assertIn('49 prosenttia', tyre)
        self.assertIn('yhtä harvoin 24 prosenttia', tyre)
        self.assertNotIn('joten paineiden tarkistaminen', tyre)
        self.assertIn('autonrengasliitto.fi/ajankohtaista/', tyre)
        speaker = self.page('posts/' + ARTICLES[1])
        self.assertIn('Tiina Toivonen arvioi', speaker)
        self.assertNotIn('Rytkönen-Sandberg arvioi myös', speaker)
        self.assertIn('https://valtioneuvosto.fi/-/1410853/', speaker)
        sampling = self.page('posts/' + ARTICLES[2])
        self.assertIn('sunnuntaiaamun ja maanantaiaamun', sampling)
        self.assertIn('kaikkina viikonpäivinä', sampling)
        self.assertIn('https://thl.fi/-/', sampling)
        for html in [tyre, speaker, sampling]: self.assertIn('7.9.2026:', html)

    def test_guide_expiry_is_honest_and_route_accessible(self):
        guide = self.page('oppaat/kauppojen-aukioloajat')
        self.assertIn('noindex,follow', guide)
        self.assertIn('voimassaoloa ei ole jatkettu', guide)
        self.assertIn('S-kauppojen ja Lidlin', guide)
        self.assertIn('https://www.k-ryhma.fi/kauppojen-aukioloajat', guide)
        self.assertIn('Tarkistusta odottavat oppaat', self.page('oppaat'))

    def test_retained_illustration_is_reproducible(self):
        from PIL import Image
        original = ROOT / 'static/images/categories/kotimaa.jpg'
        optimized = ROOT / 'themes/uutistenlukija/static/images/illustrations/kotimaa.jpg'
        with Image.open(original) as image:
            image = image.convert('RGB')
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=78, optimize=True, progressive=True)
        self.assertEqual(output.getvalue(), optimized.read_bytes())
        self.assertLess(optimized.stat().st_size, original.stat().st_size // 4)

    def test_empty_and_single_homepage(self):
        with tempfile.TemporaryDirectory(prefix='small-', dir=SCRATCH) as directory:
            site = Path(directory)
            shutil.copytree(ROOT / 'layouts/partials', site / 'layouts/partials')
            shutil.copy(ROOT / 'layouts/index.html', site / 'layouts/index.html')
            (site / 'layouts/_default').mkdir()
            (site / 'layouts/_default/baseof.html').write_text('{{ block "main" . }}{{ end }}')
            (site / 'layouts/_default/single.html').write_text('{{ define "main" }}{{ .Content }}{{ end }}')
            (site / 'hugo.toml').write_text('baseURL="https://fixture.invalid/"\ndisableKinds=["RSS", "sitemap", "taxonomy", "term"]\n')
            (site / 'content/posts').mkdir(parents=True)
            for count in [0, 1]:
                if count:
                    (site / 'content/posts/only.md').write_text('---\ntitle: Only story\ndate: 2026-01-01\ncategories: [Kotimaa]\n---\nBody.\n')
                result = subprocess.run([HUGO, '--source', str(site), '--cacheDir', str(site / 'cache'), '--noBuildLock'], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                html = (site / 'public/index.html').read_text()
                self.assertEqual('Only story' in html, bool(count))

    def test_css_and_consumers(self):
        self.assertFalse((ROOT / 'layouts/partials/faq-article-schema.html').exists())
        for root in ['layouts', 'themes/uutistenlukija/layouts']:
            for path in (ROOT / root).rglob('*.html'):
                if path.name == 'event-tracking.html': continue
                text = path.read_text()
                self.assertNotIn('partial "faq-article-schema.html"', text)
                self.assertNotRegex(text, r'\d (?:min|h|tuntia|päivää) sitten')
        css = (ROOT / 'assets/css/portal-overhaul.css').read_text()
        for cls in ['portal-front-grid', 'portal-lead', 'portal-center-list', 'portal-right-rail', 'portal-day-digest', 'portal-river']:
            self.assertIn('.'+cls, css)
            self.assertIn(cls, (ROOT / 'layouts/index.html').read_text())

if __name__ == '__main__': unittest.main()

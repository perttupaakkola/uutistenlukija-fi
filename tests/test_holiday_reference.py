import ast
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from news_mvp import site, publish, holiday_reference as reference, utility_guides

NOW = datetime.fromisoformat('2026-10-09T12:00:00+03:00')

class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

class EmptyStore:
    def articles(self): return []
    def mark_rendered(self, ids): assert not ids

class HolidayReference(unittest.TestCase):
    def test_actual_render_metadata_discovery_primary_links_and_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(site, 'ClockDateTime', FixedClock):
                site.render_site(EmptyStore(), output, public=True)
            text = (output / 'syysloma-2026/index.html').read_text()
            self.assertIn('rel="canonical" href="https://uutistenlukija.fi/syysloma-2026/"', text)
            self.assertIn('href="/syysloma-2026/"', (output / 'oppaat/index.html').read_text())
            structured = [json.loads(raw) for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text)]
            self.assertEqual(structured[0]['@type'], 'WebPage')
            self.assertNotIn('NewsArticle', text)
            self.assertNotIn('datePublished', text)
            self.assertIn('<meta name="description"', text)
            for source in reference.SOURCES: self.assertIn('href="' + source + '"', text)
            for row in reference.ACTIVITIES: self.assertIn('<h2>' + row[0] + '</h2>', text)
            self.assertEqual(text.count('<dl>'), 6)
            self.assertNotIn('<table', text)
            for fact in ('13.–15.10.2026 klo 13–15', 'alle kouluikäiset aikuisen seurassa',
                         'myyjäiset klo 11–15, konsertit klo 15.30 ja 17, lyhtyopastus klo 18',
                         '12.–18.10.2026 joka päivä', '12.–16.10.2026', '12.10.2026 klo 10–12.40',
                         'enintään 25 henkilöä yhteen esittelyyn', 'Ei ennakkoilmoittautumista',
                         '16/8 euroa', 'Tiedot tarkistettu 9.10.2026'):
                self.assertIn(fact, text)
            self.assertNotIn('syysloma-2026', (output / 'rss.xml').read_text())
            # Reuse the normal publisher's actual finite sitemap block, not a substitute.
            tree = ast.parse(Path(publish.__file__).read_text())
            bundle = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'public_bundle')
            start = next(i for i,n in enumerate(bundle.body) if isinstance(n, ast.Assign) and any(isinstance(t,ast.Name) and t.id=='listing_paths' for t in n.targets))
            end = next(i for i in range(start,len(bundle.body)) if isinstance(bundle.body[i],ast.Expr) and isinstance(bundle.body[i].value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='sitemap.xml' for a in ast.walk(bundle.body[i].value)))
            code = compile(ast.Module(body=bundle.body[start:end+1],type_ignores=[]),publish.__file__,'exec')
            scope = dict(vars(publish), site=output, entries=[])
            exec(code,scope)
            sitemap = (output/'sitemap.xml').read_text()
            self.assertIn('<loc>https://uutistenlukija.fi/syysloma-2026/</loc>',sitemap)
            self.assertNotIn('<news:news>',sitemap)
            self.assertNotIn('<lastmod>',sitemap)
            (output/'syysloma-2026/index.html').write_text('<link rel="canonical" href="https://wrong.invalid/">')
            scope['entries'] = []
            exec(code,scope)
            self.assertNotIn('https://uutistenlukija.fi/syysloma-2026/',(output/'sitemap.xml').read_text())

    def test_exact_expiry_and_honest_dated_archive(self):
        before = datetime.fromisoformat('2026-10-18T20:58:59+00:00')
        after = datetime.fromisoformat('2026-10-18T20:59:00+00:00')
        self.assertFalse(reference.archived(before))
        self.assertTrue(reference.archived(after))
        active = reference.render(before,site.page,True)
        archive = reference.render(after,site.page,True)
        self.assertIn('vertaile maksutonta tekemistä</h1>',active)
        self.assertIn('Vuoden 2026 ohjelma on päättynyt',archive)
        self.assertIn('maksuttoman tekemisen arkisto</h1>',archive)
        self.assertIn('Tiedot tarkistettu 9.10.2026',archive)
        for text in (active,archive): self.assertIn('https://uutistenlukija.fi/syysloma-2026/',text)
        self.assertIn('arkisto',reference.discovery_html(after))
        with self.assertRaises(ValueError): reference.archived(datetime(2026,10,9))

    def test_private_noindex_and_existing_guide_contract_unchanged(self):
        text = reference.render(NOW,site.page,False)
        self.assertIn('noindex,nofollow',text)
        self.assertNotIn('rel="canonical"',text)
        self.assertNotIn('application/ld+json',text)
        self.assertEqual(utility_guides.GUIDE_PATHS,('/oppaat/kellojen-siirto-2026/','/oppaat/talvirenkaat-2026/','/oppaat/palovaroittimen-tarkistus/'))

    def test_holiday_travel_links_discover_existing_guides_without_new_claims(self):
        for now in (NOW, datetime.fromisoformat('2026-10-20T12:00:00+03:00')):
            text = reference.render(now, site.page, True)
            self.assertIn('href="/oppaat/talvirenkaat-2026/"', text)
            self.assertIn('href="/oppaat/#oppaat-ajokeli-title"', text)
            self.assertIn('href="/oppaat/">Kaikki oppaat', text)
            self.assertEqual(text.count('<dl>'), 6)
            self.assertIn('Tiedot tarkistettu 9.10.2026', text)

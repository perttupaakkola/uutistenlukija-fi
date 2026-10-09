import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from news_mvp import site, utility_guides as guides

class EmptyStore:
    def articles(self): return []
    def mark_rendered(self, ids): pass

class UtilityGuides(unittest.TestCase):
    def test_actual_renderer_routes_metadata_discovery_and_rss(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            site.render_site(EmptyStore(), output, public=True)
            contents = (output / 'oppaat/index.html').read_text()
            for path in guides.GUIDE_PATHS:
                with self.subTest(path=path):
                    text = (output / path.strip('/') / 'index.html').read_text()
                    self.assertIn('href="' + path + '"', contents)
                    self.assertIn('rel="canonical" href="' + guides.ORIGIN + path + '"', text)
                    self.assertIn('<meta name="description"', text)
                    data = [json.loads(raw) for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text)]
                    self.assertEqual(data[0]['@type'], 'WebPage')
                    self.assertEqual(data[0]['breadcrumb']['@type'], 'BreadcrumbList')
                    self.assertNotIn('NewsArticle', text)
                    self.assertNotIn('datePublished', text)
                    self.assertIn('/mvp-assets/images/logo.png', text)
                    self.assertIn('article-body', text)
                    self.assertIn('href="/oppaat/"', text)
                    self.assertGreater(len(re.sub('<[^>]+>', '', text.split('<article')[1].split('</article>')[0]).split()), 250)
            rss = (output / 'rss.xml').read_text()
            self.assertNotIn('<item>', rss)
            for path in guides.GUIDE_PATHS: self.assertNotIn(path, rss)

    def test_source_facts_and_crosslinks_are_bounded(self):
        now = datetime.fromisoformat('2026-10-09T10:00:00+03:00')
        items = guides.guides(now)
        for item in items:
            text = guides.render_guide(item, site.page, True)
            self.assertIn(item['source'], text)
            for path, _ in item['related']:
                self.assertIn('href="' + path + '"', text)
        self.assertIn('04.00 takaisin kello 03.00', items[0]['answer'])
        self.assertIn('enintään 3,5 tonnia', items[1]['answer'])
        self.assertIn('jos sää tai keli', items[1]['answer'])
        self.assertIn('3 mm', items[1]['answer'])
        self.assertIn('5 mm', items[1]['answer'])
        self.assertIn('ei kykyä havaita savua', items[2]['answer'])

    def test_clock_expiry_changes_answer_not_canonical(self):
        before = guides.guides(datetime.fromisoformat('2026-10-25T21:59:59+00:00'))[0]
        after = guides.guides(datetime.fromisoformat('2026-10-25T22:00:00+00:00'))[0]
        self.assertIn('siirretään', before['answer'])
        self.assertIn('siirrettiin', after['answer'])
        self.assertIn('ei seuraavaa', after['answer'])
        self.assertEqual(before['path'], after['path'])
        with self.assertRaises(ValueError): guides.guides(datetime(2026, 10, 9))

    def test_sitemap_uses_exact_canonical_routes_without_news_dates(self):
        import ast
        from news_mvp import publish
        tree = ast.parse(Path(publish.__file__).read_text())
        bundle = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'public_bundle')
        start = next(i for i, node in enumerate(bundle.body) if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'listing_paths' for t in node.targets))
        end = next(i for i in range(start, len(bundle.body)) if isinstance(bundle.body[i], ast.Expr) and isinstance(bundle.body[i].value, ast.Call) and any(isinstance(arg, ast.Constant) and 'sitemap.xml' == arg.value for arg in ast.walk(bundle.body[i].value)))
        code = compile(ast.Module(body=bundle.body[start:end + 1], type_ignores=[]), publish.__file__, 'exec')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            site.render_site(EmptyStore(), output, public=True)
            scope = dict(vars(publish), site=output, entries=[])
            exec(code, scope)
            sitemap = (output / 'sitemap.xml').read_text()
            for path in guides.GUIDE_PATHS:
                self.assertIn('<loc>' + guides.ORIGIN + path + '</loc>', sitemap)
            self.assertNotIn('<news:news>', sitemap)
            self.assertNotIn('<lastmod>', sitemap)
            (output / guides.GUIDE_PATHS[0].strip('/') / 'index.html').write_text('<link rel="canonical" href="https://wrong.invalid/">')
            scope['entries'] = []
            exec(code, scope)
            self.assertNotIn(guides.ORIGIN + guides.GUIDE_PATHS[0], (output / 'sitemap.xml').read_text())

    def test_private_pages_are_noindex(self):
        for guide in guides.guides(datetime.fromisoformat('2026-10-09T00:00:00+00:00')):
            text = guides.render_guide(guide, site.page, False)
            self.assertIn('noindex,nofollow', text)
            self.assertNotIn('rel="canonical"', text)
            self.assertNotIn('application/ld+json', text)

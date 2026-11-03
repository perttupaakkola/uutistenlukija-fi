import json
import re
import unittest, pathlib

from news_mvp import site


ROOT = pathlib.Path(__file__).resolve().parents[1]


class FrontGuidesRail(unittest.TestCase):
    def test_home_rail_links_seasonal_guides(self):
        s = pathlib.Path(__file__).resolve().parents[1].joinpath('news_mvp/site.py').read_text()
        for href in ('/oppaat/kellojen-siirto-2026/', '/oppaat/talvirenkaat-2026/', '/syysloma-2026/'):
            # The full guide archive keeps these routes even though the homepage rail is capped.
            self.assertIn(href, s)

    def test_home_rail_is_capped_and_links_to_all_guides(self):
        s = ROOT.joinpath('news_mvp/site.py').read_text()
        rail = re.search(
            r'<section class="portal-most-read portal-guides-rail".*?</section>', s, re.S
        ).group(0)
        self.assertEqual(rail.count('<li><a href='), 8)
        self.assertIn('href="/oppaat/">Kaikki oppaat</a>', rail)

    def test_three_desktop_rail_modules_stretch_to_one_row_height(self):
        css = ROOT.joinpath('static/css/portal-overhaul.css').read_text()
        rules = re.findall(r'\.portal-right-rail\s*\{([^}]*)\}', css)
        three_column_rules = [rule for rule in rules if 'repeat(3' in rule]
        self.assertEqual(len(three_column_rules), 2)
        for rule in three_column_rules:
            self.assertRegex(rule, r'align-items:\s*stretch')
            self.assertRegex(rule, r'grid-template-columns:\s*repeat\(3,\s*minmax\(0,\s*1fr\)\)')

    def test_long_finnish_headline_gets_visual_only_syllable_hints(self):
        title = 'Alueidenkäyttötavoitteisiin ehdotetaan energiatavoitetta & lisää'
        draft = {'title': title, 'summary': 'Tiivistelmä.', 'category': 'Kotimaa'}
        job = {'id': 'a' * 64, 'created_at': '2026-11-02T15:05:03+00:00'}
        item = (job, draft, '/uutiset/testi/', '2.11.2026', '', None, None)

        rendered = site.listing_page_html([item], 1, 1)
        self.assertIn('A&shy;lu&shy;ei&shy;den&shy;käyt&shy;tö&shy;ta&shy;voit&shy;tei&shy;siin', rendered)
        self.assertIn('&amp; lisää', rendered)
        self.assertNotIn('\u00ad', title)

        metadata = site.homepage_head_meta([item])
        self.assertNotIn('&shy;', metadata)
        self.assertNotIn('\u00ad', metadata)
        json_ld = [json.loads(block) for block in
                   re.findall(r'application/ld\+json">(.*?)</script>', metadata)]
        item_list = next(block for block in json_ld if block.get('@type') == 'ItemList')
        self.assertEqual(item_list['itemListElement'][0]['name'], title)
if __name__ == '__main__':
    unittest.main()

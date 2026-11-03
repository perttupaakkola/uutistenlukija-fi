import re
import unittest, pathlib
class FrontGuidesRail(unittest.TestCase):
    def test_home_rail_links_seasonal_guides(self):
        s = pathlib.Path(__file__).resolve().parents[1].joinpath('news_mvp/site.py').read_text()
        for href in ('/oppaat/kellojen-siirto-2026/', '/oppaat/talvirenkaat-2026/', '/syysloma-2026/'):
            # The full guide archive keeps these routes even though the homepage rail is capped.
            self.assertIn(href, s)

    def test_home_rail_is_capped_and_links_to_all_guides(self):
        s = pathlib.Path(__file__).resolve().parents[1].joinpath('news_mvp/site.py').read_text()
        rail = re.search(
            r'<section class="portal-most-read portal-guides-rail".*?</section>', s, re.S
        ).group(0)
        self.assertEqual(rail.count('<li><a href='), 8)
        self.assertIn('href="/oppaat/">Kaikki oppaat</a>', rail)
if __name__ == '__main__':
    unittest.main()

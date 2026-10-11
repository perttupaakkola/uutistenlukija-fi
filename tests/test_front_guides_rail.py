import unittest, pathlib
class FrontGuidesRail(unittest.TestCase):
    def test_home_rail_links_seasonal_guides(self):
        s = pathlib.Path(__file__).resolve().parents[1].joinpath('news_mvp/site.py').read_text()
        for href in ('/oppaat/kellojen-siirto-2026/', '/oppaat/talvirenkaat-2026/', '/syysloma-2026/'):
            self.assertIn('<li><a href="%s">' % href, s)
if __name__ == '__main__':
    unittest.main()

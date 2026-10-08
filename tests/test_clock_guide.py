import unittest
from datetime import datetime
from news_mvp import site

class ClockGuide(unittest.TestCase):
    def test_helsinki_and_year_boundaries_keep_section_and_contents_together(self):
        for iso, expected in [('2026-10-07T20:59:59+00:00', False),
                              ('2026-10-07T21:00:00+00:00', True),
                              ('2026-10-25T21:59:59+00:00', True),
                              ('2026-10-25T22:00:00+00:00', False),
                              ('2027-10-08T00:00:00+03:00', False)]:
            with self.subTest(iso=iso):
                html = site.clock_guide_html(datetime.fromisoformat(iso))
                self.assertEqual(bool(html), expected)
                nav = site.guides_contents_html(html)
                self.assertEqual('#oppaat-kellojen-siirto-title' in nav, expected)

    def test_naive_clock_refused(self):
        with self.assertRaises(ValueError):
            site.clock_guide_html(datetime(2026, 10, 8))

    def test_original_guidance_matches_statute_and_calendar(self):
        html = site.clock_guide_html(datetime.fromisoformat('2026-10-08T14:00:00+03:00'))
        self.assertIn('ei uusi uutisjuttu', html)
        self.assertIn('neljästä kolmeen', html)
        self.assertIn('https://www.finlex.fi/fi/lainsaadanto/2001/753', html)
        self.assertIn('25. lokakuuta 2026', html)
        self.assertEqual(max(day for day in range(1, 32) if datetime(2026, 10, day).weekday() == 6), 25)
        self.assertEqual(html.count('id="oppaat-kellojen-siirto-title"'), 1)

    def test_similar_id_does_not_create_clock_contents(self):
        for body in ('<h2 id="oppaat-kellojen-siirto-title-other">x</h2>',
                     '<h2 id="prefix-oppaat-kellojen-siirto-title">x</h2>'):
            self.assertNotIn('kellojen-siirto', site.guides_contents_html(body))

if __name__ == '__main__':
    unittest.main()

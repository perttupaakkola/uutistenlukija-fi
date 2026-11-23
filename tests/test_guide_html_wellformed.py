import re
import unittest
from datetime import datetime, timezone

from news_mvp import utility_guides


class GuideSectionHtmlWellFormed(unittest.TestCase):
    """A row pasted inside another row's link (23.11. Kauneimmat abroad) leaked raw HTML onto the page."""

    def test_no_markup_inside_attributes_and_balanced_items(self):
        now = datetime(2026, 11, 23, tzinfo=timezone.utc)
        for g in utility_guides.guides(now):
            for title, html in g.get('sections', ()):
                with self.subTest(guide=g.get('slug'), section=title[:40]):
                    for attr in re.findall(r'(?:href|src)="([^"]*)"', html):
                        self.assertNotIn('<', attr)
                    self.assertEqual(html.count('<li'), html.count('</li>'))
                    self.assertEqual(len(re.findall(r'<a\b', html)), html.count('</a>'))


if __name__ == '__main__':
    unittest.main()

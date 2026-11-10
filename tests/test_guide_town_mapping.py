import re
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from news_mvp import utility_guides as ug

# Guides whose dated town lists are still ahead; every named town entry must
# reach the rendered town sections. A missing _TOWN_LOCATIVES key silently
# dropped Lapua, Hanko and Ylivieska from the Christmas-opening list (10 Nov 2026).
UPCOMING = ('/oppaat/joulumarkkinat-2026/', '/oppaat/kauneimmat-joululaulut-2026/',
            '/oppaat/itsenaisyyspaiva-2026/', '/oppaat/lucian-paiva-2026/')


class GuideTownMappingTest(unittest.TestCase):
    def test_town_prefixed_entries_are_not_dropped(self):
        now = datetime(2026, 11, 10, 10, tzinfo=ZoneInfo('Europe/Helsinki'))
        for g in ug.guides(now):
            if g['path'] not in UPCOMING:
                continue
            for index in g.get('event_sections', ()):
                title, fragment = g['sections'][index]
                for raw in re.findall(r'<li>(.*?)(?:</li>|$)', fragment, re.S | re.I):
                    m = re.search(r'<strong>(.*?)</strong>', raw, re.S | re.I)
                    if not m:
                        continue
                    strong = ug._plain(m.group(1))
                    if re.match(r'(?:ma|ti|ke|to|pe|la|su)\b|\d', strong, re.I):
                        continue  # date-led rows inside a single-town section
                    with self.subTest(guide=g['path'], entry=strong):
                        self.assertIsNotNone(ug._town_for_item(title, strong))

    def test_christmas_openings_include_new_towns(self):
        now = datetime(2026, 11, 10, 10, tzinfo=ZoneInfo('Europe/Helsinki'))
        g = next(g for g in ug.guides(now) if g['path'] == '/oppaat/joulumarkkinat-2026/')
        towns = {e['town'] for e in ug.guide_events(g)}
        for town in ('Lapua', 'Hanko', 'Ylivieska', 'Iisalmi'):
            self.assertIn(town, towns)


if __name__ == '__main__':
    unittest.main()

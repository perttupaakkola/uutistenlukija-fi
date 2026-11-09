import unittest
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

from news_mvp import utility_guides as ug


class TownShareLinkTest(unittest.TestCase):
    def test_each_town_section_has_tagged_whatsapp_share(self):
        now = datetime(2026, 11, 9, 12, tzinfo=ZoneInfo('Europe/Helsinki'))
        guide = next(g for g in ug.guides(now) if g['path'] == '/oppaat/kauneimmat-joululaulut-2026/')
        events = ug.guide_events(guide)
        towns = list(dict.fromkeys(e['town'] for e in events))
        out = ug._event_guide_html(guide, events)
        self.assertEqual(out.count('class="guide-share"'), len(towns))
        self.assertIn('Lähetä Helsinki-lista WhatsAppissa', out)
        start = out.index('https://wa.me/?text=', out.index('id="helsinki"'))
        text = urllib.parse.unquote(out[start + len('https://wa.me/?text='):out.index('"', start)])
        self.assertIn('utm_source=whatsapp', text)
        self.assertIn('utm_campaign=kauneimmat-joululaulut-2026-helsinki#helsinki', text)
        self.assertTrue(text.startswith('Kauneimmat'))


if __name__ == '__main__':
    unittest.main()

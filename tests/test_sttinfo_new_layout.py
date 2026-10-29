"""STT Info changed its release page layout on 28 Oct 2026: the 'Tietoja julkaisijasta'
block became 'Lue lisää julkaisijalta <publisher>' and every release failed with
'Missing STT Info release or publisher block'. The fixture is a real captured page."""
import unittest
from datetime import datetime, timezone
from pathlib import Path

from news_mvp.official_additional import _sttinfo_parts

PAGE = (Path(__file__).parent / 'fixtures' / 'official_sources'
        / 'sttinfo_release_2026_layout.html').read_bytes()
URL = 'https://www.sttinfo.fi/tiedote/72458564/keski-suomen-pelastuslaitos-onnettomuustiedote?lang=fi'
NOW = datetime(2026, 10, 29, 18, 30, tzinfo=timezone.utc)


class STTInfoNewLayoutTests(unittest.TestCase):
    def test_real_2026_layout_parses_only_release_text(self):
        fields, _page, publisher, _reason = _sttinfo_parts(PAGE, URL, NOW)
        self.assertEqual(publisher, 'Keski-Suomen hyvinvointialue')
        self.assertEqual(fields['title'], 'Keski-Suomen pelastuslaitos onnettomuustiedote')
        text = fields['text']
        self.assertTrue(text.startswith('Kooste Keski-Suomen pelastuslaitoksen 29.10.2026'))
        self.assertIn('Jyväskylässä klo: 17:41', text)
        for leak in ('Kuvituskuva', 'Avainsanat', 'Yhteyshenkilöt', 'Lue lisää julkaisijalta',
                     'huumekuolemia', 'Puh:', 'Jaa'):
            self.assertNotIn(leak, text)

    def test_publisher_block_must_match_header_publisher(self):
        raw = PAGE.replace('Lue lisää julkaisijalta Keski-Suomen hyvinvointialue'.encode(),
                           'Lue lisää julkaisijalta Joku muu'.encode())
        with self.assertRaisesRegex(ValueError, 'publisher block'):
            _sttinfo_parts(raw, URL, NOW)


if __name__ == '__main__':
    unittest.main()

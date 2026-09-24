import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock

from news_mvp import frontpage as f, site

NOW = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
WEATHER = {'properties': {'meta': {'updated_at': NOW.isoformat(), 'units': {'air_temperature': 'celsius'}},
                         'timeseries': [{'time': NOW.isoformat(), 'data': {'instant': {'details': {'air_temperature': 8.5, 'wind_speed': 3}}}}]}}
MARKETS = b'<Envelope><Cube><Cube time="2026-09-24"><Cube currency="USD" rate="1.13"/><Cube currency="SEK" rate="11.26"/><Cube currency="GBP" rate="0.85"/></Cube></Cube></Envelope>'


class FrontpageData(unittest.TestCase):
    def test_snapshots_cache_source_times_and_survive_provider_failure(self):
        with tempfile.TemporaryDirectory() as state:
            reader = Mock(side_effect=lambda url: MARKETS if url == f.ECB_URL else json.dumps(WEATHER).encode())
            snapshot = f.refresh(state, NOW, reader)
            self.assertEqual(reader.call_count, 5)
            self.assertEqual(snapshot['markets']['date'], '2026-09-24')
            self.assertEqual(snapshot['helsinki']['updated_at'], NOW.isoformat())
            reader.reset_mock()
            self.assertEqual(f.refresh(state, NOW + timedelta(minutes=30), reader), snapshot)
            reader.assert_not_called()
            failed = Mock(side_effect=OSError('private upstream details'))
            self.assertEqual(f.refresh(state, NOW + timedelta(hours=7), failed), snapshot)
            self.assertNotIn('private', Path(state, 'frontpage-data.json').read_text())
            self.assertEqual(f.load(state), snapshot)

    def test_stale_future_and_unavailable_data_are_not_current(self):
        item = f.parse_weather(json.dumps(WEATHER))
        self.assertIsNotNone(f.current_weather(item, NOW))
        self.assertIsNone(f.current_weather(item, NOW + timedelta(hours=19)))
        self.assertIsNone(f.current_weather(item, NOW - timedelta(hours=1)))
        self.assertIsNone(f.current_weather({}, NOW))
        market = f.parse_markets(MARKETS)
        self.assertTrue(f.current_markets(market, NOW + timedelta(days=2)))
        self.assertFalse(f.current_markets(market, NOW + timedelta(days=8)))
        self.assertFalse(f.current_markets(market, NOW - timedelta(days=1)))
        text = f.modules({'helsinki': item, 'markets': market}, NOW + timedelta(days=8))
        self.assertIn('Sääennuste ei ole nyt saatavilla', text)
        self.assertIn('Valuuttakurssit eivät ole nyt saatavilla', text)
        self.assertNotIn('<dd>', text)

    def test_units_validation_and_no_script_injection(self):
        broken = json.loads(json.dumps(WEATHER))
        broken['properties']['meta']['units']['air_temperature'] = 'fahrenheit'
        with self.assertRaises(ValueError): f.parse_weather(json.dumps(broken))
        with self.assertRaises(ValueError): f.parse_markets(MARKETS.replace(b'1.13', b'NaN'))
        with self.assertRaises(ValueError): f.parse_markets(b'<Envelope/>')
        text = f.modules({'unexpected': '</script><script>alert(1)</script>'}, NOW)
        self.assertNotIn('<script>alert', text)
        self.assertIn('MET Norway', text)
        self.assertIn('1 euro (EUR)', text)
        self.assertIn('ei reaaliaikainen', text)
        self.assertIn('value="rovaniemi"', text)

    def test_readable_real_values_with_source_date(self):
        text = f.modules({'helsinki': f.parse_weather(json.dumps(WEATHER)), 'markets': f.parse_markets(MARKETS)}, NOW)
        self.assertIn('°C', text)
        self.assertIn('tuuli 3 m/s', text)
        self.assertIn('24.09.2026', text)
        self.assertIn('1.1300 USD', text)
        self.assertIn('11.2600 SEK', text)
        self.assertIn('0.8500 GBP', text)

    def test_audited_wrong_image_excluded_without_mutating_provenance(self):
        image = {'sha256': next(iter(site.EXCLUDED_IMAGES)), 'alt': 'municipality'}
        self.assertIsNone(site.display_image(image))
        self.assertEqual(image['alt'], 'municipality')
        sha = next(iter(site.IMAGE_ALT_CORRECTIONS))
        image = {'sha256': sha, 'alt': 'flight', 'credit': 'original credit'}
        shown = site.display_image(image)
        self.assertEqual(shown['credit'], image['credit'])
        self.assertNotEqual(shown['alt'], image['alt'])

    def test_feature_never_reaches_past_recent_eight_or_duplicates_stories(self):
        def row(n, image=False, age=0):
            return ({'created_at': (NOW-timedelta(hours=age)).isoformat()}, {}, '/'+str(n), '', '', {'sha256': str(n)} if image else None, '/image')
        rows = [row(0), row(1), row(2,True)]
        ordered = site.homepage_order(rows)
        self.assertEqual([r[2] for r in ordered], ['/2','/0','/1'])
        self.assertEqual([r[2] for r in rows], ['/0','/1','/2'])
        old = [row(0), row(1,True,72)]
        self.assertEqual(site.homepage_order(old), old)
        distant = [row(n) for n in range(9)]+[row(9,True)]
        self.assertEqual(site.homepage_order(distant), distant)

    def test_asset_urls_change_with_content_and_version_all_shell_dependencies(self):
        from unittest.mock import patch
        import re
        first = site.page('T', 'Body', '/')
        urls = re.findall(r'(?:src|href)="([^"]+\.(?:css|js)[^"]*)"', first)
        self.assertEqual(len(urls), 13)
        self.assertTrue(all(re.search(r'\?v=[0-9a-f]{12}$', url) for url in urls))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'static').mkdir()
            path = root/'static/style.css'
            path.write_text('before')
            with patch.object(site, 'ROOT', root):
                before = site.asset_url('mvp-assets', 'style.css')
                self.assertEqual(before, site.asset_url('mvp-assets', 'style.css'))
                path.write_text('after')
                after = site.asset_url('mvp-assets', 'style.css')
                self.assertNotEqual(before, after)
                self.assertEqual(before.split('?')[0], after.split('?')[0])

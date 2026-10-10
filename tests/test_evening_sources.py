import copy
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp import official


FIXTURES = Path(__file__).parent / 'fixtures' / 'official_sources'
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)


class EveningSources(unittest.TestCase):
    def setUp(self):
        self.config = {'discovery': {'family': 'finnish-official', 'max_candidates': 5}}
        self.policy = official.policy()
        self.police = official.POLICE_PROVIDERS

    def fixture(self, name):
        return (FIXTURES / name).read_bytes()

    def test_new_rss_providers_discover_fresh_captured_items(self):
        cases = {
            'ec-press': 'ec_press_feed.xml',
            'espoo': 'espoo_feed.xml',
            **{provider: 'police_feed.xml' for provider in self.police},
        }
        for provider, fixture in cases.items():
            with self.subTest(provider=provider), patch.object(
                    official, 'response', return_value=self.fixture(fixture)):
                rows = official.discover(self.config, NOW, provider_only=provider)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['provider'], provider)

    def test_police_feeds_rotate_three_at_a_time(self):
        subset = copy.deepcopy(self.policy)
        subset['providers'] = {name: subset['providers'][name] for name in self.police}
        fetched = []

        def response(url, hosts):
            fetched.append(url)
            return self.fixture('police_feed.xml')

        with patch.object(official, 'policy', return_value=subset), \
                patch.object(official, 'response', side_effect=response):
            official.discover(self.config, NOW)
            first = set(fetched)
            fetched.clear()
            official.discover(self.config, NOW + timedelta(minutes=15))
            second = set(fetched)
        self.assertEqual(len(first), 3)
        self.assertEqual(len(second), 3)
        self.assertFalse(first & second)

    def test_collection_and_rights_pins_for_every_new_provider(self):
        cases = {
            'ec-press': ('ec_rights.html', 'ec_press_article.json',
                         'https://ec.europa.eu/commission/presscorner/detail/fi/statement_26_2127'),
            'espoo': ('espoo_rights.html', 'espoo_article.html',
                      'https://www.espoo.fi/fi/uutiset/2026/10/nayttelykeskus-weegeen-etelainen-paaty-remonttiin'),
            **{provider: ('police_rights.html', 'police_article.html',
                          'https://poliisi.fi/-/kaksi-loukkaantui-liikenneonnettomuuksissa-oulussa')
               for provider in self.police},
        }
        with tempfile.TemporaryDirectory() as temp:
            for provider, (rights_name, article_name, url) in cases.items():
                rights = self.fixture(rights_name)
                article = self.fixture(article_name)
                with self.subTest(provider=provider):
                    permission = official.rights_text(rights, provider)
                    self.assertEqual(hashlib.sha256(permission.encode()).hexdigest(),
                                     self.policy['providers'][provider]['rights_text_sha256'])

                    def response(requested, hosts, allow_pdf=False, allow_json=False):
                        return rights if requested == self.policy['providers'][provider]['rights_url'] else article

                    recipe = {'family': 'finnish-official', 'provider': provider, 'url': url}
                    with patch.object(official, 'response', side_effect=response):
                        packet, receipt = official.collect(recipe, Path(temp) / provider, NOW)
                    self.assertEqual(packet['publication_basis']['provider'], provider)
                    self.assertEqual(packet['sources'][0]['url'], url)
                    self.assertGreaterEqual(len(packet['sources'][0]['text']), 200)
                    self.assertIsNone(packet['image'])
                    self.assertEqual(receipt['image_status'], 'explicit-text-only')

    def test_text_only_and_noncommercial_police_contract(self):
        for provider in self.police:
            spec = self.policy['providers'][provider]
            self.assertTrue(spec['text_only'])
            self.assertFalse(spec['commercial_use'])
            self.assertIn('kuvien käyttö edellyttää lupaa', spec['license'])

    def test_ec_press_is_cc_by_text_only_and_espoo_uses_own_terms(self):
        ec = self.policy['providers']['ec-press']
        self.assertTrue(ec['text_only'])
        self.assertIn('CC BY 4.0', ec['license'])
        espoo = self.policy['providers']['espoo']
        self.assertEqual(espoo['rights_url'],
                         'https://www.espoo.fi/fi/tietoa-espoofi-sivustosta')
        self.assertIn('vapaata julkaistavaksi', espoo['license'])

    def test_kuntaliitto_index_date_filters_stale_teasers(self):
        with patch.object(official, 'response', return_value=self.fixture('kuntaliitto_index.html')):
            rows = official.discover(self.config, NOW, provider_only='kuntaliitto')
        self.assertEqual([row['url'] for row in rows],
                         ['https://www.kuntaliitto.fi/ajankohtaista/2026/tuore-tiedote'])


if __name__ == '__main__':
    unittest.main()

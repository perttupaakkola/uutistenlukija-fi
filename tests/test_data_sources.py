import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp import data_sources
from news_mvp.authorization import proposed_policy_v2
from news_mvp.discovery import discover_mixed
from news_mvp.editorial import validate_packet
from news_mvp.release_contract import media
from news_mvp.store import database


FIXTURES = Path(__file__).parent/'fixtures/data_sources'
FMI_NOW = datetime(2026, 10, 10, 22, 0, tzinfo=timezone.utc)
TRAFFIC_NOW = datetime(2026, 10, 8, 19, 30, tzinfo=timezone.utc)


class DataSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmi = (FIXTURES/'fmi_warnings_atom.xml').read_bytes()
        cls.fmi_rights = (FIXTURES/'fmi_rights.html').read_bytes()
        cls.traffic = (FIXTURES/'fintraffic_messages.json').read_bytes()
        cls.traffic_rights = (FIXTURES/'fintraffic_rights.html').read_bytes()

    def setUp(self):
        # Most fixture tests exercise grouping with the captured yellow sea-wind group.
        flag = patch.object(data_sources, 'EXCLUDE_YELLOW_SEA_WIND', False)
        flag.start(); self.addCleanup(flag.stop)

    def test_yellow_sea_wind_alone_is_not_news(self):
        with patch.object(data_sources, 'EXCLUDE_YELLOW_SEA_WIND', True):
            self.assertEqual(data_sources._fmi_groups(self.fmi, FMI_NOW), [])

    def test_fmi_groups_one_update_and_drops_small_yellow_warnings(self):
        rows = data_sources._fmi_groups(self.fmi, FMI_NOW)
        self.assertEqual(len(rows), 1)
        key, records, areas = rows[0]
        self.assertEqual(key, 'fmi-warning:2026-10-11:seaWind:Moderate')
        self.assertEqual(len(records), 2, 'same day/type/severity must be one packet')
        self.assertGreaterEqual(len(areas), 3)
        fields = data_sources.source_fields(self.fmi, data_sources.FMI, key)
        self.assertIn('Selkämeren pohjoisosa', fields['text'])
        self.assertIn('11.10.2026 klo 08.00 (Suomen aika)', fields['text'])
        self.assertNotIn('Etelä-Pohjanmaa', fields['text'])
        self.assertGreaterEqual(len(fields['text']), 200)

    def test_fmi_story_key_survives_a_repeated_update(self):
        first = data_sources.discover_family
        with patch.object(data_sources, 'fetch_source', return_value=self.fmi):
            a = first(data_sources.FMI, FMI_NOW)
            b = first(data_sources.FMI, FMI_NOW)
        self.assertEqual([x['story_key'] for x in a], [x['story_key'] for x in b])
        with patch.object(data_sources, 'fetch_source', return_value=self.fmi):
            self.assertEqual(first(data_sources.FMI, FMI_NOW,
                                   excluded={a[0]['failure_url']}), [])
        with tempfile.TemporaryDirectory() as directory, database(directory) as store:
            store.record_collection_failure(a[0]['failure_url'], data_sources.FMI,
                                            'ValueError: isolated failure', 1.0)
            self.assertEqual(store.collection_failure_urls(2.0), {a[0]['failure_url']})

    def test_fintraffic_keeps_significant_main_road_closure_and_drops_routine_work(self):
        with patch.object(data_sources, 'fetch_source', return_value=self.traffic):
            rows = data_sources.discover_family(data_sources.FINTRAFFIC, TRAFFIC_NOW)
        self.assertEqual([row['story_key'] for row in rows],
                         ['fintraffic-traffic:GUID50472054'])
        fields = data_sources.source_fields(self.traffic, data_sources.FINTRAFFIC,
                                             rows[0]['story_key'])
        self.assertIn('Tie on suljettu liikenteeltä', fields['text'])
        self.assertIn('Tie 16', fields['title'])
        self.assertGreaterEqual(len(fields['text']), 200)

    def test_fintraffic_updates_keep_the_situation_story_key(self):
        data = json.loads(self.traffic)
        data['features'][0]['properties']['version'] = 2
        data['features'][0]['properties']['versionTime'] = '2026-10-08T19:05:00Z'
        updated = json.dumps(data, ensure_ascii=False).encode()
        with patch.object(data_sources, 'fetch_source', side_effect=[self.traffic, updated]):
            first = data_sources.discover_family(data_sources.FINTRAFFIC, TRAFFIC_NOW)
            second = data_sources.discover_family(data_sources.FINTRAFFIC, TRAFFIC_NOW)
        self.assertEqual(first[0]['story_key'], second[0]['story_key'])

    def test_exact_rights_sentences_and_pins(self):
        cases = ((data_sources.FMI, self.fmi_rights, data_sources.FMI_RIGHTS_SENTENCE),
                 (data_sources.FINTRAFFIC, self.traffic_rights,
                  data_sources.FINTRAFFIC_RIGHTS_SENTENCE))
        policy = data_sources._policy()['data_providers']
        for provider, raw, expected in cases:
            with self.subTest(provider=provider):
                self.assertEqual(data_sources.rights_text(raw, provider), expected)
                self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(),
                                 policy[provider]['rights_text_sha256'])
                with self.assertRaises(ValueError):
                    data_sources.rights_text(raw.replace(expected.encode(), b'changed'), provider)

    def test_collected_packets_validate_and_reconstruct_from_captured_bytes(self):
        cases = ((data_sources.FMI, self.fmi, self.fmi_rights, FMI_NOW),
                 (data_sources.FINTRAFFIC, self.traffic, self.traffic_rights, TRAFFIC_NOW))
        for provider, raw, rights, now in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                with patch.object(data_sources, 'fetch_source', return_value=raw):
                    recipe = data_sources.discover_family(provider, now)[0]
                with patch.object(data_sources, 'fetch_source', return_value=rights):
                    packet, _ = data_sources.collect(recipe, directory, now)
                self.assertIs(validate_packet(packet, now, 48), packet)
                intake = Path(directory)/'intake'/data_sources.digest(packet)
                self.assertTrue(data_sources.verify_intake(packet, intake))
                self.assertIsNone(packet['image'])
                self.assertEqual(packet['story_key'], recipe['story_key'])
                draft = {'title': packet['sources'][0]['title'][:60],
                         'summary': 'Rakenteisen lähteen tiedot on koottu uutisluonnokseen.',
                         'category': 'Kotimaa',
                         'paragraphs': [{'text': 'Tiedote koskee ilmoitettua aluetta.',
                                         'source_ids': ['A']},
                                        {'text': 'Ajat esitetään Suomen ajassa.',
                                         'source_ids': ['A']}], 'image': None}
                self.assertEqual(media(packet, draft)['text_only']['policy'], 'official-text-v1')

    def test_digitraffic_transport_sends_required_identity_and_gzip_headers(self):
        class Headers:
            def get(self, name, default=''):
                return 'gzip' if name == 'Content-Encoding' else default
            def get_content_type(self):
                return 'application/geo+json'
        class Response:
            url = data_sources._policy()['data_providers'][data_sources.FINTRAFFIC]['index']
            headers = Headers()
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return gzip.compress(self_raw)
        self_raw = self.traffic
        with patch.object(data_sources, 'urlopen', return_value=Response()) as opened:
            self.assertEqual(data_sources.fetch_source(data_sources.FINTRAFFIC), self.traffic)
        request = opened.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers['digitraffic-user'], 'Uutistenlukija/1.0')
        self.assertEqual(headers['accept-encoding'], 'gzip')

    def test_mixed_discovery_adds_exactly_two_bounded_fetches(self):
        config = {'discovery': {'family': 'news-reviewed-v2', 'max_candidates': 5},
                  'max_source_age_hours': 48}
        def response(provider, **kwargs):
            return self.fmi if provider == data_sources.FMI else self.traffic
        with patch('news_mvp.discovery.discover', return_value=[]), \
                patch('news_mvp.official.discover', return_value=[]), \
                patch.object(data_sources, 'fetch_source', side_effect=response) as fetch:
            discover_mixed(config, FMI_NOW)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         [data_sources.FMI, data_sources.FINTRAFFIC])

    def test_authorization_keeps_limits_and_registers_both_families(self):
        policy = proposed_policy_v2()
        self.assertEqual(policy['max_fetch_calls_per_tick'], 20)
        self.assertEqual(policy['max_source_age_hours'], 48)
        self.assertIn(data_sources.FMI, policy['source_families'])
        self.assertIn(data_sources.FINTRAFFIC, policy['source_families'])

    def test_store_allows_distinct_fmi_story_keys_on_the_official_warning_page(self):
        source = {'url': 'https://www.ilmatieteenlaitos.fi/varoitukset'}
        with tempfile.TemporaryDirectory() as directory, database(directory) as store:
            first = {'story_key': 'fmi-warning:2026-10-11:seaWind:Moderate',
                     'sources': [source]}
            second = {'story_key': 'fmi-warning:2026-10-12:seaWind:Moderate',
                      'sources': [source]}
            self.assertTrue(store.admit(first, FMI_NOW.isoformat())[1])
            self.assertTrue(store.admit(second, FMI_NOW.isoformat())[1])
            self.assertEqual(store.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 2)

    def test_existing_unique_source_url_schema_is_migrated_without_losing_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'jobs.sqlite'
            db = sqlite3.connect(path)
            db.execute('''CREATE TABLE jobs (
                id TEXT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE,
                source_url TEXT NOT NULL UNIQUE, packet TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, draft TEXT, review TEXT,
                adapter TEXT, created_at TEXT NOT NULL, error TEXT)''')
            db.execute("INSERT INTO jobs (id,story_key,source_url,packet,created_at) "
                       "VALUES ('old','url:https://example.test/a','https://example.test/a','{}','2026-10-10T00:00:00Z')")
            db.commit(); db.close()
            with database(directory) as store:
                self.assertEqual(store.db.execute('SELECT id FROM jobs').fetchone()[0], 'old')
                indexes = list(store.db.execute("PRAGMA index_list('jobs')"))
                unique_columns = [[row[2] for row in store.db.execute(
                    f"PRAGMA index_info('{index[1]}')")] for index in indexes if index[2]]
                self.assertNotIn(['source_url'], unique_columns)


if __name__ == '__main__':
    unittest.main()

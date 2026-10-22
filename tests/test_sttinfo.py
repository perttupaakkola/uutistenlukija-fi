import copy
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp import official
from news_mvp.authorization import proposed_policy_v2
from news_mvp.editorial import digest
from news_mvp.official_additional import (STTINFO_GRANT, _sttinfo_title_key,
                                          source_fields,
                                          sttinfo_publisher_allowed)
from news_mvp.release_contract import verify_intake
from news_mvp.site import source_list_html


FIXTURES = Path(__file__).parent / 'fixtures' / 'official_sources'
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)
URL = ('https://www.sttinfo.fi/tiedote/70000001/'
       'kelan-palveluihin-tulee-tarkistettu-aikataulu?lang=fi')


class STTInfoTests(unittest.TestCase):
    def setUp(self):
        self.spec = official.policy()['providers']['sttinfo']
        self.feed = (FIXTURES / 'sttinfo_feed.xml').read_bytes()
        self.page = (FIXTURES / 'sttinfo_release.html').read_bytes()
        self.rights = (FIXTURES / 'sttinfo_rights.html').read_bytes()
        self.config = {'discovery': {'family': 'finnish-official', 'max_candidates': 5}}

    def publisher_page(self, publisher):
        raw = self.page.decode()
        raw = raw.replace('Kela/FPA', publisher)
        return raw.encode()

    def title_page(self, title, extra=''):
        raw = self.page.decode().replace(
            'Kelan palveluihin tulee tarkistettu aikataulu', title)
        return raw.replace('</div>\n<h2>Tietoja julkaisijasta',
                           '<p>' + extra + '</p></div>\n<h2>Tietoja julkaisijasta').encode()

    def test_public_body_allowlist_keeps_explicit_and_deterministic_names(self):
        cases = ('Kela/FPA', 'Lupa- ja valvontavirasto',
                 'Keski-Suomen hyvinvointialue', 'Tampereen kaupunki')
        for publisher in cases:
            with self.subTest(publisher=publisher):
                fields = source_fields(self.publisher_page(publisher), 'sttinfo', URL, NOW)
                self.assertEqual(fields['publisher'], publisher + ' / STT Info')

    def test_parties_companies_associations_and_unknown_publishers_are_rejected(self):
        cases = ('Suomen Sosialidemokraattinen Puolue SDP', 'Esimerkki Oy',
                 'Esimerkki ry', 'Tuntematon Media')
        for publisher in cases:
            with self.subTest(publisher=publisher), self.assertRaises(ValueError):
                source_fields(self.publisher_page(publisher), 'sttinfo', URL, NOW)

    def test_non_news_titles_are_rejected(self):
        for title in ('Nostot medialle 12.–16.10.2026',
                      'Mediakutsu: julkisen palvelun esittely',
                      'Avoimet työpaikat: haemme asiantuntijaa'):
            with self.subTest(title=title), self.assertRaises(ValueError):
                source_fields(self.title_page(title), 'sttinfo', URL, NOW)

    def test_release_restrictions_fail_closed_in_body_or_page(self):
        restrictions = ('Tätä tiedotetta ei saa julkaista.', 'EMBARGO',
                        'Vain tiedotusvälineiden käyttöön.',
                        'Kaikki oikeudet pidätetään.',
                        'Julkaisuvapaa 11.10.2026 klo 09.00.')
        for restriction in restrictions:
            with self.subTest(restriction=restriction), self.assertRaises(ValueError):
                source_fields(self.title_page(
                    'Kelan palveluihin tulee tarkistettu aikataulu', restriction),
                    'sttinfo', URL, NOW)

    def test_exact_rights_sentence_and_hash_are_pinned(self):
        self.assertEqual(official.rights_text(self.rights, 'sttinfo'), STTINFO_GRANT)
        self.assertEqual(hashlib.sha256(STTINFO_GRANT.encode()).hexdigest(),
                         self.spec['rights_text_sha256'])
        with self.assertRaises(ValueError):
            official.rights_text(self.rights.replace(b'vapaasti', b'ehdollisesti'), 'sttinfo')

    def test_discovery_rotates_one_page_and_never_exceeds_two_fetches(self):
        calls = []
        def response(url, hosts):
            calls.append(url)
            return self.feed if url == self.spec['index'] else self.page
        with patch.object(official, 'response', side_effect=response):
            rows = official.discover(self.config, NOW, provider_only='sttinfo')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['publisher'], 'Kela/FPA')
        self.assertEqual(calls, [self.spec['index'], URL])
        self.assertLessEqual(len(calls), self.spec['max_fetches_per_tick'])

    def test_duplicate_existing_provider_url_or_similar_title_is_skipped(self):
        linked = self.page.replace(
            b'<h2>Tietoja julkaisijasta</h2>',
            b'<a href="https://www.kela.fi/original">Alkuperainen</a>'
            b'<h2>Tietoja julkaisijasta</h2>')
        for excluded, page in (({'https://www.kela.fi/original'}, linked),
                               ({'title:' + _sttinfo_title_key(
                                   'Kelan palveluihin tulee tarkistettu aikataulu!')}, self.page)):
            errors = []
            with self.subTest(excluded=excluded), patch.object(
                    official, 'response', side_effect=[self.feed, page]):
                rows = official.discover(self.config, NOW, excluded, errors,
                                         provider_only='sttinfo')
            self.assertEqual(rows, [])
            self.assertIn('duplicate', errors[0]['error'].lower())

    def test_unknown_publisher_skip_is_logged(self):
        errors = []
        with patch.object(official, 'response',
                          side_effect=[self.feed, self.publisher_page('Tuntematon Media')]):
            self.assertEqual(official.discover(
                self.config, NOW, errors=errors, provider_only='sttinfo'), [])
        self.assertIn('unknown publisher', errors[0]['error'].lower())

    def test_collection_attribution_text_only_and_strict_readback(self):
        recipe = {'family': 'finnish-official', 'provider': 'sttinfo',
                  'url': URL, '_source_raw': self.page}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(official, 'response', side_effect=AssertionError(
                    'cached release and pinned grant need no collection fetch')) as response:
                packet, receipt = official.collect(recipe, Path(temp), NOW)
            self.assertEqual(response.call_count, 0)
            self.assertEqual(packet['sources'][0]['publisher'], 'Kela/FPA / STT Info')
            self.assertEqual(self.spec['notice'], 'Lähde: <julkaisija> / STT Info')
            self.assertIn('Lähde: Kela/FPA / STT Info',
                          source_list_html(packet['sources']))
            self.assertIsNone(packet['image'])
            self.assertEqual(receipt['image_status'], 'explicit-text-only')
            verify_intake(packet, Path(temp))
            directory = Path(temp) / 'intake' / digest(packet)
            (directory / 'rights.html').write_bytes(
                self.rights.replace(b'vapaasti', b'ehdollisesti'))
            with self.assertRaises(ValueError):
                verify_intake(packet, Path(temp))

    def test_policy_registers_provider_and_changes_authorized_digest(self):
        self.assertIn('sttinfo', official.PROVIDER_ORDER)
        self.assertIn('sttinfo', official.ADDITIONAL_PROVIDERS)
        policy = proposed_policy_v2()
        self.assertIn('sttinfo', policy['source_families'])
        self.assertEqual(policy['text_only_policy_sha256'], digest(official.policy()))


if __name__ == '__main__':
    unittest.main()

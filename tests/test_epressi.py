import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp import official
from news_mvp.authorization import authorize, proposed_policy_v2
from news_mvp.discovery import discover_mixed
from news_mvp.editorial import digest
from news_mvp.official_additional import (EPRESSI_BASIS, epressi_feed_index,
                                          press_wire_publisher_allowed,
                                          press_wire_title_key, source_fields)
from news_mvp.release_contract import verify_intake
from news_mvp.site import reuse_rights_html, source_list_html


FIXTURES = Path(__file__).parent / 'fixtures' / 'official_sources'
NOW = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)
URL = ('https://www.epressi.com/tiedotteet/kaupungit-ja-kunnat/'
       'kaupunki-uudistaa-koulukuljetusten-aikatauluja.html')


class EPressiTests(unittest.TestCase):
    def setUp(self):
        self.spec = official.policy()['providers']['epressi']
        self.feed = (FIXTURES / 'epressi_feed.xml').read_bytes()
        self.page = (FIXTURES / 'epressi_release.html').read_bytes()
        self.rights = (FIXTURES / 'epressi_rights.txt').read_bytes().rstrip(b'\n')
        self.config = {'discovery': {'family': 'finnish-official', 'max_candidates': 5}}

    def publisher_page(self, publisher):
        return self.page.replace(b'Tampereen kaupunki', publisher.encode())

    def title_page(self, title, extra=''):
        raw = self.page.decode().replace(
            'Kaupunki uudistaa koulukuljetusten aikatauluja', title)
        return raw.replace('</div>\n</body>', '<p>' + extra + '</p></div>\n</body>').encode()

    def test_public_body_allowlist_keeps_city_wellbeing_county_and_shared_bodies(self):
        cases = ('Tampereen kaupunki', 'Pohjois-Karjalan hyvinvointialue',
                 'Savon koulutuskuntayhtymä', 'Pohjois-Pohjanmaan liitto')
        for publisher in cases:
            with self.subTest(publisher=publisher):
                fields = source_fields(self.publisher_page(publisher), 'epressi', URL, NOW)
                self.assertEqual(fields['publisher'], publisher + ' / ePressi')
                self.assertTrue(press_wire_publisher_allowed(publisher, self.spec)[0])

    def test_city_owned_transport_is_allowed_only_with_city_as_page_publisher(self):
        fields = source_fields(self.publisher_page(
            'Tampereen kaupunki, joukkoliikenne'), 'epressi', URL, NOW)
        self.assertEqual(fields['publisher'], 'Tampereen kaupunki, joukkoliikenne / ePressi')
        with self.assertRaisesRegex(ValueError, 'unknown publisher'):
            source_fields(self.publisher_page('Nysse'), 'epressi', URL, NOW)

    def test_companies_associations_parties_and_unknown_publishers_are_rejected(self):
        cases = ('Esimerkki Oy', 'Esimerkki ry', 'Suomen Esimerkkiliitto',
                 'Esimerkkipuolue', 'Tuntematon Media')
        for publisher in cases:
            with self.subTest(publisher=publisher), self.assertRaises(ValueError):
                source_fields(self.publisher_page(publisher), 'epressi', URL, NOW)

    def test_non_news_titles_are_rejected(self):
        cases = ('Mediakutsu: kaupungin palvelujen esittely',
                 'Nuoret voivat hakea kaupungin stipendejä',
                 'Maija Meikäläinen nimitetty hallintojohtajaksi',
                 'Uusi taidenäyttely avautuu museossa',
                 'Avoimet työpaikat: haemme asiantuntijaa')
        for title in cases:
            with self.subTest(title=title), self.assertRaisesRegex(ValueError, 'non-news'):
                source_fields(self.title_page(title), 'epressi', URL, NOW)

    def test_stock_exchange_category_and_url_are_never_candidates(self):
        stock = self.feed.replace(
            b'<category>Kaupungit ja kunnat</category>',
            b'<category>Porssitiedote</category>')
        calls = []
        with patch.object(official, 'response', side_effect=lambda url, hosts:
                          calls.append(url) or stock):
            self.assertEqual(official.discover(
                self.config, NOW, provider_only='epressi'), [])
        self.assertEqual(calls, [epressi_feed_index(self.spec, NOW)])
        bad = URL.replace('/kaupungit-ja-kunnat/', '/porssitiedotteet/')
        with self.assertRaises(ValueError):
            source_fields(self.page, 'epressi', bad, NOW)

    def test_culture_feed_rejects_art_event_even_when_title_omits_art_form(self):
        art = self.feed.replace(
            b'Kaupunki uudistaa koulukuljetusten aikatauluja',
            b'Artisti saapuu juhlistamaan kaupungin kesaa').replace(
                b'<category>Kaupungit ja kunnat</category>',
                b'<category>Kulttuuri ja taide</category>')
        with patch.object(official, 'response', return_value=art) as response:
            self.assertEqual(official.discover(
                self.config, NOW, provider_only='epressi'), [])
        self.assertEqual(response.call_count, 1)

    def test_release_restrictions_fail_closed(self):
        restrictions = ('Tätä tiedotetta ei saa julkaista.', 'EMBARGO',
                        'Vain tiedotusvälineiden käyttöön.',
                        'Kaikki oikeudet pidätetään.',
                        'Julkaisuvapaa 11.10.2026 klo 09.00.')
        for restriction in restrictions:
            with self.subTest(restriction=restriction), self.assertRaises(ValueError):
                source_fields(self.title_page(
                    'Kaupunki uudistaa koulukuljetusten aikatauluja', restriction),
                    'epressi', URL, NOW)

    def test_discovery_rotates_feeds_and_never_exceeds_two_fetches(self):
        for now in (NOW, NOW + timedelta(minutes=15)):
            calls = []
            def response(url, hosts):
                calls.append(url)
                return self.feed if url in self.spec['indexes'] else self.page
            with self.subTest(now=now), patch.object(official, 'response', side_effect=response):
                rows = official.discover(self.config, now, provider_only='epressi')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['publisher'], 'Tampereen kaupunki')
            self.assertEqual(calls, [epressi_feed_index(self.spec, now), URL])
            self.assertLessEqual(len(calls), self.spec['max_fetches_per_tick'])
        selected = [epressi_feed_index(self.spec, NOW + timedelta(minutes=15*i))
                    for i in range(4)]
        self.assertEqual(selected.count(self.spec['index']), 3)
        self.assertEqual(selected.count(self.spec['indexes'][1]), 1)

    def test_combined_discovery_stays_within_twenty_fetches(self):
        calls = []
        stt = official.policy()['providers']['sttinfo']
        stt_feed = (FIXTURES / 'sttinfo_feed.xml').read_bytes()
        stt_page = (FIXTURES / 'sttinfo_release.html').read_bytes()
        empty_feed = b'<rss><channel></channel></rss>'

        def official_response(url, hosts):
            calls.append(('official', url))
            if url == stt['index']:
                return stt_feed
            if url.startswith('https://www.sttinfo.fi/tiedote/'):
                return stt_page
            if url in self.spec['indexes']:
                return self.feed
            if url == URL:
                return self.page
            return empty_feed

        def nasa_fetch(url, hosts):
            calls.append(('nasa', url))
            return b'<html></html>', 'text/html', url

        def data_fetch(provider, rights=False):
            calls.append(('data', provider))
            return b''

        with patch.object(official, 'response', side_effect=official_response), \
                patch('news_mvp.discovery.fetch', side_effect=nasa_fetch), \
                patch('news_mvp.data_sources.fetch_source', side_effect=data_fetch):
            discover_mixed({'discovery': {'family': 'news-reviewed-v2',
                                          'max_candidates': 5}}, NOW)
        epressi_calls = [url for kind, url in calls
                         if kind == 'official' and 'epressi.com' in url]
        self.assertEqual(epressi_calls, [epressi_feed_index(self.spec, NOW), URL])
        self.assertLessEqual(len(calls), 20)

    def test_duplicate_provider_url_story_key_or_similar_title_is_rejected(self):
        linked = self.page.replace(
            b'</div>\n</body>',
            b'<a href="https://www.tampere.fi/original">Alkuperainen</a></div>\n</body>')
        cases = (({'https://www.tampere.fi/original'}, linked),
                 ({'url:https://www.tampere.fi/original'}, linked),
                 ({'title:' + press_wire_title_key(
                     'Kaupunki uudistaa koulukuljetusten aikatauluja!')}, self.page))
        for excluded, page in cases:
            errors = []
            with self.subTest(excluded=excluded), patch.object(
                    official, 'response', side_effect=[self.feed, page]):
                rows = official.discover(self.config, NOW, excluded, errors,
                                         provider_only='epressi')
            self.assertEqual(rows, [])
            self.assertIn('duplicate', errors[0]['error'].lower())

    def test_unknown_publisher_skip_is_logged(self):
        errors = []
        with patch.object(official, 'response', side_effect=[
                self.feed, self.publisher_page('Tuntematon Media')]):
            self.assertEqual(official.discover(
                self.config, NOW, errors=errors, provider_only='epressi'), [])
        self.assertIn('unknown publisher', errors[0]['error'].lower())

    def test_attribution_text_only_owner_pin_and_strict_readback(self):
        self.assertEqual(official.rights_text(self.rights, 'epressi'), EPRESSI_BASIS)
        self.assertEqual(self.spec['basis'], EPRESSI_BASIS)
        self.assertEqual(hashlib.sha256(EPRESSI_BASIS.encode()).hexdigest(),
                         self.spec['rights_text_sha256'])
        with self.assertRaises(ValueError):
            official.rights_text(self.rights + b' changed', 'epressi')
        recipe = {'family': 'finnish-official', 'provider': 'epressi',
                  'url': URL, '_source_raw': self.page}
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(official, 'response', side_effect=AssertionError(
                    'cached release and owner pin need no collection fetch')) as response:
                packet, receipt = official.collect(recipe, Path(temp), NOW)
            self.assertEqual(response.call_count, 0)
            self.assertEqual(packet['sources'][0]['publisher'],
                             'Tampereen kaupunki / ePressi')
            self.assertEqual(self.spec['notice'], 'Lähde: <julkaisija> / ePressi')
            self.assertIn('Lähde: Tampereen kaupunki / ePressi',
                          source_list_html(packet['sources']))
            self.assertEqual(reuse_rights_html(packet['sources']), '')
            self.assertIsNone(packet['image'])
            self.assertEqual(receipt['image_status'], 'explicit-text-only')
            verify_intake(packet, Path(temp))
            directory = Path(temp) / 'intake' / digest(packet)
            (directory / 'rights.html').write_bytes(self.rights + b' changed')
            with self.assertRaises(ValueError):
                verify_intake(packet, Path(temp))

    def test_policy_registration_and_writer_reviewer_rule(self):
        self.assertIn('epressi', official.PROVIDER_ORDER)
        self.assertIn('epressi', official.ADDITIONAL_PROVIDERS)
        policy = proposed_policy_v2()
        self.assertIn('epressi', policy['source_families'])
        self.assertEqual(policy['text_only_policy_sha256'], digest(official.policy()))
        for name in ('writer.md', 'reviewer.md'):
            prompt = (Path(__file__).parents[1] / 'prompts' / name).read_text()
            self.assertIn('STT Info- tai ePressi-tiedote', prompt)

    def test_exact_updated_policy_authorizes(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            accepted = proposed_policy_v2()
            accepted.update(enabled=True, approved_by='Hermes', review_ref='epressi-test')
            (state / 'steady-state-policy.json').write_text(json.dumps(accepted))
            config = {'enabled': True, 'authorization_mode': 'steady_state',
                      'state_dir': str(state), 'source_recipes': [],
                      'max_source_age_hours': 48,
                      'discovery': {'family': 'news-reviewed-v2', 'max_candidates': 5}}
            authorize(config)


if __name__ == '__main__':
    unittest.main()

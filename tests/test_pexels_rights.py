"""Real CC0 labels, exact-photo refusal, bounded transport and release binding."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

from news_mvp import imagery, pexels_rights as rights
from news_mvp.release_contract import stock_binding
from pexels_fixtures import photo_html

CANDIDATE = {'photo_id': '106152',
    'photo_page': 'https://www.pexels.com/photo/pile-of-gold-round-coins-106152/',
    'name': 'Pixabay', 'profile': 'https://www.pexels.com/@pixabay',
    'image_url': 'https://images.pexels.com/photos/106152/euro-coins-currency-money-106152.jpeg?w=940'}


class Response:
    status = 200
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, limit): return self.raw[:limit]


class ExactPexelsRights(unittest.TestCase):
    def evidence(self, code='CC0'):
        return rights.from_html(photo_html(CANDIDATE, code), CANDIDATE, 'pexels_https')

    def record(self, code='CC0'):
        candidate = {**CANDIDATE, 'license_evidence': self.evidence(code)}
        return imagery._pexels_record(candidate, 'euro coins', 'a'*64,
            'media/'+'a'*64+'.jpg', {'width': 940, 'height': 627, 'mode': 'RGB', 'variance': 1000.0},
            'Euro coins on a table.', '2026-09-26T12:00:00Z')

    def test_exact_cc0_and_pexels_grants_have_distinct_release_labels(self):
        for code, label, url in [('CC0', 'CC0 1.0', 'https://creativecommons.org/publicdomain/zero/1.0/'),
                                 ('Pexels', 'Pexels License', 'https://www.pexels.com/license/')]:
            with self.subTest(code=code):
                record = self.record(code)
                self.assertEqual((record['license'], record['license_url']), (label, url))
                self.assertEqual(stock_binding(record)['license_evidence']['license_code'], code)

    def test_another_photo_author_or_pixel_path_is_refused(self):
        for changes in ({'id': 999}, {'user': {'first_name': 'Other', 'slug': 'other'}},
                        {'image': {'large': 'https://images.pexels.com/photos/999/other.jpg'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rights.from_html(photo_html(CANDIDATE, **changes), CANDIDATE, 'pexels_https')

    def test_related_photo_grant_does_not_authorize_unknown_main_photo(self):
        raw = photo_html(CANDIDATE, 'Reserved').decode()
        value = json.loads(raw.split('>', 1)[1].split('</script>')[0])
        value['props']['pageProps']['related'] = {'id': 999, 'license': 'CC0'}
        with self.assertRaises(ValueError):
            rights.from_html(('<script id="__NEXT_DATA__">'+json.dumps(value)+'</script>').encode(), CANDIDATE, 'pexels_https')

    def test_duplicate_scripts_and_conflicting_json_keys_are_refused(self):
        raw = photo_html(CANDIDATE)
        for bad in (raw+raw, raw.replace(b'"license": "Pexels"', b'"license":"Pexels","license":"CC0"')):
            with self.subTest(raw=bad[:30]), self.assertRaises(ValueError):
                rights.from_html(bad, CANDIDATE, 'pexels_https')

    def test_unpublished_or_oversized_response_is_refused(self):
        for raw in (photo_html(CANDIDATE, published=False), b'x'*(rights.MAX_HTML+1)):
            with self.assertRaises(ValueError): rights.from_html(raw, CANDIDATE, 'pexels_https')

    def test_direct_block_uses_public_reader_without_credentials_and_caches_exact_bytes(self):
        raw = photo_html(CANDIDATE, 'CC0')
        denied = urllib.error.HTTPError(CANDIDATE['photo_page'], 403, 'blocked', {}, None)
        with tempfile.TemporaryDirectory() as state, mock.patch.object(imagery, '_open', side_effect=[denied, Response(raw)]) as opened:
            evidence = rights.fetch(CANDIDATE, state)
            self.assertEqual(evidence['transport'], 'jina_reader')
            self.assertEqual(evidence['response_sha256'], hashlib.sha256(raw).hexdigest())
            for call in opened.call_args_list:
                self.assertFalse(call.kwargs['credentialed'])
                self.assertIsNone(call.args[0].get_header('Authorization'))
            self.assertEqual(rights.fetch(CANDIDATE, state), evidence)
            self.assertEqual(opened.call_count, 2)
            self.assertEqual((Path(state)/'pexels-rights'/(evidence['response_sha256']+'.html')).read_bytes(), raw)

    def test_429_is_not_bypassed_through_reader(self):
        error = urllib.error.HTTPError(CANDIDATE['photo_page'], 429, 'limited', {}, None)
        with tempfile.TemporaryDirectory() as state, mock.patch.object(imagery, '_open', side_effect=error) as opened:
            self.assertIsNone(rights.fetch(CANDIDATE, state)); self.assertEqual(opened.call_count, 1)

    def test_successful_but_conflicting_response_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as state, mock.patch.object(imagery, '_open', return_value=Response(photo_html(CANDIDATE, 'Reserved'))) as opened:
            self.assertIsNone(rights.fetch(CANDIDATE, state)); self.assertEqual(opened.call_count, 1)

    def test_tampered_cached_body_requires_fresh_verification(self):
        raw = photo_html(CANDIDATE, 'CC0')
        with tempfile.TemporaryDirectory() as state, mock.patch.object(imagery, '_open', return_value=Response(raw)) as opened:
            evidence = rights.fetch(CANDIDATE, state)
            (Path(state)/'pexels-rights'/(evidence['response_sha256']+'.html')).write_bytes(b'changed')
            self.assertIsNone(rights.fetch(CANDIDATE, state))
            self.assertEqual(opened.call_count, 2)

    def test_release_refuses_changed_label_identity_or_missing_cc0_evidence(self):
        record = self.record()
        variants = []
        for key, value in [('license', 'Pexels License'), ('license_url', 'https://www.pexels.com/license/')]:
            variants.append({**record, key: value})
        wrong = deepcopy(record); wrong['license_evidence']['photo_id'] = '999'; variants.append(wrong)
        missing = deepcopy(record); missing.pop('license_evidence'); variants.append(missing)
        for value in variants:
            with self.assertRaises(ValueError): stock_binding(value)

    def test_new_record_cannot_silently_assume_provider_licence(self):
        with self.assertRaises(KeyError):
            imagery._pexels_record(CANDIDATE, 'coins', 'a'*64, 'media/a.jpg', {}, 'coins', '2026-09-26T12:00:00Z')


if __name__ == '__main__': unittest.main()

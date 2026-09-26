"""The ordinary provider tree must not confuse composition with relevance."""
import hashlib
import json
import tempfile
import unittest
from unittest import mock

from news_mvp import imagery
from news_mvp.release_contract import stock_binding
from test_image_decision_tree import structured_png
from pexels_fixtures import grant


DRAFT = {'title': 'STM: Lääkehoidon kustannusvastuun selvittely jatkuu',
    'summary': 'Lääkehoidon kustannusvastuuta selvitetään hyvinvointialueiden kanssa.',
    'category': 'Kotimaa', 'paragraphs': [
        {'text': 'STM selvittää lääkehoidon kustannusvastuuta ja lääkkeiden korvaushakemuksia.',
         'source_ids': ['A']}]}
DECISION = {'subject': 'lääkehoidon kustannusvastuun selvittely',
    'depictable_scene': 'Lääkepakkaukset ja laskin pöydällä.',
    'must_show': ['medicine blister packs', 'calculator'], 'must_avoid': ['faces'],
    'search_queries': ['medicine blister packs calculator', 'medicine blister packs',
                       'calculator medicine costs'], 'category': 'Kotimaa'}
PHOTO = {'id': 123456, 'url': 'https://www.pexels.com/photo/medicine-blisters-123456/',
    'photographer': 'Fixture Author', 'photographer_url': 'https://www.pexels.com/@fixture-author',
    'alt': 'Medicine blister packs on a table.',
    'src': {'large': 'https://images.pexels.com/photos/123456/fixture.jpg'}}


class StockArticleReview(unittest.TestCase):
    def setUp(self):
        self.raw = structured_png()
        self.description = 'Various blister packs containing pills and capsules on a wooden surface.'
        self.review = {'approved': True, 'alt_fi': 'Läpipainopakkauksia on puisella pöydällä.',
            'description': self.description, 'reason': 'Medicines directly illustrate treatment costs.',
            'no_people': True, 'image_sha256': hashlib.sha256(imagery._jpg(self.raw)).hexdigest(),
            'article_text_sha256': hashlib.sha256(json.dumps(DRAFT, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'model': 'fixture-review', 'reviewed_at': '2026-09-26T18:00:00+00:00'}

    def build(self, review, description=None, photo=None):
        with tempfile.TemporaryDirectory() as state, \
                mock.patch('news_mvp.pexels_rights.fetch', side_effect=grant), \
                mock.patch.object(imagery, 'provider_key', return_value='fixture-key'), \
                mock.patch.object(imagery, '_pexels_search', return_value={'photos': [photo or PHOTO]}), \
                mock.patch.object(imagery, '_get_bytes', return_value=self.raw), \
                mock.patch.object(imagery, 'describe', return_value=description or self.description), \
                mock.patch.object(imagery, 'review_pixels', return_value=review) as pixel_review, \
                mock.patch.object(imagery, 'fetch_unsplash', return_value=None), \
                mock.patch.object(imagery, 'fetch_wikimedia', return_value=None), \
                mock.patch.object(imagery, 'fetch_google', return_value=None), \
                mock.patch.object(imagery, 'generate', return_value=(None, '', None)) as generate:
            result = imagery.build_image(DRAFT, state, decision=DECISION, attempts=1)
            return result, pixel_review.call_count, generate.call_count

    def test_real_medicines_without_calculator_reach_exact_article_review(self):
        self.assertFalse(imagery.relevance_check(self.description, DECISION, 'vision')['accepted'])
        result, reviewed, generated = self.build(self.review)
        self.assertIsNotNone(result)
        self.assertFalse(result['generated'])
        self.assertEqual((reviewed, generated), (1, 0))
        imagery.validate_pixel_review(result, DRAFT)
        stock_binding(result)
        self.assertIn('full-article review', result['relevance_check']['reason'])
        self.assertIn('calculator', result['relevance_check']['reason'])

    def test_unrelated_or_unavailable_review_cannot_approve_composition_fallback(self):
        for review in ({**self.review, 'approved': False}, None):
            with self.subTest(review=review):
                result, reviewed, _ = self.build(review)
                self.assertIsNone(result)
                self.assertGreater(reviewed, 0)

    def test_wrong_exact_image_or_article_hash_is_refused(self):
        for key in ('image_sha256', 'article_text_sha256'):
            with self.subTest(key=key):
                result, _, _ = self.build({**self.review, key: '0'*64})
                self.assertIsNone(result)

    def test_forbidden_visible_subject_is_never_deferred(self):
        result, reviewed, _ = self.build(self.review, 'Blister packs beside identifiable faces.')
        self.assertIsNone(result)
        self.assertEqual(reviewed, 0)

    def test_missing_rights_identity_never_reaches_review(self):
        photo = {**PHOTO, 'photographer': ''}
        result, reviewed, _ = self.build(self.review, photo=photo)
        self.assertIsNone(result)
        self.assertEqual(reviewed, 0)

    def test_standalone_provider_keeps_strict_gate_without_exact_review_path(self):
        callback = mock.Mock(side_effect=lambda record: record)
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, 'provider_key', return_value='fixture-key'), \
                mock.patch.object(imagery, '_pexels_search', return_value={'photos': [PHOTO]}), \
                mock.patch.object(imagery, '_get_bytes', return_value=self.raw), \
                mock.patch.object(imagery, 'describe', return_value=self.description):
            self.assertIsNone(imagery.fetch_pexels(DRAFT, state, decision=DECISION, accept=callback))
        callback.assert_not_called()


if __name__ == '__main__':
    unittest.main()

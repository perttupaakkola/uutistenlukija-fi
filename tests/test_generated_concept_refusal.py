"""Real 13 Nov 2026 fault: a generated scene refused as a whole was regenerated 3x.

Orpo's Ukraine-negotiations story: after a text correction the image step re-chose an
empty conference table, the reviewer saw every required element yet refused it as too
generic (fit 5), and the identical prompt was generated three times. The story then
waited with no picture. The fixture holds the real draft, concept and replayed review.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import imagery
from news_mvp import controller

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' /
                      'image_concept_refusal_20261113.json').read_text())


class ConceptRefusedAsScene(unittest.TestCase):
    def test_real_review_is_a_scene_refusal(self):
        self.assertTrue(imagery.concept_refused_as_scene(FIXTURE['pixel_review']))

    def test_missing_element_is_not_a_scene_refusal(self):
        review = {**FIXTURE['pixel_review'], 'must_show_visible': [True, False]}
        self.assertFalse(imagery.concept_refused_as_scene(review))

    def test_approved_good_fit_is_not_a_refusal(self):
        review = {**FIXTURE['pixel_review'], 'approved': True, 'fit_score': 9}
        self.assertFalse(imagery.concept_refused_as_scene(review))

    def test_same_scene_is_generated_once_not_three_times(self):
        draft, concept = FIXTURE['draft'], FIXTURE['concept']
        calls = []

        def fake_generate(subject, category, **kwargs):
            calls.append(subject)
            return b'raw', 'prompt', 'codex-oauth:gpt-image-2'

        refusals = []
        token = imagery.CONCEPT_REFUSALS.set(refusals)
        try:
            with tempfile.TemporaryDirectory() as state, \
                    mock.patch.object(imagery, 'generate', side_effect=fake_generate), \
                    mock.patch.object(imagery, 'verify', return_value={}), \
                    mock.patch.object(imagery, '_jpg', side_effect=lambda raw: raw + str(len(calls)).encode()), \
                    mock.patch.object(imagery, '_other_article_images', return_value=set()), \
                    mock.patch.object(imagery, '_rejected_image_hashes', return_value=set()), \
                    mock.patch.object(imagery, 'review_pixels', return_value=dict(FIXTURE['pixel_review'])), \
                    mock.patch.object(imagery, '_reject_generated'), \
                    mock.patch('news_mvp.image_providers.request_event'):
                image = imagery._build_image(draft, state, 'Maailma', 'fixture', 3, concept,
                                             False, True, None, skip_stock=True, exact_concept=True)
        finally:
            imagery.CONCEPT_REFUSALS.reset(token)
        self.assertIsNone(image)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(refusals), 1)
        self.assertIn('neuvottelupöytä', refusals[0]['depictable_scene'])

    def test_refused_scene_reaches_the_next_classifier_round(self):
        draft = FIXTURE['draft']
        packet = {'story_key': 'url:https://valtioneuvosto.fi/-/paaministeri-orpo-dublinissa'}
        seen = []

        def classify(text_draft, model=None, packet=None, feedback=None):
            seen.append(feedback)
            return {'version': 'article-first-v1'}

        def build(*args, **kwargs):
            imagery._record_concept_refusal(FIXTURE['concept'], FIXTURE['pixel_review'])
            return None

        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, 'classify_draft', side_effect=classify), \
                mock.patch.object(imagery, 'build_image', side_effect=build):
            self.assertIsNone(controller.article_first_image(draft, packet, state, object()))
            # Second round (e.g. after a text correction, with no editorial feedback).
            controller.article_first_image(draft, packet, state, object())
        self.assertIsNone(seen[0])
        reasons = seen[1]['reasons']
        self.assertTrue(seen[1]['image_retryable'])
        self.assertTrue(any('neuvottelupöytä' in r and 'never this scene again' in r for r in reasons))
        # It is the shape the classifier's feedback parser accepts.
        self.assertIsNotNone(imagery._prior_feedback(seen[1]))

    def test_stored_refusals_are_bounded(self):
        with tempfile.TemporaryDirectory() as state:
            for _ in range(10):
                imagery.save_concept_refusals(state, 'k', [{'depictable_scene': 'x'}])
            self.assertEqual(len(imagery.load_concept_refusals(state, 'k')),
                             imagery.MAX_STORED_CONCEPT_REFUSALS)


if __name__ == '__main__':
    unittest.main()

"""Real 16 Nov 2026 fault: a must_show element that only text could prove was regenerated 6x.

The AI-at-work story (Työterveyslaitos) chose a desk scene requiring a "stack of printed
papers". Generated pictures may carry no text, so every picture drew a blank stack and the
pixel reviewer marked the element missing ("no discernible printing", fit 7). The same
prompt was generated 3 times in each of two correction rounds, nothing was remembered, and
the story waited with no picture. The fixture holds the real draft, concept and replayed review.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import imagery

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' /
                      'image_mustshow_text_20261116.json').read_text())


def _run(reviews):
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
                mock.patch.object(imagery, 'review_pixels', side_effect=[dict(r) for r in reviews]), \
                mock.patch.object(imagery, '_reject_generated'), \
                mock.patch('news_mvp.image_providers.request_event'):
            image = imagery._build_image(FIXTURE['draft'], state, 'Tiede', 'fixture', 3,
                                         FIXTURE['concept'], False, True, None,
                                         skip_stock=True, exact_concept=True)
    finally:
        imagery.CONCEPT_REFUSALS.reset(token)
    return image, calls, refusals


class MustShowNeverVisible(unittest.TestCase):
    def test_real_review_reports_the_papers_missing(self):
        self.assertEqual(imagery.missing_must_show(FIXTURE['pixel_review']), {1})
        self.assertFalse(imagery.concept_refused_as_scene(FIXTURE['pixel_review']))

    def test_same_missing_element_twice_stops_the_concept(self):
        image, calls, refusals = _run([FIXTURE['pixel_review']] * 3)
        self.assertIsNone(image)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]['missing'], ['stack of printed papers'])

    def test_different_missing_elements_keep_the_third_attempt(self):
        other = {**FIXTURE['pixel_review'], 'must_show_visible': [False, True]}
        image, calls, refusals = _run([FIXTURE['pixel_review'], other, other])
        self.assertIsNone(image)
        self.assertEqual(len(calls), 3)

    def test_feedback_tells_classifier_not_to_require_printing(self):
        refusal = {'depictable_scene': FIXTURE['concept']['depictable_scene'],
                   'missing': ['stack of printed papers'], 'fit_score': 7,
                   'reason': FIXTURE['pixel_review']['reason']}
        feedback = imagery.concept_refusal_feedback([refusal])
        text = ' '.join(feedback['reasons'])
        self.assertIn('stack of printed papers', text)
        self.assertIn('never require printing', text)
        self.assertIsNotNone(imagery._prior_feedback(feedback))

    def test_reviewer_is_told_generated_objects_carry_no_text(self):
        src = Path(imagery.__file__).read_text()
        self.assertIn("never '\n           'mark an element absent only because it carries no readable printing", src)


if __name__ == '__main__':
    unittest.main()

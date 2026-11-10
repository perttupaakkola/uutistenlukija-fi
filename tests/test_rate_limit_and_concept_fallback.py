"""Real 9-10 Nov 2026 faults: usage limit burned a story; one refused concept looped."""
import hashlib
import tempfile
import unittest
from unittest import mock

from news_mvp import imagery
from news_mvp.editorial import digest, model_login_unavailable

# Secret-free stderr text from the 9 Nov 2026 23:06-23:38 UTC writer failures.
REAL_429 = ("HTTP 429: Incomplete upstream response (first upstream attempt: status 429, capture "
            "incomplete, native retries denied: 0, upstream said: This request would exceed your "
            "account's rate limit. Please try again later.): You've hit your session limit")

DRAFT = {'title': 'Oulun tulovero pysyy ensi vuonna 8,10 prosentissa',
    'summary': 'Valtuusto hylkäsi esityksen veron laskemisesta, ja kiinteistöveroprosentit säilyvät.',
    'category': 'Kotimaa', 'paragraphs': [
        {'text': 'Oulun tulovero pysyy 8,10 prosentissa ja talousarvio on alijäämäinen.',
         'source_ids': ['A']}]}
C1 = {'rank': 1, 'safe_to_generate': True, 'subject': 'Oulun tulovero',
      'depictable_scene': 'Pino tulostettuja papereita ja euron kolikoita puupöydällä.',
      'must_show': ['printed budget documents', 'euro coins'], 'must_avoid': ['people'],
      'search_queries': ['municipal budget documents', 'euro coins table', 'tax papers desk']}
C2 = {'rank': 2, 'safe_to_generate': True, 'subject': 'talousarvio',
      'depictable_scene': 'Oulun kaupungintalon kaltainen kivirakennus harmaana päivänä.',
      'must_show': ['stone town hall building'], 'must_avoid': ['people'],
      'search_queries': ['town hall building', 'city hall stone facade', 'municipal building']}
DECISION = {'version': 'article-first-v1', 'category': 'Kotimaa', 'concepts': [C1, C2]}


class RateLimitIsModelOutage(unittest.TestCase):
    def test_real_session_limit_text_defers_instead_of_failing(self):
        self.assertTrue(model_login_unavailable(REAL_429))
        self.assertFalse(model_login_unavailable('ValueError: Invalid title 429 kirjaa'))


class RefusedConceptHandsOver(unittest.TestCase):
    def test_refused_first_concept_falls_back_to_next_safe_concept(self):
        calls = []
        def build(draft, state, category, model, attempts, concept, *a, **k):
            calls.append((concept['subject'], attempts))
            if concept['subject'] == C1['subject']:
                return None   # every picture of the budget papers refused (real 10 Nov case)
            raw = b'town-hall'
            return {'generated': True, 'sha256': hashlib.sha256(raw).hexdigest(),
                'pixel_review': {'approved': True, 'fit_score': 8,
                    'must_show_visible': [True], 'image_sha256': hashlib.sha256(raw).hexdigest(),
                    'article_text_sha256': imagery._article_text_sha(DRAFT),
                    'concept_sha256': digest(concept), 'no_people': True}}
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, 'fetch_pexels', return_value=None), \
                mock.patch.object(imagery, 'fetch_unsplash', return_value=None), \
                mock.patch.object(imagery, 'fetch_wikimedia', return_value=None), \
                mock.patch.object(imagery, 'fetch_google', return_value=None), \
                mock.patch.object(imagery, '_build_image', side_effect=build), \
                mock.patch('news_mvp.image_providers.candidate_event'):
            image = imagery._build_image_article_first(DRAFT, state, 'Kotimaa', 'fixture', 3,
                                                       DECISION, False, True, None)
        self.assertEqual(calls, [(C1['subject'], 1), (C2['subject'], 2)])
        self.assertEqual(image['selection_evidence']['selected']['concept_rank'], 2)
        imagery.validate_selection_evidence(image, DRAFT)

    def test_unsafe_concept_still_cannot_be_generated(self):
        decision = {**DECISION, 'concepts': [C1, {**C2, 'safe_to_generate': False}]}
        raw = b'x'
        image = {'generated': True, 'pixel_review': {'approved': True, 'fit_score': 8,
            'must_show_visible': [True], 'image_sha256': hashlib.sha256(raw).hexdigest(),
            'concept_sha256': digest(imagery.concept_decision(decision, decision['concepts'][1]))},
            'classifier_output': decision,
            'selection_evidence': {'version': 'article-first-v1',
                'article_text_sha256': imagery._article_text_sha(DRAFT),
                'decision_sha256': imagery._digest(decision), 'minimum_real_fit': 8,
                'searches': [], 'selected': {'kind': 'generated', 'concept_rank': 2,
                    'fit_score': 8, 'image_sha256': hashlib.sha256(raw).hexdigest()}}}
        with self.assertRaises(ValueError):
            imagery.validate_selection_evidence(image, DRAFT)

    def test_classifier_prompt_requires_shape_recognisable_must_show(self):
        from pathlib import Path
        text = (Path(imagery.__file__).resolve().parents[1] / 'prompts/image_classifier.md').read_text()
        self.assertIn('ilman luettavaa tekstiä, etikettiä', text)


if __name__ == '__main__':
    unittest.main()

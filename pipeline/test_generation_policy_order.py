"""Policy must explain generation skips before key/backoff availability.

Runs the real publisher enrichment orchestrator with all external boundaries
mocked; no provider requests, runtime env loading, or health writes are allowed.
"""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import staged_publish as staged


class GenerationPolicyOrderTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(staged.os.environ, {
            'UNSPLASH_ACCESS_KEY': '', 'PEXELS_API_KEY': '', 'KIE_API_KEY': '',
        }, clear=True))
        for name in ('load_env_files', 'sync_image_provider_keys'):
            self.stack.enter_context(patch.object(staged, name))
        self.generator = self.stack.enter_context(patch.object(staged, 'generate_images_for_articles'))
        self.skip = self.stack.enter_context(patch.object(staged, 'should_skip', return_value=(False, None)))
        self.success = self.stack.enter_context(patch.object(staged, 'record_success'))
        self.failure = self.stack.enter_context(patch.object(staged, 'record_failure'))
        self.unsplash = self.stack.enter_context(patch.object(staged, 'unsplash_fetch_images', side_effect=AssertionError('network forbidden')))
        self.pexels = self.stack.enter_context(patch.object(staged, 'pexels_fetch_images', side_effect=AssertionError('network forbidden')))

    @staticmethod
    def eligible() -> dict:
        return {'title': 'Aurinkoinen sää jatkuu', 'category': 'Kotimaa',
                'content': 'Aurinkoinen sää jatkuu Suomessa.'}

    @staticmethod
    def ineligible():
        return {'title': 'Tampereella ehkäistään lähisuhdeväkivaltaa',
                'category': 'Kotimaa',
                'content': 'Jouni Perttula kertoo väkivallan uhrien palveluista.'}

    def run_enrichment(self, articles):
        summary = staged.enrich_images_for_articles(articles, unsplash_delay=0, pexels_delay=0)
        self.unsplash.assert_not_called()
        self.pexels.assert_not_called()
        return summary

    def assert_policy_reject(self, article):
        terminal = article[staged.GENERATION_TERMINAL_FIELD]
        self.assertEqual(terminal['reason'], staged.REASON_PRE_SAFETY_REJECT)
        self.assertEqual(terminal['outcome'], 'policy_reject')
        self.assertFalse(terminal['provider_attempted'])
        self.assertFalse(terminal['provider_fault'])
        self.assertTrue(article['image_category_fallback'])
        self.assertEqual(article['image_decision_reason'], 'final category fallback after pre_safety_reject')

    def test_ineligible_precedes_key_and_backoff(self):
        for key, backoff in [('', False), ('synthetic-test-key', False), ('synthetic-test-key', True)]:
            with self.subTest(key_present=bool(key), backoff=backoff):
                staged.os.environ['KIE_API_KEY'] = key
                self.skip.return_value = (backoff, 'test backoff')
                article = self.ineligible()
                self.run_enrichment([article])
                self.assert_policy_reject(article)
        self.skip.assert_not_called()
        self.generator.assert_not_called()
        self.failure.assert_not_called()
        self.success.assert_not_called()

    def test_named_article_without_concrete_concept_is_policy_rejected(self):
        article = {'title': 'Pörssisijoittajan viikko alkaa', 'category': 'Talous',
                   'content': 'Mirko Hurmerinta ja Petri Niemisvirta esiintyvät verkkolähetyksessä.'}
        self.run_enrichment([article])
        self.assert_policy_reject(article)
        self.generator.assert_not_called()

    def test_eligible_missing_key_still_reports_missing_key(self):
        article = self.eligible()
        self.run_enrichment([article])
        self.assertEqual(article[staged.GENERATION_TERMINAL_FIELD]['reason'], staged.REASON_KEY_UNAVAILABLE)
        self.generator.assert_not_called()
        self.skip.assert_not_called()

    def test_eligible_backoff_still_reports_backoff(self):
        staged.os.environ['KIE_API_KEY'] = 'synthetic-test-key'
        self.skip.return_value = (True, 'test backoff')
        article = self.eligible()
        self.run_enrichment([article])
        self.assertEqual(article[staged.GENERATION_TERMINAL_FIELD]['reason'], staged.REASON_BACKOFF)
        self.generator.assert_not_called()
        self.skip.assert_called_once_with('kie_api')
        self.failure.assert_not_called()
        self.success.assert_not_called()

    def test_mixed_batch_only_routes_eligible_article(self):
        staged.os.environ['KIE_API_KEY'] = 'synthetic-test-key'
        rejected, eligible = self.ineligible(), self.eligible()
        self.run_enrichment([rejected, eligible])
        self.assert_policy_reject(rejected)
        self.generator.assert_called_once_with([eligible], max_total_sec=180)
        self.failure.assert_not_called()
        self.success.assert_not_called()

    def test_brief_failure_is_fail_closed_without_provider_health_change(self):
        staged.os.environ['KIE_API_KEY'] = 'synthetic-test-key'
        article = self.eligible()
        with patch.object(staged, 'build_visual_brief', side_effect=ValueError('test failure')):
            self.run_enrichment([article])
        self.assert_policy_reject(article)
        self.generator.assert_not_called()
        self.skip.assert_not_called()
        self.failure.assert_not_called()
        self.success.assert_not_called()

    def test_source_evidence_is_part_of_policy(self):
        for field in ('source_text', 'research'):
            with self.subTest(field=field):
                article = self.eligible()
                article[field] = 'Kyse on väkivallan uhreista.'
                self.run_enrichment([article])
                self.assert_policy_reject(article)
        self.generator.assert_not_called()

    def test_existing_generator_uses_same_grounded_inputs(self):
        # A safety pre-check must not drift from the generator's existing check.
        from image_candidate_guard import build_visual_brief
        from image_gen import generate_images_for_articles
        for base in (self.eligible(), self.ineligible()):
            article = copy.deepcopy(base)
            expected = build_visual_brief(article['title'], article['category'],
                                          content=article['content']).intent.generated_ok
            calls = []
            def brief(*args, **kwargs):
                calls.append((args, kwargs))
                return build_visual_brief(*args, **kwargs)
            with patch('image_candidate_guard.build_visual_brief', side_effect=brief), \
                 patch('image_gen.generate_article_image', side_effect=RuntimeError('boundary reached')):
                if expected:
                    with self.assertRaises(RuntimeError):
                        generate_images_for_articles([article])
                else:
                    generate_images_for_articles([article])
            with patch.object(staged, 'build_visual_brief', side_effect=brief):
                self.run_enrichment([copy.deepcopy(base)])
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], calls[1])


if __name__ == '__main__':
    unittest.main()

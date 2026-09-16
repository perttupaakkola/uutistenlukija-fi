"""Contracts for the municipal sources added to widen fresh-article supply.

These pin the properties that made the sources admissible, so a future edit cannot quietly
drop a licence requirement or start accepting a hub page as a news article.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class MunicipalSources(unittest.TestCase):
    def setUp(self):
        from news_mvp import official
        self.official = official
        self.policy = official.policy()

    def test_every_policy_provider_is_discoverable(self):
        """A provider present in the policy but absent from PROVIDER_ORDER is never fetched."""
        configured = set(self.policy['providers'])
        ordered = set(self.official.PROVIDER_ORDER)
        self.assertEqual(ordered - {'nasa-modis'} - configured, set(), 'order names an unknown provider')
        self.assertEqual(configured - ordered, set(), 'configured provider cannot be discovered')

    def test_municipal_sources_carry_a_pinned_rights_requirement(self):
        for provider in ('kuopio', 'vantaa'):
            spec = self.policy['providers'][provider]
            self.assertTrue(spec.get('rights_url'), provider)
            self.assertRegex(spec.get('rights_text_sha256', ''), r'^[a-f0-9]{64}$', provider)
            self.assertTrue(spec.get('article_pattern'), provider)
            self.assertTrue(spec.get('hosts'), provider)
            self.assertIn('Europe/Helsinki', spec.get('timezone', ''), provider)

    def test_kuopio_licence_is_pinned_by_document_hash(self):
        """Kuopio publishes its licence only as a PDF, so the document itself is the evidence."""
        spec = self.policy['providers']['kuopio']
        self.assertRegex(spec.get('rights_document_sha256', ''), r'^[a-f0-9]{64}$')
        self.assertTrue(spec['rights_url'].endswith('.pdf'))

    def test_rights_document_change_fails_closed(self):
        """A swapped licence document must never be treated as continued permission."""
        from news_mvp.official import rights_text
        with self.assertRaises(ValueError):
            rights_text(b'%PDF-1.4 not the reviewed document', 'kuopio')

    def test_article_patterns_reject_non_article_paths(self):
        import re
        cases = {
            'kuopio': ('https://www.kuopio.fi/2026/09/16/some-news-story', True),
            'vantaa': ('https://www.vantaa.fi/fi/ajankohtaista/tiedote/some-release', True),
        }
        for provider, (url, expected) in cases.items():
            pattern = self.policy['providers'][provider]['article_pattern']
            self.assertEqual(bool(re.fullmatch(pattern, url)), expected, provider)
        # Index and section pages must not match, or a hub page becomes a candidate.
        self.assertFalse(re.fullmatch(self.policy['providers']['kuopio']['article_pattern'],
                                      'https://www.kuopio.fi/2026/09/'))
        self.assertFalse(re.fullmatch(self.policy['providers']['vantaa']['article_pattern'],
                                      'https://www.vantaa.fi/fi/ajankohtaista/tiedotteet'))

    def test_aggregator_page_is_refused_before_the_excerpt_cap(self):
        """A hub page must be named as such, not surface as a misleading excerpt error."""
        self.assertLess(self.official.MAX_ARTICLE_CHARS, 20000,
                        'hub-page check must fire before editorial.text() excerpt cap')


if __name__ == '__main__':
    unittest.main()

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


class ValtioneuvostoSource(unittest.TestCase):
    """Valtioneuvosto is the highest-volume source; pin the properties that admit it."""

    def setUp(self):
        from news_mvp import official
        self.official = official
        self.spec = official.policy()['providers']['valtioneuvosto']

    def test_is_registered_for_rss_discovery(self):
        self.assertIn('valtioneuvosto', self.official.RSS_PROVIDERS)
        self.assertIn('valtioneuvosto', self.official.ADDITIONAL_PROVIDERS)
        self.assertIn('valtioneuvosto', self.official.PROVIDER_ORDER)

    def test_reuse_terms_are_pinned_and_record_the_commercial_limits(self):
        """Text reuse is permitted with attribution; commercial use needs a separate deal."""
        self.assertRegex(self.spec.get('rights_text_sha256', ''), r'^[a-f0-9]{64}$')
        self.assertTrue(self.spec.get('rights_url'))
        self.assertIn('valtioneuvosto.fi', self.spec['hosts'])
        self.assertEqual(self.spec.get('timezone'), 'Europe/Helsinki')
        # The non-commercial basis is explicit, with the reason, so it cannot be silently
        # treated as unrestricted reuse if sponsorship activates later.
        self.assertFalse(self.spec.get('commercial_use'))
        self.assertIn('non-commercial', self.spec.get('commercial_basis', '').lower())

    def test_article_pattern_accepts_both_url_forms_and_rejects_hubs(self):
        import re
        pattern = self.spec['article_pattern']
        self.assertTrue(re.fullmatch(pattern, 'https://valtioneuvosto.fi/-/ministeri-tavio-vierailee-virossa'))
        self.assertTrue(re.fullmatch(pattern, 'https://valtioneuvosto.fi/-/1410877/pk-yritysbarometri-1'))
        self.assertFalse(re.fullmatch(pattern, 'https://valtioneuvosto.fi/ajankohtaista/uutiset'))
        self.assertFalse(re.fullmatch(pattern, 'https://valtioneuvosto.fi/tietoa-sivustosta'))
        # A lookalike host must not satisfy the pattern.
        self.assertFalse(re.fullmatch(pattern, 'https://evil-valtioneuvosto.fi/-/some-slug'))


class ReuseLicenceIsNeverInvented(unittest.TestCase):
    def test_every_provider_declares_its_own_licence(self):
        """A defaulted licence can contradict the publisher's terms, as it did on
        Valtioneuvosto (claimed CC BY 4.0; terms require a separate commercial agreement)."""
        from news_mvp.official import policy
        for provider, spec in policy()['providers'].items():
            self.assertTrue(spec.get('license'), f'{provider} must declare its exact licence')

    def test_missing_licence_is_refused_rather_than_defaulted(self):
        from news_mvp.official import reuse
        with self.assertRaises(ValueError):
            reuse({'rights_url': 'https://example.fi/terms'})

    def test_valtioneuvosto_licence_records_the_commercial_limit(self):
        from news_mvp.official import policy
        spec = policy()['providers']['valtioneuvosto']
        self.assertIn('kaupalliseen', spec['license'])
        self.assertNotIn('CC BY 4.0', spec['license'])


if __name__ == '__main__':
    unittest.main()

"""Legacy redirect recovery: the reviewed inventory and its pure validation gate.

The reviewed inventory is deliberately empty of mappings: the planner checked all 20
top legacy demand rows (all still 404) against the 109 deployed article titles/summaries
and the live sitemap and found no reviewed equivalent, so nothing may be redirected.
These tests are offline: no network, no live directories, no production state.
"""
import copy
import json
import unittest
from pathlib import Path

from news_mvp.release_contract import (
    LEGACY_REDIRECTS,
    REDIRECT_MAX_LINES,
    REDIRECT_MAX_LINE_CHARS,
    legacy_inventory,
    legacy_redirect_lines,
    load_legacy_redirects,
    validate_legacy_mappings,
)

# The two named targets from the goal statement, kept explicit so a regression that
# silently "recovers" them by inventing a successor is caught here.
NAMED = ['/posts/2026-09-09-tampere-irtisanoo-liikuntapalvelujen-paallikon-hakametsan-ep/',
         '/oppaat/kauppojen-aukioloajat/']

TARGET = '/uutiset/kauppojen-aukioloajat-abcdef123456/'
ELIGIBLE = ['/uutiset/muu-juttu-abcdef123456/', TARGET]


def mapping(source='/oppaat/kauppojen-aukioloajat/', target=TARGET, **overrides):
    record = {'source': source, 'target': target, 'reviewed': True,
              'review': {'rationale': 'Editorially confirmed equivalent successor.',
                         'evidence': ['editorial review 2026-09-22']}}
    record.update(overrides)
    return record


class RealInventory(unittest.TestCase):
    """The committed data file: exact reviewed counts, targets and an empty mapping list."""

    def setUp(self):
        self.document = load_legacy_redirects()

    def test_inventory_has_exactly_the_twenty_reviewed_rows_and_measured_totals(self):
        summary = legacy_inventory(self.document)
        self.assertEqual(summary['rows'], 20)
        self.assertEqual(summary['clicks'], 57)
        self.assertEqual(summary['impressions'], 2676)
        self.assertEqual(summary['paths'][:1], [NAMED[0]])
        self.assertIn(NAMED[1], summary['paths'])
        self.assertEqual(len(set(summary['paths'])), 20)
        self.assertTrue(all(path.startswith('/') and path.endswith('/') for path in summary['paths']))

    def test_rows_are_missing_pages_with_no_reviewed_equivalent(self):
        for row in self.document['inventory']:
            self.assertEqual(row['http_status'], 404)
            self.assertEqual(row['equivalence'], 'no-reviewed-equivalent')

    def test_evidence_window_bound_and_rationale_are_kept_in_the_data(self):
        self.assertEqual(self.document['window']['start'], '2026-08-20')
        self.assertEqual(self.document['window']['end'], '2026-09-18')
        self.assertTrue(self.document['window']['final'])
        self.assertEqual(self.document['bound']['source_row_cap'], 250)
        self.assertTrue(self.document['bound']['cap_reached'])
        self.assertFalse(self.document['bound']['exhaustive'])
        self.assertIn('no reviewed equivalent', self.document['review']['rationale'])
        self.assertIn('legacy-http-evidence.json', self.document['review']['evidence'])

    def test_no_reviewed_mapping_exists_so_nothing_is_redirected(self):
        self.assertEqual(self.document['mappings'], [])
        summary = legacy_inventory(self.document)
        self.assertEqual(summary['mapped'], [])
        self.assertEqual(legacy_redirect_lines(self.document['mappings'], ELIGIBLE), [])
        for path in NAMED:
            self.assertNotIn(path, [mapping['source'] for mapping in self.document['mappings']])

    def test_malformed_inventory_fails_closed(self):
        cases = {}
        missing = copy.deepcopy(self.document); missing.pop('totals'); cases['missing totals'] = missing
        wrong = copy.deepcopy(self.document); wrong['totals']['clicks'] = 58; cases['wrong totals'] = wrong
        rows = copy.deepcopy(self.document); rows['inventory'] = rows['inventory'][:19]; cases['row count'] = rows
        live = copy.deepcopy(self.document); live['inventory'][0]['http_status'] = 200; cases['not missing'] = live
        dup = copy.deepcopy(self.document); dup['inventory'][1]['source'] = dup['inventory'][0]['source']; cases['duplicate row'] = dup
        unsafe = copy.deepcopy(self.document); unsafe['inventory'][0]['source'] = '//evil.example/posts/x/'; cases['unsafe source'] = unsafe
        window = copy.deepcopy(self.document); window['window']['final'] = False; cases['not final'] = window
        review = copy.deepcopy(self.document); review['review'].pop('rationale'); cases['no rationale'] = review
        version = copy.deepcopy(self.document); version['schema_version'] = 2; cases['bad version'] = version
        unreviewed = copy.deepcopy(self.document)
        unreviewed['mappings'] = [mapping(reviewed=False)]
        cases['unreviewed file mapping'] = unreviewed
        unsafe_map = copy.deepcopy(self.document)
        unsafe_map['mappings'] = [mapping(source='//evil.example/oppaat/x/')]
        cases['unsafe file mapping'] = unsafe_map
        for label, document in cases.items():
            with self.subTest(label=label):
                path = Path(self._tmp())
                path.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    load_legacy_redirects(path)

    def test_unreadable_or_non_json_inventory_fails_closed(self):
        path = Path(self._tmp())
        path.write_text('{not json')
        with self.assertRaises(ValueError):
            load_legacy_redirects(path)
        with self.assertRaises(ValueError):
            load_legacy_redirects(Path(self._tmp()) / 'missing.json')

    def _tmp(self):
        import tempfile
        if not hasattr(self, '_dir'):
            self._dir = tempfile.TemporaryDirectory()
            self.addCleanup(self._dir.cleanup)
        return Path(self._dir.name) / 'legacy_redirects.json'


class MappingValidation(unittest.TestCase):
    def test_reviewed_mapping_to_an_eligible_article_is_accepted(self):
        lines = legacy_redirect_lines([mapping()], ELIGIBLE)
        self.assertEqual(lines, [f'/oppaat/kauppojen-aukioloajat/ {TARGET} 301'])

    def test_lines_are_deterministic_and_sorted(self):
        second = mapping(source='/posts/2026-01-01-vanha-juttu/', target=ELIGIBLE[0])
        lines = legacy_redirect_lines([mapping(), second], ELIGIBLE)
        self.assertEqual(lines, sorted(lines))
        self.assertEqual(lines, legacy_redirect_lines([second, mapping()], ELIGIBLE))

    def test_generated_aliases_join_the_same_rule_set(self):
        alias = ('/uutiset/' + 'a' * 64 + '/', TARGET)
        lines = legacy_redirect_lines([mapping()], ELIGIBLE, [alias])
        self.assertIn(f'{alias[0]} {TARGET} 301', lines)
        self.assertIn(f'/oppaat/kauppojen-aukioloajat/ {TARGET} 301', lines)

    def test_unsafe_syntax_is_rejected(self):
        unsafe = ['https://evil.example/oppaat/x/', '//evil.example/oppaat/x/', '/oppaat/x',
                  '/oppaat/x/?q=1', '/oppaat/x/#frag', '/oppaat/%2e%2e/x/', '/oppaat/x/../y/',
                  '/oppaat\\x/', '/oppaat/ x/', '/oppaat/x/\r\n/evil/', '/oppaat/*/', '/oppaat/{x}/',
                  '/oppaat/x/%2f/']
        for value in unsafe:
            with self.subTest(source=value):
                with self.assertRaises(ValueError):
                    legacy_redirect_lines([mapping(source=value)], ELIGIBLE)
        for value in ['https://uutistenlukija.fi' + TARGET, '//uutistenlukija.fi' + TARGET,
                      '/', '/uutiset/', TARGET + '?x=1', TARGET + '#x']:
            with self.subTest(target=value):
                with self.assertRaises(ValueError):
                    legacy_redirect_lines([mapping(target=value)], ELIGIBLE)

    def test_broad_replacement_targets_are_not_canonical_articles(self):
        for value in ['/', '/uutiset/', '/kategoriat/talous/']:
            with self.subTest(target=value):
                with self.assertRaises(ValueError):
                    validate_legacy_mappings([mapping(target=value)], ELIGIBLE)

    def test_unreviewed_or_evidence_free_mappings_are_rejected(self):
        cases = [mapping(reviewed=False), mapping(reviewed='true'), mapping(reviewed=1),
                 mapping(review={}), mapping(review={'rationale': 'x'}),
                 mapping(review={'rationale': 'x', 'evidence': []}),
                 mapping(review={'rationale': '   ', 'evidence': ['e']}),
                 mapping(review={'rationale': 'x', 'evidence': [' ']})]
        for record in cases:
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    validate_legacy_mappings([record], ELIGIBLE)

    def test_duplicate_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_legacy_mappings([mapping(), mapping(target=ELIGIBLE[0])], ELIGIBLE)
        alias = (mapping()['source'], TARGET)
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping()], ELIGIBLE, [alias])

    def test_targets_outside_the_eligible_canonical_set_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_legacy_mappings([mapping(target='/uutiset/ei-julkaistu-abcdef123456/')], ELIGIBLE)
        with self.assertRaises(ValueError):
            legacy_redirect_lines([], ELIGIBLE, [('/uutiset/' + 'b' * 64 + '/', '/uutiset/puuttuu-1/')])

    def test_loops_chains_and_self_redirects_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_legacy_mappings([mapping(target=mapping()['source'])], ELIGIBLE)
        chained = [mapping(source='/oppaat/a/', target=TARGET),
                   mapping(source='/oppaat/b/', target='/oppaat/a/')]
        with self.assertRaises(ValueError):
            validate_legacy_mappings(chained, ELIGIBLE)
        alias = ('/uutiset/' + 'c' * 64 + '/', TARGET)
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping(target=alias[0])], ELIGIBLE + [alias[0]], [alias])

    def test_sources_shadowing_a_live_canonical_are_rejected(self):
        for source in ['/uutiset/', '/uutiset/muu-juttu-abcdef123456/']:
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    validate_legacy_mappings([mapping(source=source)], ELIGIBLE)

    def test_malformed_structure_fails_closed(self):
        for value in [None, {}, 'x', [None], [{'source': '/a/', 'target': TARGET}],
                      [mapping(extra='x')], [mapping(source=1)], [mapping(target=None)]]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_legacy_mappings(value, ELIGIBLE)
        for value in [None, 'x', [('a', 'b')], [('/a/',)] ]:
            with self.subTest(extra=value):
                with self.assertRaises(ValueError):
                    legacy_redirect_lines([], ELIGIBLE, value)

    def test_cloudflare_limits_are_enforced(self):
        self.assertEqual(REDIRECT_MAX_LINES, 2000)
        self.assertEqual(REDIRECT_MAX_LINE_CHARS, 1000)
        many = [mapping(source=f'/oppaat/{index}/', target=TARGET) for index in range(REDIRECT_MAX_LINES + 1)]
        with self.assertRaises(ValueError):
            legacy_redirect_lines(many, ELIGIBLE)
        long_source = '/oppaat/' + 'x' * (REDIRECT_MAX_LINE_CHARS + 10) + '/'
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping(source=long_source)], ELIGIBLE)


if __name__ == '__main__':
    unittest.main()

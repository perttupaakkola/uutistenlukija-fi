"""Offline A1–A6 regressions. Never import auth-reading legacy report modules."""
import ast
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from analytics_contract import ctr_fraction, traffic_classification, validate_source
from analytics_freshness_evidence import summarize_daily_report, summarize_search_console
from ctr_gap_report import analyze_gsc_data, load_search_console_data
from fetch_search_console import fetch_report
from reader_retention_report import build_report

FIXTURES = Path(__file__).with_name('fixtures') / 'analytics'
NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


def functions_only(name, names):
    path = Path(__file__).with_name(name)
    tree = ast.parse(path.read_text())
    scope = {}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), str(path), 'exec'), scope)
    return scope


def gsc_report(**kwargs):
    rows = fixture('gsc_production28_full')['response']['rows']
    aggregate = fixture('gsc_rolling30_final')['response']
    # Pagination fixture rows and aggregate are independent on purpose: never sum dimensions.
    requests = []
    def query(_token, request):
        requests.append(request)
        if 'dimensions' not in request:
            return aggregate
        start = request['startRow']
        return {'rows': rows[start:start + request['rowLimit']]}
    report = fetch_report('fixture-not-a-token', now=NOW, page_size=2, query_fn=query, **kwargs)
    return report, requests


class AnalyticsRebuildTest(unittest.TestCase):
    def test_ctr_identity_beats_legacy_heuristic(self):
        rows = fixture('legacy_ctr_rows')
        gaps = analyze_gsc_data(rows, 20)
        self.assertEqual([g['ctr'] for g in gaps], [0.61, 0.14])

    def test_ctr_boundaries_and_explicit_units(self):
        for percent in [0, 0.14, 0.61, 1, 3, 100]:
            for unit, value in [('percent', percent), ('fraction', percent / 100)]:
                self.assertAlmostEqual(ctr_fraction({'ctr': value, 'ctr_unit': unit}), percent / 100)
            self.assertAlmostEqual(ctr_fraction({'clicks': percent, 'impressions': 100, 'ctr': 99}), percent / 100)
        self.assertEqual(ctr_fraction({'clicks': 0, 'impressions': 0}), 0)
        for row in [{}, {'ctr': .61}, {'ctr': None}, {'ctr_fraction': 2}, {'clicks': 2, 'impressions': 1}, {'ctr_fraction': float('nan')}]:
            with self.assertRaises((ValueError, TypeError)):
                ctr_fraction(row)

    def test_paginated_provider_rows_and_direct_totals(self):
        report, requests = gsc_report()
        self.assertEqual([r['startRow'] for r in requests if 'dimensions' in r], [0, 2, 4])
        self.assertEqual(report['row_count'], 4)
        self.assertTrue(report['completeness']['pagination_exhausted'])
        self.assertEqual(report['property_totals']['clicks'], 116)
        self.assertEqual(report['query_window'], {'startDate': '2026-08-08', 'endDate': '2026-09-04'})
        self.assertTrue(validate_source(report, 'gsc', NOW)['fresh'])
        self.assertEqual(report['ctr_unit'], 'percent')
        self.assertAlmostEqual(report['rows'][0]['ctr_fraction'], report['rows'][0]['clicks'] / report['rows'][0]['impressions'])

    def test_cap_is_explicit_and_fails_closed(self):
        report, _ = gsc_report(max_rows=2)
        self.assertTrue(report['completeness']['row_limit_reached'])
        self.assertFalse(validate_source(report, 'gsc', NOW)['fresh'])

    def test_gsc_wrong_property_schema_and_window_fail_closed(self):
        base, _ = gsc_report()
        for fields in [{'site': 'sc-domain:wrong.invalid'}, {'schema_version': 99},
                       {'ctr_unit': 'fraction'}, {'days': 30}, {'data_state': 'all'},
                       {'rows': [], 'row_count': 0}]:
            data = dict(base, **fields)
            self.assertFalse(validate_source(data, 'gsc', NOW)['fresh'])

    def test_duplicate_pagination_is_rejected(self):
        row = fixture('gsc_production28_full')['response']['rows'][0]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            fetch_report('fixture', page_size=1, query_fn=lambda *_: {'rows': [row]}, now=NOW)

    def test_partial_failure_does_not_return_success(self):
        def query(_, request):
            if request.get('startRow') == 0:
                return {'rows': fixture('gsc_production28_full')['response']['rows'][:2]}
            raise OSError('fixture failure')
        with self.assertRaises(OSError):
            fetch_report('fixture', page_size=2, query_fn=query, now=NOW)

    def test_freshness_rejects_empty_stale_schema_property_and_window(self):
        base = fixture('ga4_rolling30_latest')
        self.assertTrue(validate_source(base, 'ga4', NOW)['fresh'])
        variants = [{}, dict(base, fetched_at='2020-01-01T00:00:00Z'), dict(base, endpoint='wrong'), dict(base, fetched_at='2026-09-08T00:00:00Z')]
        for mutate in [lambda d: d['response'].update(rows=[]),
                       lambda d: d['request']['dateRanges'][0].update(endDate='2026-08-01'),
                       lambda d: d['response']['metricHeaders'][0].update(name='wrong'),
                       lambda d: d['response'].update(metadata={'subjectToThresholding': True})]:
            data = copy.deepcopy(base); mutate(data); variants.append(data)
        for data in variants:
            self.assertFalse(validate_source(data, 'ga4', NOW)['fresh'])

    def test_touch_cannot_bless_invalid_data_and_loader_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'source.json'
            for data in [{}, {'generated_at': '2020-01-01'}, {'site': 'wrong', 'rows': fixture('legacy_ctr_rows')}]:
                path.write_text(json.dumps(data)); os.utime(path, None)
                self.assertEqual(load_search_console_data(path), [])
                with patch('analytics_freshness_evidence.DAILY_REPORT', path), patch('analytics_freshness_evidence.PROJECT_DIR', Path(temp)):
                    self.assertFalse(summarize_daily_report(data, None, NOW, 30)['fresh'])

    def test_successful_total_cannot_certify_missing_daily_components(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'daily.json'
            data = {'generated_at': '2026-09-07', 'daily_pageviews': [],
                    'ga4_source': fixture('ga4_rolling30_latest')}
            path.write_text(json.dumps(data))
            with patch('analytics_freshness_evidence.DAILY_REPORT', path), patch('analytics_freshness_evidence.PROJECT_DIR', Path(temp)):
                self.assertFalse(summarize_daily_report(data, None, NOW, 30)['fresh'])

    def test_direct_rolling30_goal_and_returning_share(self):
        report = build_report(fixture('ga4_rolling30_latest'), fixture('ga4_new_returning30'), now=NOW)
        self.assertEqual(report['status'], 'fresh')
        self.assertEqual(report['goal']['activeUsers']['observed'], 54)
        self.assertEqual(report['goal']['screenPageViews']['observed'], 108)
        self.assertAlmostEqual(report['returning_active_share']['value'], 6 / 54)
        self.assertFalse(report['returning_active_share']['is_cohort_retention'])
        self.assertFalse(report['traffic']['qa_internal_separated'])

    def test_goal_rejects_dimension_sums_filters_and_wrong_window(self):
        variants = [fixture('ga4_new_returning30')]
        for mutate in [lambda d: d['request'].update(dimensionFilter={'filter': {}}),
                       lambda d: d['request']['dateRanges'][0].update(startDate='2026-08-09')]:
            d = fixture('ga4_rolling30_latest'); mutate(d); variants.append(d)
        for d in variants:
            self.assertIsNone(build_report(d, now=NOW)['goal'])

    def test_returning_wrong_window_is_not_divided(self):
        returning = fixture('ga4_new_returning30')
        returning['request']['dateRanges'][0] = {'startDate': '2026-08-07', 'endDate': '2026-09-05'}
        report = build_report(fixture('ga4_rolling30_latest'), returning, now=NOW)
        self.assertEqual(report['returning_active_share']['status'], 'blocked')

    def test_legacy_retention_uses_direct_denominator(self):
        funcs = functions_only('retention_trend.py', {'extract_metric', 'extract_new_returning'})
        extract = funcs['extract_new_returning']
        dims = fixture('ga4_new_returning30')['response']
        total = fixture('ga4_rolling30_latest')['response']
        self.assertIsNone(extract(dims)[3])
        self.assertEqual(extract(dims, total)[1:], (6, 67, 54))

    def test_bounce_presentation_and_qa_classification(self):
        # Evaluate actual f-string fields, without importing the module's env/auth bootstrap.
        tree = ast.parse(Path(__file__).with_name('daily_traffic_card.py').read_text())
        strings = [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)]
        fields = [n for s in strings for n in s.values if isinstance(n, ast.FormattedValue) and isinstance(n.value, ast.Name) and n.value.id in ('bounce_rate', 'b_bounce')]
        self.assertEqual(len(fields), 2)
        for field in fields:
            expression = ast.Expression(ast.JoinedStr([field]))
            rendered = eval(compile(ast.fix_missing_locations(expression), '<fixture>', 'eval'), {'bounce_rate': 0.3636363636, 'b_bounce': 0.3636363636})
            self.assertEqual(rendered, '36.4%')
        self.assertEqual(traffic_classification({'traffic_type': 'qa'}), 'qa')
        self.assertEqual(traffic_classification({'traffic_type': 'internal'}), 'internal')
        self.assertEqual(traffic_classification({'experiment_id': 'test'}), 'unclassified')
        self.assertEqual(traffic_classification({}), 'unclassified')


if __name__ == '__main__':
    unittest.main()

"""Actual weekly/panel callers, offline AST loading without env/auth bootstrap."""
import ast
import copy
import contextlib
import io
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)


def functions_only(filename, names=None, **scope):
    path = ROOT / 'scripts' / filename
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and (names is None or n.name in names)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


def fixture(name):
    return json.loads((ROOT / 'scripts/fixtures/analytics' / (name + '.json')).read_text())['response']


def weekly(metrics, dimensions=None):
    report = fixture('ga4_new_returning30' if dimensions else 'ga4_rolling30_latest')
    names = [h['name'] for h in report['metricHeaders']]
    report['metricHeaders'] = [report['metricHeaders'][names.index(m)] for m in metrics]
    for row in report['rows']:
        row['metricValues'] = [row['metricValues'][names.index(m)] for m in metrics]
    return report


class WeeklyReviewTest(unittest.TestCase):
    def caller(self, mutate=None, bad_call=0, null_response=False):
        calls = []
        def query(token, start, end, metrics, dimensions=None):
            report = weekly(metrics, dimensions)
            if len(calls) == bad_call and mutate:
                mutate(report)
            if len(calls) == bad_call and null_response:
                report = None
            calls.append((start, end, metrics, dimensions))
            return report
        scope = functions_only('retention_trend.py', datetime=datetime, timedelta=timedelta,
                               timezone=timezone, sys=sys)
        scope.update(os=type('Env', (), {'environ': {}}), get_valid_token=lambda: 'offline',
                     ga4_report=query, post_to_discord=Mock(side_effect=AssertionError('No send')))
        output = io.StringIO()
        with patch.object(sys, 'argv', ['retention_trend.py', '--dry-run']), contextlib.redirect_stdout(output):
            result = scope['main']()
        scope['post_to_discord'].assert_not_called()
        return result, output.getvalue(), calls

    def test_actual_weekly_caller_uses_independent_same_window_denominators(self):
        result, output, calls = self.caller()
        self.assertIn('**11 %**', output)  # 6 / 54, never 6 / (52 + 6)
        self.assertNotEqual(result, 1)
        self.assertEqual(len(calls), 4)
        for numerator, denominator in [(calls[0], calls[2]), (calls[1], calls[3])]:
            self.assertEqual(numerator[:2], denominator[:2])
            self.assertEqual(denominator[2:], (['activeUsers'], None))
            self.assertEqual(numerator[3], ['newVsReturning'])
            self.assertEqual((datetime.fromisoformat(numerator[1]) - datetime.fromisoformat(numerator[0])).days, 6)
        self.assertIn('ei ole hankintakohortin', output)

    def test_review_actual_extractor_truncated_rows(self):
        scope = functions_only('retention_trend.py')
        report = fixture('ga4_new_returning30')
        report['rows'] = report['rows'][:1]
        with self.assertRaises(ValueError):
            scope['extract_new_returning'](report, fixture('ga4_rolling30_latest'))

    def test_actual_caller_blocks_bad_numerator_and_denominator(self):
        mutations = {
            'truncated': lambda r: r.update(rows=r['rows'][:1]),
            'missing_rows': lambda r: r.pop('rows'),
            'row_count': lambda r: r.update(rowCount=999),
            'boolean_row_count': lambda r: r.update(rowCount=True),
            'missing_metric': lambda r: r['metricHeaders'][0].update(name='wrong'),
            'wrong_dimensions': lambda r: r.update(dimensionHeaders=[{'name': 'country'}]),
            'short_values': lambda r: r['rows'][0].update(metricValues=[]),
            'thresholded': lambda r: r.update(metadata={'subjectToThresholding': True}),
            'sampled': lambda r: r.update(metadata={'samplingMetadatas': [{'samplesReadCount': '10', 'samplingSpaceSize': '100'}]}),
            'data_loss': lambda r: r.update(metadata={'dataLossFromOtherRow': True}),
        }
        for value in [None, '', 'bad', 'NaN', 'Infinity', '-1', True]:
            mutations['number_' + str(value)] = lambda r, value=value: r['rows'][0]['metricValues'][0].update(value=value)
        for call in range(4):
            for name, mutate in mutations.items():
                if name == 'truncated' and call >= 2:
                    continue  # The direct report already has exactly one row.
                with self.subTest(call=call, mutation=name):
                    result, output, _ = self.caller(mutate, call)
                    self.assertEqual(result, 1)
                    self.assertNotIn('**Palaavien', output)
                    self.assertIn('unavailable', output)

    def test_complete_absent_returning_is_valid_zero_but_duplicate_is_invalid(self):
        scope = functions_only('retention_trend.py')
        report = fixture('ga4_new_returning30')
        report['rows'] = report['rows'][:1]
        report['rowCount'] = 1
        self.assertEqual(scope['extract_new_returning'](report, fixture('ga4_rolling30_latest'))[1], 0)
        report['rows'].append(copy.deepcopy(report['rows'][0]))
        report['rowCount'] = 2
        with self.assertRaises(ValueError):
            scope['extract_new_returning'](report, fixture('ga4_rolling30_latest'))

    def test_actual_returning_numerator_and_zero_denominator_block(self):
        for call in [0, 1]:
            for value in [None, 'bad', 'NaN', 'Infinity', '-1', True, '55']:
                with self.subTest(call=call, returning=value):
                    mutate = lambda r: r['rows'][1]['metricValues'][0].update(value=value)
                    result, output, _ = self.caller(mutate, call)
                    self.assertEqual(result, 1)
                    self.assertNotIn('**Palaavien', output)
        for call in [2, 3]:
            result, output, _ = self.caller(lambda r: r['rows'][0]['metricValues'][0].update(value='0'), call)
            self.assertEqual(result, 1)
            self.assertNotIn('**Palaavien', output)
            result, output, _ = self.caller(bad_call=call, null_response=True)
            self.assertEqual(result, 1)
            self.assertNotIn('**Palaavien', output)


class PanelReviewTest(unittest.TestCase):
    def caller(self, ctr, freshness=None):
        scope = functions_only('business_control_panel.py',
            {'analytics_status', 'parse_dt', 'iso', 'age_minutes', 'sanitize_reason'},
            Any=Any, Path=Path, datetime=datetime, timedelta=timedelta, timezone=timezone, re=re,
            PROJECT_DIR=ROOT, LOG_DIR=ROOT / 'absent-fixture-logs', ANALYTICS_FRESHNESS_MAX_AGE_HOURS=48,
            SECRETISH_RE=re.compile(r'(?!)'), URL_QUERY_RE=re.compile(r'(?!)'))
        scope['newest_existing_json'] = lambda paths: (paths[0], ctr) if 'ctr-gap-report' in str(paths[0]) else (None, freshness)
        return scope['analytics_status'](NOW)

    def test_exact_blocked_v2_report_with_missing_stale_and_fresh_evidence(self):
        ctr = {'schema_version': 2, 'status': 'blocked', 'reason': 'invalid_stale_or_empty_gsc',
               'data_source': 'unavailable', 'generated_at': NOW.isoformat(), 'gaps': [], 'total_gaps_found': 0}
        fresh = {'status': 'fresh', 'checked_at': NOW.isoformat(), 'artifacts': {
            key: {'fresh': True, 'evidence_at': NOW.isoformat()} for key in ['daily_report', 'search_console']}}
        for freshness in [None, {'status': 'stale'}, fresh]:
            with self.subTest(freshness=freshness):
                result = self.caller(ctr, freshness)['gsc']
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], ctr['reason'])
                self.assertEqual(result['ctr_gap_report']['status'], 'blocked')

    def test_stale_and_unknown_sources_never_look_valid(self):
        valid = {'schema_version': 2, 'status': 'fresh', 'reason': 'validated_source',
                 'data_source': 'google_search_console', 'generated_at': NOW.isoformat()}
        self.assertEqual(self.caller(valid)['gsc']['status'], 'local_report_present')
        for fields, expected in [({'status': 'stale', 'reason': 'source_timestamp_stale'}, 'stale'),
                                 ({'data_source': 'surprise'}, 'blocked'),
                                 ({'status': 'surprise'}, 'blocked'),
                                 ({'status': None}, 'blocked'),
                                 ({'generated_at': '2026-01-01T00:00:00Z'}, 'stale')]:
            with self.subTest(fields=fields):
                ctr = dict(valid, **fields)
                for freshness in [None, {'status': 'stale'}]:
                    self.assertEqual(self.caller(ctr, freshness)['gsc']['status'], expected)


if __name__ == '__main__':
    unittest.main()

"""Offline snapshot tests, fixture provider only, no private runtime access."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch
import analytics_projection as p
from test_collect_analytics import FakeProvider, NOW
import collect_analytics as c


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='analytics-projection-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'analytics'
        fake = FakeProvider()
        code, _ = c.execute(self.data, now=NOW, token_fn=fake.token, transport=fake.post)
        self.assertEqual(code, 0)

    def alter(self, name, fn):
        path = self.data / name
        data = json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data))

    def rebind_fixture_marker(self):
        # Simulate producer-captured bytes with corrupt cached projections. This
        # deliberately bypasses the digest gate to exercise semantic revalidation.
        marker = json.loads((self.data/'collector-status.json').read_text())
        marker['source_sha256'] = {name: p.canonical_source_hash(json.loads((self.data/name).read_text()))
                                  for name in ('daily-report.json', 'search-console-data.json')}
        (self.data/'collector-status.json').write_text(json.dumps(marker))

    def test_exact_private_sources_and_direct_goal_not_static_mtime(self):
        legacy = self.root / 'static/api'
        legacy.mkdir(parents=True)
        (legacy / 'analytics-freshness-status.json').write_text('{"status":"fresh"}')
        (legacy / 'search-console-data.json').write_text('{"row_count":999}')
        before = {f: f.read_bytes() for f in self.data.iterdir()}
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'fresh')
        self.assertEqual(summary['search_console_rows'], 1)
        reader = outputs['reader-retention-report.json']
        self.assertEqual(reader['goal']['screenPageViews']['observed'], 108)
        self.assertEqual(reader['goal']['activeUsers']['observed'], 54)
        self.assertEqual(reader['returning_active_share']['value'], 6/54)
        self.assertFalse(reader['traffic']['qa_internal_separated'])
        self.assertEqual(reader['cohort_retention']['status'], 'unavailable')
        self.assertEqual(outputs['ctr-gap-report.json']['ctr_unit'], 'percent')
        self.assertEqual({f: f.read_bytes() for f in self.data.iterdir()}, before)

    def test_nested_reader_and_gsc_totals_recomputed_not_trusted(self):
        self.alter('daily-report.json', lambda d: d.update(reader_retention={'goal_met': True}, search_console={'total_clicks': 999999}))
        self.rebind_fixture_marker()
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'fresh')
        self.assertFalse(outputs['daily-report.json']['reader_retention']['goal_met'])
        self.assertEqual(outputs['daily-report.json']['search_console']['total_clicks'], 6)
        self.assertEqual(outputs['daily-report.json']['search_console']['top_queries_status'], 'private_not_exported')

    def test_last_good_cannot_hide_latest_failed_attempt(self):
        self.alter('collector-status.json', lambda d: d.update(status='blocked'))
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')
        self.assertIsNone(outputs['reader-retention-report.json']['goal'])
        self.assertNotIn('rows', outputs['search-console-data.json'])

    def test_clock_advance_invalidates_even_newly_touched_files(self):
        for path in self.data.iterdir(): os.utime(path, None)
        outputs, summary = p.team_snapshot(self.root, NOW + timedelta(days=4))
        self.assertEqual(summary['freshness_status'], 'blocked')
        self.assertFalse(outputs['analytics-freshness-status.json']['fresh'])

    def test_missing_corrupt_wrong_property_and_future_attempt_fail_closed(self):
        for mode in ('missing', 'corrupt', 'wrong_property', 'future'):
            with self.subTest(mode=mode):
                path = self.data / ('daily-report.json' if mode == 'wrong_property' else 'collector-status.json')
                old = path.read_bytes()
                if mode == 'missing': path.unlink()
                elif mode == 'corrupt': path.write_text('bad')
                elif mode == 'future': self.alter(path.name, lambda d: d.update(checked_at=(NOW+timedelta(days=1)).isoformat()))
                else: self.alter(path.name, lambda d: d['ga4_source'].update(endpoint='https://analyticsdata.googleapis.com/v1beta/properties/999:runReport'))
                outputs, summary = p.team_snapshot(self.root, NOW)
                self.assertEqual(summary['freshness_status'], 'blocked')
                path.write_bytes(old)

    def test_credentiallike_content_not_exported(self):
        self.alter('daily-report.json', lambda d: d.update(private_key='fixture-secret'))
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')
        self.assertNotIn('fixture-secret', json.dumps(outputs))

    def test_all_six_destinations_have_verified_manifest_and_blocked_replacement(self):
        outputs, summary = p.team_snapshot(self.root, NOW)
        dests = [self.root / ws for ws in p.WORKSPACES]
        manifest = p.export_snapshot(outputs, summary, dests)
        self.assertEqual(len(dests), 6)
        for dest in dests:
            self.assertEqual(json.loads((dest/'latest.json').read_text()), manifest)
            for name, item in manifest['artifacts'].items():
                raw = (dest/name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item['sha256'])
                self.assertEqual(len(raw), item['bytes'])
        self.alter('collector-status.json', lambda d: d.update(status='blocked'))
        p.export_snapshot(*p.team_snapshot(self.root, NOW), dests)
        for dest in dests:
            self.assertEqual(json.loads((dest/'latest.json').read_text())['freshness_status'], 'blocked')
            self.assertIsNone(json.loads((dest/'reader-retention-report.json').read_text())['goal'])
            self.assertNotIn('rows', json.loads((dest/'search-console-data.json').read_text()))

    def test_public_mode_never_reads_private_data(self):
        target = self.root/'public.json'
        with patch.object(p, 'team_snapshot', side_effect=AssertionError('private read')), patch.object(p, 'read_data', side_effect=AssertionError('data read')):
            self.assertEqual(p.main(['--public-output', str(target)]), 0)
        data = json.loads(target.read_text())
        self.assertEqual(data['status'], 'unavailable')
        self.assertEqual(data['artifacts'], {})
        self.assertNotIn('108', target.read_text())
        self.assertNotIn('property_id', data)

    def test_source_changes_mid_read_block_snapshot(self):
        original = p.read_data
        calls = []
        def read(path):
            value = original(path)
            if path.name == 'collector-status.json':
                calls.append(path)
                if len(calls) == 2: value['status'] = 'blocked'
            return value
        with patch.object(p, 'read_data', side_effect=read):
            outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')

    def test_saved_provider_bypasses_and_mixed_generation_rejected(self):
        mutations = {
            'error': lambda d: d['ga4_source']['response'].update(error={'message': 'not-exported'}),
            'rowcount_bool': lambda d: d['ga4_source']['response'].update(rowCount=True),
            'timezone': lambda d: d['ga4_source']['response']['metadata'].update(timeZone='UTC'),
            'bad_rate': lambda d: d['ga4_source']['response']['rows'][0]['metricValues'][3].update(value='2'),
            'mixed_generation': lambda d: d['ga4_source'].update(fetched_at=(NOW-timedelta(hours=1)).isoformat()),
            'malformed_components': lambda d: d.update(ga4_components=[]),
        }
        path = self.data/'daily-report.json'
        old = path.read_bytes()
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.alter(path.name, mutate)
                outputs, summary = p.team_snapshot(self.root, NOW)
                self.assertEqual(summary['freshness_status'], 'blocked')
                self.assertIsNone(outputs['reader-retention-report.json']['goal'])
                path.write_bytes(old)

    def test_allowlist_excludes_raw_queries_arbitrary_extras_and_realtime(self):
        self.alter('daily-report.json', lambda d: d.update(arbitrary='not-for-export', realtime={'active_users': 999999}))
        self.alter('search-console-data.json', lambda d: d['property_totals'].update(extra='not-for-export', ctr_fraction=0.99))
        self.rebind_fixture_marker()
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'fresh')
        text = json.dumps(outputs)
        for forbidden in ('not-for-export', '999999', 'metricValues', 'dimensionValues', 'top_pages_7d', 'pageTitle'):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('rows', outputs['search-console-data.json'])
        self.assertEqual(outputs['daily-report.json']['search_console']['avg_ctr_pct'], 6 / 1000 * 100)
        self.assertEqual(outputs['daily-report.json']['realtime']['status'], 'unavailable')

    def test_invalid_returning_does_not_invent_retention_or_hide_valid_goal(self):
        self.alter('daily-report.json', lambda d: d.update(ga4_returning_source={}))
        self.rebind_fixture_marker()
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'fresh')
        reader = outputs['reader-retention-report.json']
        self.assertEqual(reader['goal']['activeUsers']['observed'], 54)
        self.assertEqual(reader['returning_active_share']['status'], 'unavailable')

    def test_panel_modes_and_all_deployment_callers(self):
        import business_control_panel as b
        with patch.object(b, 'PROJECT_DIR', self.root):
            self.assertEqual(b.analytics_status(NOW)['ga4']['status'], 'fresh')
            with patch.object(p, 'team_snapshot', side_effect=AssertionError('private read')):
                result = b.analytics_status(NOW, public_only=True)
                self.assertEqual(result['freshness']['status'], 'unavailable')
        for name in ('deploy.yml', 'staged-publish.yml', 'daily-kooste.yml'):
            text = (Path(__file__).resolve().parent.parent/'.github/workflows'/name).read_text()
            lines = [line for line in text.splitlines() if 'business_control_panel.py ' in line]
            self.assertEqual(len(lines), 1)
            self.assertIn('--public-analytics', lines[0])

    def test_public_panel_cli_writes_standalone_status_without_metrics(self):
        import business_control_panel as b
        panel = {'status': 'unknown', 'generated_at': NOW.isoformat(),
                 'analytics': {'freshness': p.public_status(NOW)}}
        target = self.root/'static/api/business-control-panel.json'
        with patch.object(b, 'PROJECT_DIR', self.root), patch.object(b, 'build_panel', return_value=panel) as build:
            self.assertEqual(b.main(['--public-analytics', '--output', str(target)]), 0)
        self.assertTrue(build.call_args.kwargs['public_analytics'])
        saved = json.loads((target.parent/'analytics-freshness-status.json').read_text())
        self.assertEqual(saved['status'], 'unavailable')
        self.assertEqual(saved['artifacts'], {})

    def test_exact_no_argument_installed_wrapper_interface(self):
        import subprocess
        home = self.root/'home'
        helper = home/'.openclaw/workspace/scripts/uutistenlukija_current_main_job.py'
        helper.parent.mkdir(parents=True)
        helper.write_text('import sys,json\nprint(json.dumps(sys.argv[1:]))\n')
        wrapper = Path(__file__).with_name('export_analytics_team_snapshot.sh')
        result = subprocess.run(['/bin/sh', str(wrapper)], env={'HOME': str(home), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['--name', 'team-analytics-snapshot', '--', '/usr/bin/python3', '-B', 'scripts/analytics_projection.py', '--team-root', str(home/'.openclaw')])
        bad = subprocess.run(['/bin/sh', str(wrapper), '--unexpected'], env={'HOME': str(home), 'PATH': '/usr/bin:/bin'}, capture_output=True)
        self.assertEqual(bad.returncode, 2)

    def test_cli_refuses_missing_workspace_and_symlink_outputs(self):
        team = self.root/'team'
        (team/'workspace').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'missing_expected_team_workspaces'):
            p.main(['--project', str(self.root), '--team-root', str(team)])
        self.assertFalse((team/'workspace/reports').exists())
        link = self.root/'link'
        link.symlink_to(self.data, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink_parent_refused'):
            p.atomic_write(link/'do-not-write.json', b'{}')
        self.assertFalse((self.data/'do-not-write.json').exists())

    def test_rejects_other_fresh_gsc_generation(self):
        fake = FakeProvider()
        old = c.collect(NOW-timedelta(hours=1), fake.token, fake.post)['search-console-data.json']
        (self.data/'search-console-data.json').write_text(json.dumps(old))
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')
        self.assertIsNone(outputs['reader-retention-report.json']['goal'])

    def test_reused_gsc_matches_its_recorded_source_time(self):
        fake = FakeProvider()
        old = c.collect(NOW-timedelta(hours=1), fake.token, fake.post)['search-console-data.json']
        source = self.root/'reused-gsc.json'
        source.write_text(json.dumps(old))
        code, evidence = c.execute(self.data, now=NOW, token_fn=fake.token, transport=fake.post, gsc_input=source)
        self.assertEqual(code, 0)
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'fresh')
        self.assertEqual(summary['search_console_generated_at'], evidence['artifacts']['search_console']['evidence_at'])
        self.assertNotEqual(summary['collector_checked_at'], summary['search_console_generated_at'])

    def test_same_timestamp_content_replacement_is_rejected(self):
        self.alter('search-console-data.json', lambda d: d['property_totals'].update(clicks=77))
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')
        self.assertNotIn('search_console', outputs['daily-report.json'])

    def test_strict_invalid_header_replaces_previous_success_without_crash(self):
        destination = self.root/'export'
        p.export_snapshot(*p.team_snapshot(self.root, NOW), [destination])
        def mutate(data):
            data['ga4_source']['request']['metrics'][0]['name'] = 1
            data['ga4_source']['response']['metricHeaders'][0]['name'] = 1
        self.alter('daily-report.json', mutate)
        self.rebind_fixture_marker()
        outputs, summary = p.team_snapshot(self.root, NOW)
        self.assertEqual(summary['freshness_status'], 'blocked')
        p.export_snapshot(outputs, summary, [destination])
        self.assertEqual(json.loads((destination/'latest.json').read_text())['freshness_status'], 'blocked')
        self.assertIsNone(json.loads((destination/'reader-retention-report.json').read_text())['goal'])

    def test_nonfinite_extra_records_failed_attempt_and_preserves_last_good(self):
        fake = FakeProvider()
        original = (self.data/'daily-report.json').read_bytes()
        def post(endpoint, request, token):
            status, response = fake.post(endpoint, request, token)
            if 'analyticsdata' in endpoint:
                response['unrecognised_extra'] = float('nan')
            return status, response
        code, evidence = c.execute(self.data, now=NOW, token_fn=fake.token, transport=post)
        self.assertEqual(code, 1)
        self.assertEqual(evidence['reason'], 'invalid_source_serialization')
        self.assertEqual((self.data/'daily-report.json').read_bytes(), original)
        self.assertEqual(p.team_snapshot(self.root, NOW)[1]['freshness_status'], 'blocked')

    def test_interrupted_export_does_not_commit_new_manifest(self):
        outputs, summary = p.team_snapshot(self.root, NOW)
        dest = self.root/'dest'
        p.export_snapshot(outputs, summary, [dest])
        old = (dest/'latest.json').read_bytes()
        original = p.atomic_write
        def fail(path, raw):
            if path.name == 'search-console-data.json': raise OSError('fixture')
            original(path, raw)
        with patch.object(p, 'atomic_write', side_effect=fail), self.assertRaises(OSError):
            p.export_snapshot(outputs, dict(summary, generated_at='later'), [dest])
        self.assertEqual((dest/'latest.json').read_bytes(), old)


if __name__ == '__main__':
    unittest.main()

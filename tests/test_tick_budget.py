import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp import publish as pub
from news_mvp.controller import ingest, load_config
from news_mvp.editorial import ROOT, FixtureModel, digest
from news_mvp.store import database


class TickBudget(unittest.TestCase):
    """28 Oct: systemd killed a tick mid-upload at its 30 min timeout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config_path = root / 'config.json'
        self.config_path.write_text(json.dumps({'enabled': True, 'backend': 'fixture',
                                                'state_dir': str(root / 'state'), 'output_dir': str(root / 'private')}))
        self.config = load_config(self.config_path)
        packet = json.loads((ROOT / 'fixtures/source-packet.json').read_text())
        self.jid = ingest(self.config, packet, datetime(2026, 9, 12, 12, tzinfo=timezone.utc))['id']
        draft = FixtureModel().call('writer', packet)
        draft['image'] = {'sha256': 'a'*64, 'local_path': 'media/'+'a'*64+'.jpg', 'url': 'https://example.invalid/i.jpg',
                          'source_url': 'https://example.invalid/s', 'license_url': 'https://example.invalid/r',
                          'license': 'isolated test rights', 'alt': 'Test', 'credit': 'Test'}
        packet = copy.deepcopy(packet); packet['image'] = draft['image']; packet['fixture'] = False
        self.job = {'id': self.jid, 'packet': json.dumps(packet), 'draft': json.dumps(draft),
                    'review': json.dumps({'approved': True, 'draft_sha256': digest(draft), 'reasons': ['t']})}
        self.packet, self.draft = packet, draft
        self.addCleanup(pub.set_deadline, None)

    def _row(self, store):
        pub.ensure_table(store)
        store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',
                         (self.jid, digest(self.packet), digest(self.draft), 'a'*64, 'source', 'preparing')); store.db.commit()

    def test_budget_stop_during_upload_refunds_attempt_and_returns_cleanly(self):
        with database(self.config['state_dir']) as store:
            self._row(store)
            with patch('news_mvp.publish.guard'), patch('news_mvp.publish.cmd', return_value='source'), \
                 patch('news_mvp.publish.public_bundle', return_value=(None, {})), \
                 patch('news_mvp.publish.make_commit', side_effect=pub.PreparationDeferred('budget')):
                for _ in range(5):
                    result = pub.publish(store, self.job, self.config['state_dir'], self.config_path)
                    self.assertEqual(result['status'], 'preparation_continues')
            row = store.db.execute('SELECT status,attempts,remote_commit,error FROM publications').fetchone()
            self.assertEqual((row[0], row[1], row[2]), ('preparing', 0, None))
            self.assertTrue(row[3].startswith('Deferred:'))

    def test_expired_budget_skips_bundle_without_burning_attempt(self):
        pub.set_deadline(0)
        with database(self.config['state_dir']) as store:
            self._row(store)
            with patch('news_mvp.publish.guard'), patch('news_mvp.publish.cmd', return_value='source'), \
                 patch('news_mvp.publish.public_bundle', side_effect=AssertionError('must not render')):
                self.assertEqual(pub.publish(store, self.job, self.config['state_dir'], self.config_path)['status'],
                                 'preparation_continues')
            self.assertEqual(store.db.execute('SELECT attempts FROM publications').fetchone()[0], 0)

    def test_blob_upload_stops_at_deadline_before_any_request(self):
        pub.set_deadline(0)
        with tempfile.TemporaryDirectory() as d:
            site = Path(d) / 'live-site'; site.mkdir(); (site / 'a.html').write_text('x')
            with patch('news_mvp.publish.api', return_value={'object': {'sha': 'p'}, 'tree': {'sha': 't'}}), \
                 patch('news_mvp.publish.upload_blob', side_effect=AssertionError('must not upload')):
                with self.assertRaises(pub.PreparationDeferred):
                    pub.make_commit(site, {'files': ['a.html'], 'job_id': 'x'})

    def test_budget_is_below_systemd_start_timeout(self):
        unit = (ROOT / 'systemd/uutistenlukija-mvp.service').read_text()
        self.assertIn('TimeoutStartSec=30min', unit)
        self.assertLessEqual(pub.TICK_BUDGET_SECONDS, 25 * 60)

    def test_live_tick_sets_and_clears_deadline(self):
        from news_mvp import live
        seen = []
        with patch('news_mvp.live._live_tick', side_effect=lambda p: seen.append(pub._deadline) or {'status': 'idle'}):
            live.live_tick('unused')
        self.assertIsNotNone(seen[0]); self.assertIsNone(pub._deadline)


if __name__ == '__main__':
    unittest.main()


class UpstreamOutage(TickBudget):
    """30 Oct: GitHub disruption returned HTTP 500 for git/blobs; must not burn attempts."""

    REAL = 'RuntimeError: GitHub POST git/blobs: HTTP 500 '

    def test_github_500_refunds_attempt_and_is_bounded(self):
        with database(self.config['state_dir']) as store:
            self._row(store)
            with patch('news_mvp.publish.guard'), patch('news_mvp.publish.cmd', return_value='source'), \
                 patch('news_mvp.publish.public_bundle', return_value=(None, {})), \
                 patch('news_mvp.publish.make_commit', side_effect=pub.UncommittedPreparationError(self.REAL)):
                for n in range(1, pub.TRANSIENT_OUTAGE_TICKS + 1):
                    result = pub.publish(store, self.job, self.config['state_dir'], self.config_path)
                    self.assertEqual(result['status'], 'preparation_continues')
                    row = store.db.execute('SELECT status,attempts,error FROM publications').fetchone()
                    self.assertEqual((row[0], row[1]), ('preparing', 0))
                    self.assertTrue(row[2].startswith(f'Transient {n}: '))
                # bound reached: ordinary attempt counting resumes and raises
                with self.assertRaises(pub.UncommittedPreparationError):
                    pub.publish(store, self.job, self.config['state_dir'], self.config_path)
                self.assertEqual(store.db.execute('SELECT attempts FROM publications').fetchone()[0], 1)

    def test_non_outage_error_still_counts(self):
        with database(self.config['state_dir']) as store:
            self._row(store)
            with patch('news_mvp.publish.guard'), patch('news_mvp.publish.cmd', return_value='source'), \
                 patch('news_mvp.publish.public_bundle', return_value=(None, {})), \
                 patch('news_mvp.publish.make_commit', side_effect=pub.UncommittedPreparationError('RuntimeError: GitHub POST git/blobs: HTTP 422 bad')):
                with self.assertRaises(pub.UncommittedPreparationError):
                    pub.publish(store, self.job, self.config['state_dir'], self.config_path)
            self.assertEqual(store.db.execute('SELECT attempts FROM publications').fetchone()[0], 1)

"""Synthetic portable public_bundle tests; no canonical state or uploads."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from news_mvp import publish
from cutover.check_release import check
from tests.test_amendment_release_consumer import portable_amendment
from tests.test_amendment_renderer import amendment_job, ordinary_job, stale_policy_amendment, IMAGE_BYTES

BUILD_REF = 'a' * 40

class Store:
    def __init__(self, jobs):
        self.jobs = jobs
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE publications(job_id TEXT,status TEXT)')
        self.db.execute('CREATE TABLE jobs(id TEXT,created_at TEXT,draft TEXT)')
        for job in jobs:
            self.db.execute('INSERT INTO publications VALUES (?,?)', (job['id'], 'deployed'))
            self.db.execute('INSERT INTO jobs VALUES (?,?,?)', (job['id'], job['created_at'], job['draft']))
    def articles(self): return self.jobs
    def mark_rendered(self, ids): pass

class AmendmentBundleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.packet, self.draft = portable_amendment()
        self.job = amendment_job(self.packet, self.draft)
        path = self.state / self.draft['image']['local_path']
        path.parent.mkdir(parents=True)
        path.write_bytes(IMAGE_BYTES)
        self.store = Store([self.job])
        self.addCleanup(self.store.db.close)

    def bundle(self, store=None, job=None):
        with patch('news_mvp.backfill.release_records', return_value=[]), patch.object(publish, 'cmd', return_value=BUILD_REF):
            return publish.public_bundle(store or self.store, job or self.job, self.state)

    def test_actual_renderer_and_hosted_check_emit_v3_with_actual_build_ref(self):
        with patch('news_mvp.amendment_preparation._reconstruct', autospec=True) as reconstruct:
            output, receipt = self.bundle()
        self.assertEqual(receipt['schema_version'], 3)
        self.assertEqual(receipt['source_commit'], BUILD_REF)
        self.assertNotEqual(BUILD_REF, self.packet['final_review_result']['source_ref'])
        self.assertEqual(check(output, receipt), len(receipt['files']))
        captures = self.packet['final_review_input']['source_packet']['preparation']['captures']
        self.assertEqual(reconstruct.call_count, 2)
        for call, role in zip(reconstruct.call_args_list, ('original','update')):
            raw = self.packet['capture_json'][role]
            self.assertEqual(call.args, (captures[role]['packet'], captures[role]['validation_draft'], raw['packet'].encode(), raw['receipt'].encode(), self.state))
            self.assertEqual(call.kwargs, {})
        metadata = self.packet['final_review_input']['source_packet']['public_metadata']
        self.assertIn('<lastmod>'+metadata['dateModified']+'</lastmod>', (output/'sitemap.xml').read_text())
        self.assertEqual(receipt['packet'], self.packet)
        self.assertEqual(receipt['draft'], self.draft)
        self.assertEqual(receipt['review'], json.loads(self.job['review']))

    def test_either_capture_failure_refuses_before_render(self):
        for role_index in (0, 1):
            with self.subTest(role_index=role_index):
                outcomes = [None, None]
                outcomes[role_index] = ValueError('Synthetic reconstruction refusal')
                with patch('news_mvp.amendment_preparation._reconstruct', autospec=True, side_effect=outcomes):
                    with self.assertRaisesRegex(ValueError, 'Synthetic reconstruction refusal'):
                        self.bundle()
                self.assertFalse((self.state/'live-site').exists())

    def test_wrong_row_review_and_backfill_mix_refuse_before_render(self):
        wrong = copy.deepcopy(self.job)
        wrong['review'] = json.dumps(json.loads(wrong['review']) | {'reasons':['unreviewed']})
        with self.assertRaisesRegex(ValueError, 'row review'):
            self.bundle(job=wrong)
        with patch('news_mvp.backfill.release_records', return_value=[{'job_id': self.job['id']}]), patch.object(publish, 'cmd', return_value=BUILD_REF):
            with self.assertRaisesRegex(ValueError, 'cannot share'):
                publish.public_bundle(self.store, self.job, self.state)
        self.assertFalse((self.state/'live-site').exists())

    def test_ordinary_next_release_preserves_amended_lastmod_and_intake(self):
        ordinary, _sha = ordinary_job(b'ordinary synthetic image bytes')
        path = self.state/json.loads(ordinary['draft'])['image']['local_path']
        path.write_bytes(b'ordinary synthetic image bytes')
        store = Store([self.job, ordinary])
        self.addCleanup(store.db.close)
        with patch('news_mvp.amendment_preparation._reconstruct', autospec=True) as reconstruct:
            output, receipt = self.bundle(store, ordinary)
        self.assertEqual(reconstruct.call_count, 2)
        self.assertNotEqual(receipt.get('schema_version'), 3)
        metadata = self.packet['final_review_input']['source_packet']['public_metadata']
        self.assertIn('<loc>'+metadata['canonical']+'</loc><lastmod>'+metadata['dateModified']+'</lastmod>', (output/'sitemap.xml').read_text())

    def test_archived_amendment_policy_drift_refuses_before_render(self):
        old, draft = stale_policy_amendment()
        archived = amendment_job(old, draft)
        ordinary, _sha = ordinary_job(b'ordinary synthetic image bytes')
        store = Store([archived, ordinary])
        self.addCleanup(store.db.close)
        with patch('news_mvp.amendment_preparation._reconstruct', autospec=True) as reconstruct:
            with self.assertRaisesRegex(ValueError, 'Missing exact text-only policy'):
                self.bundle(store, ordinary)
        reconstruct.assert_not_called()
        self.assertFalse((self.state/'live-site').exists())

if __name__ == '__main__': unittest.main()

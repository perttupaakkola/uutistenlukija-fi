"""Offline consumer boundaries; synthetic rows are not activation authority."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from news_mvp import publish as pub
from news_mvp.editorial import digest
from news_mvp.release_contract import media
from tests.test_amendment_release_consumer import ordinary, portable_amendment


class PublicationConsumerGateTests(unittest.TestCase):
    def store_job(self, packet, draft, status: str | None = 'dispatched'):
        store = SimpleNamespace(db=sqlite3.connect(':memory:'))
        self.addCleanup(store.db.close)
        store.db.row_factory = sqlite3.Row
        pub.ensure_table(store)
        binding = media(packet, draft)
        review = packet.get('final_review_result', {}).get('review') or {
            'approved': True, 'draft_sha256': digest(draft), 'reasons': ['Synthetic only']}
        job = {'id': 'b'*64, 'packet': json.dumps(packet), 'draft': json.dumps(draft),
               'review': json.dumps(review)}
        if status is not None:
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,run_id,status) VALUES(?,?,?,?,?,?,?,?)',
                (job['id'], digest(packet), digest(draft), binding['image_sha256'], 'c'*40, 'd'*40, 123, status))
            store.db.commit()
        return store, job, binding

    def test_ordinary_actual_post_hosted_consumer_refuses_foreign_amendment_before_readback(self):
        packet, draft, _ = ordinary()
        store, job, binding = self.store_job(packet, draft)
        live = {'remote_commit': 'd'*40, 'packet_sha256': digest(packet),
                'draft_sha256': digest(draft), 'image_sha256': binding['image_sha256'],
                'amendment': None}
        with tempfile.TemporaryDirectory() as state:
            directory = Path(state)/'deployments'/'123'
            directory.mkdir(parents=True)
            (directory/'live-deployment.json').write_text(json.dumps(live))
            with patch.object(pub, 'guard'), patch.object(pub, 'cmd', return_value='c'*40), \
                 patch.object(pub, 'api', side_effect=AssertionError('No provider API')), \
                 patch.object(pub, 'matching_runs', return_value=[{'databaseId': 123, 'status': 'completed', 'conclusion': 'success'}]), \
                 patch.object(pub.urllib.request, 'urlopen', side_effect=AssertionError('No canonical read')) as read:
                with self.assertRaisesRegex(ValueError, 'Deployment amendment binding mismatch'):
                    pub.publish(store, job, state, 'unused')
                read.assert_not_called()
            self.assertFalse((directory/'live-readback.json').exists())
        self.assertNotEqual(store.db.execute('SELECT status FROM publications').fetchone()[0], 'deployed')
    def test_amendment_admission_and_reconciliation_fail_closed_without_row_writes(self):
        packet, draft = portable_amendment()
        for status in (None, 'preparing', 'dispatched', 'deployed'):
            with self.subTest(status=status):
                store, job, _ = self.store_job(packet, draft, status)
                before = list(map(tuple, store.db.execute('SELECT * FROM publications')))
                with patch.object(pub, 'guard'), \
                     patch.object(pub, 'cmd', side_effect=AssertionError('No command')), \
                     patch.object(pub, 'api', side_effect=AssertionError('No API')), \
                     patch.object(pub, 'matching_runs', side_effect=AssertionError('No provider reconciliation')), \
                     patch.object(pub.urllib.request, 'urlopen', side_effect=AssertionError('No canonical read')):
                    with self.assertRaisesRegex(ValueError, 'Amendment publication version ownership is not installed'):
                        pub.publish(store, job, 'unused', 'unused')
                self.assertEqual(before, list(map(tuple, store.db.execute('SELECT * FROM publications'))))

    def test_original_deployed_predecessor_identity_refusal_is_preserved(self):
        packet, draft = portable_amendment()
        store, job, _ = self.store_job(packet, draft, 'deployed')
        store.db.execute("UPDATE publications SET packet_sha=?", ('e'*64,))
        store.db.commit()
        before = list(map(tuple, store.db.execute('SELECT * FROM publications')))
        with patch.object(pub, 'guard'), patch.object(pub, 'cmd', return_value='c'*40):
            with self.assertRaisesRegex(ValueError, '^Publication packet changed$'):
                pub.publish(store, job, 'unused', 'unused')
        self.assertEqual(before, list(map(tuple, store.db.execute('SELECT * FROM publications'))))

    def test_exact_amendment_hosted_helper_positive_missing_changed_and_no_mutation(self):
        packet, draft = portable_amendment()
        binding = media(packet, draft)
        live = copy.deepcopy(binding)
        before = copy.deepcopy((live, binding))
        pub.check_deployment_amendment(live, binding)
        self.assertEqual((live, binding), before)
        for mutation in ('missing', 'null', 'version', 'predecessor'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(live)
                if mutation == 'missing':
                    changed.pop('amendment')
                elif mutation == 'null':
                    changed['amendment'] = None
                elif mutation == 'version':
                    changed['amendment']['version']['id'] = 'sha256:'+'0'*64
                else:
                    changed['amendment']['version']['predecessor']['predecessor_packet_sha256'] = '0'*64
                with self.assertRaisesRegex(ValueError, 'Deployment amendment binding mismatch'):
                    pub.check_deployment_amendment(changed, binding)
        # Neither field is required on ordinary or legacy hosted receipts.
        pub.check_deployment_amendment({}, {'image_sha256': 'a'*64})

    def test_ordinary_actual_post_hosted_consumer_still_terminalizes_after_exact_readback(self):
        import hashlib
        import io
        from html import escape
        packet, draft, _ = ordinary()
        image = b'synthetic ordinary image bytes'
        draft['image']['sha256'] = hashlib.sha256(image).hexdigest()
        draft['image']['local_path'] = 'media/'+draft['image']['sha256']+'.jpg'
        packet['sources'][0]['url'] = 'https://example.org/source'
        store, job, binding = self.store_job(packet, draft)
        canonical = 'https://uutistenlukija.fi/'+pub.article_path(job)
        required = [draft['title'], draft['summary'], *[p['text'] for p in draft['paragraphs']],
                    packet['sources'][0]['url'], draft['image']['license_url'], draft['image']['license']]
        html = ('<link rel="canonical" href="'+canonical+'">'+''.join('<p>'+escape(x)+'</p>' for x in required)).encode()
        live = {'remote_commit': 'd'*40, 'packet_sha256': digest(packet), 'draft_sha256': digest(draft),
                'image_sha256': binding['image_sha256'], 'deployment_id': 'synthetic-only'}
        with tempfile.TemporaryDirectory() as state:
            directory = Path(state)/'deployments'/'123'
            directory.mkdir(parents=True)
            (directory/'live-deployment.json').write_text(json.dumps(live))
            with patch.object(pub, 'guard'), patch.object(pub, 'cmd', return_value='c'*40), \
                 patch.object(pub, 'api', side_effect=AssertionError('No provider API')), \
                 patch.object(pub, 'matching_runs', return_value=[{'databaseId': 123, 'status': 'completed', 'conclusion': 'success'}]), \
                 patch.object(pub.urllib.request, 'urlopen', side_effect=lambda request, timeout: io.BytesIO(image if request.full_url.endswith('.jpg') else html)), \
                 patch('news_mvp.backfill.release_records', return_value=[]), \
                 patch('news_mvp.backfill.complete'), patch('news_mvp.indexing.ping'):
                result = pub.publish(store, job, state, 'unused')
            self.assertEqual(result['status'], 'deployed')
            saved = json.loads((directory/'live-readback.json').read_text())
            self.assertEqual(saved['live_html_sha256'], hashlib.sha256(html).hexdigest())
            self.assertEqual(saved['live_image_sha256'], binding['image_sha256'])
        self.assertEqual(store.db.execute('SELECT status FROM publications').fetchone()[0], 'deployed')


if __name__ == '__main__':
    unittest.main()

import unittest
from news_mvp.publish import ref_update_retry_count, REF_UPDATE_RETRY_LIMIT

# Exact error stored for article f8bf45e1 on 24 Nov 2026. GitHub acknowledged, but never
# stored, the tests/ tree containing the first version of this file; any content change
# gives a new tree object.
REAL = 'RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 500 '


class RefUpdateRetry(unittest.TestCase):
    def test_real_http_500_is_retried_and_counted(self):
        self.assertEqual(ref_update_retry_count(None, REAL), 1)
        self.assertEqual(ref_update_retry_count('RefUpdateRetry 3: '+REAL, REAL), 4)

    def test_retry_is_bounded(self):
        last = f'RefUpdateRetry {REF_UPDATE_RETRY_LIMIT}: '+REAL
        self.assertIsNone(ref_update_retry_count(last, REAL))

    def test_real_object_lag_422_is_retried(self):
        self.assertEqual(ref_update_retry_count(None,
            'RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 422 ValueError: {"message": "Object does not exist"}'), 1)

    def test_non_fast_forward_conflict_is_not_retried(self):
        self.assertIsNone(ref_update_retry_count(None,
            'RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 422 {"message": "Update is not a fast forward"}'))

    def test_dispatch_marker_is_not_mistaken_for_retry_count(self):
        self.assertEqual(ref_update_retry_count('Dispatched 2026-11-24T03:00:00+00:00 lost=0', REAL), 1)

    def test_retry_branch_is_installed_in_publish(self):
        import inspect, news_mvp.publish as p
        src = inspect.getsource(p.publish)
        self.assertIn('ref_update_retry_count', src)
        self.assertIn("'ref_update_retry'", src)


class OrphanCommit(unittest.TestCase):
    """24 Nov real case: commit ac6bf17b existed but its tree 7fee2750 was 404 on GitHub."""

    def run_gh(self, answers):
        from unittest.mock import patch
        import subprocess, news_mvp.publish as p
        results=[subprocess.CompletedProcess([],a[0],a[1],a[2]) for a in answers]
        with patch('news_mvp.publish.api',return_value={'tree':{'sha':'7fee2750ecc91d360d859ad7524bb59bb937a75d'}}), \
             patch('news_mvp.publish.subprocess.run',side_effect=results), patch('news_mvp.publish.time.sleep'):
            return p.commit_tree_missing('ac6bf17ba58b8ae617ef268f77f972a4b4f33bc1')

    def test_real_missing_tree_is_detected(self):
        nf=(1,'','{"message":"Not Found"}gh: Not Found (HTTP 404)')
        self.assertTrue(self.run_gh([nf,nf,nf]))

    def test_readable_tree_or_network_error_keeps_commit(self):
        nf=(1,'','gh: Not Found (HTTP 404)')
        self.assertFalse(self.run_gh([nf,(0,'7fee2750ecc91d360d859ad7524bb59bb937a75d\n','')]))
        self.assertFalse(self.run_gh([(1,'','error connecting to api.github.com')]))

    def test_rebuild_is_bounded(self):
        from news_mvp.publish import orphan_rebuild_count, ORPHAN_REBUILD_LIMIT
        self.assertEqual(orphan_rebuild_count('RefUpdateRetry 2: RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 500'),1)
        self.assertEqual(orphan_rebuild_count('OrphanCommit 1: tree missing'),2)
        self.assertIsNone(orphan_rebuild_count(f'OrphanCommit {ORPHAN_REBUILD_LIMIT}: tree missing'))

    def test_rebuild_branch_installed(self):
        import inspect, news_mvp.publish as p
        src=inspect.getsource(p.publish)
        self.assertIn('commit_tree_missing(row', src)
        self.assertIn('remote_commit=NULL', src)


class CommitRefusedForLostTree(unittest.TestCase):
    def test_real_404_commit_refusal_is_a_definite_no_commit(self):
        from news_mvp.publish import is_missing_commit_tree
        self.assertTrue(is_missing_commit_tree('RuntimeError: GitHub POST git/commits: HTTP 404 ValueError: {"message": "Not Found"}'))
        self.assertFalse(is_missing_commit_tree('RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 404 '))

class StaleUploadCheckpoint(unittest.TestCase):
    """24 Nov: 8 blobs (e.g. public/oppaat/adventti-2026/index.html, 459b8711) had a local
    'uploaded' checkpoint ~1 h old but GitHub had dropped them; they were skipped."""

    def test_old_checkpoint_is_reuploaded_young_or_reachable_is_skipped(self):
        import os, tempfile, time
        from pathlib import Path
        from unittest.mock import patch
        import news_mvp.publish as p
        data=b'adventti page'
        sha=__import__('hashlib').sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            site=Path(d)/'live-site';site.mkdir()
            ck=Path(d)/'uploaded-git-blobs';ck.mkdir();(ck/sha).write_text(sha+'\n')
            calls=[]
            def api(path,body=None,method=None):
                calls.append(path);return {'sha':sha}
            with patch('news_mvp.publish.api',side_effect=api):
                p.upload_blob(site,data);self.assertEqual(calls,[])
                old=time.time()-p.CHECKPOINT_TRUST_SECONDS-60;os.utime(ck/sha,(old,old))
                p.upload_blob(site,data,reachable=frozenset({sha}));self.assertEqual(calls,[])
                p.upload_blob(site,data);self.assertEqual(calls,['git/blobs'])

    def test_repeated_ref_failure_triggers_rebuild_and_rate_limit_is_transient(self):
        import inspect, news_mvp.publish as p
        src=inspect.getsource(p.publish)
        self.assertIn("int(previous.group(1))>=2", src)
        self.assertIn('distrust_checkpoints=bool(_ORPHAN.search', src)
        self.assertEqual(ref_update_retry_count(None,'RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 403 {"message": "API rate limit exceeded for user"}'),1)

class FreshCommitAndBound(unittest.TestCase):
    def test_fresh_commit_not_rebuilt_and_rebuild_count_carried(self):
        import inspect, news_mvp.publish as p
        src=inspect.getsource(p.publish)
        self.assertIn('if not external_started and rebuilds is not None', src)
        self.assertIn("carried=f'OrphanCommit {orphan.group(1)}: '", src)
        carried='RefUpdateRetry 1: OrphanCommit 2: RuntimeError: GitHub PATCH git/refs/heads/main: HTTP 500'
        self.assertEqual(p.orphan_rebuild_count(carried),3)
        self.assertIsNone(p.orphan_rebuild_count('RefUpdateRetry 2: OrphanCommit 3: x'))
        self.assertEqual(ref_update_retry_count(carried, REAL), 2)

if __name__ == '__main__':
    unittest.main()

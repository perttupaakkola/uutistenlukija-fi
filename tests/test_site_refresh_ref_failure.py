import unittest
from unittest.mock import patch
import json, subprocess
from pathlib import Path

import news_mvp.publish as p
from news_mvp.publish import ensure_table, ensure_site_refresh_table
from news_mvp.store import database
import test_site_refresh as base

FIX = json.loads((Path(__file__).parent/'fixtures'/'site_refresh_lost_subtree_20261124.json').read_text())
REAL = FIX['error']


class SiteRefreshRefFailure(unittest.TestCase):
    """24 Nov real case: refresh a52460bf's commit 239f18f0 lost subtree 'public' on GitHub;
    every fast-forward of main answered HTTP 500 and the refresh retried it forever."""

    setUp = base.SiteRefreshTests.setUp
    shell = base.SiteRefreshTests.shell

    def seed(self, error=None):
        with database(self.case.state) as store:
            ensure_table(store); ensure_site_refresh_table(store)
            store.db.execute("INSERT INTO site_refreshes VALUES('r1',?,?,?,NULL,'prepared',?,"
                             "'2026-11-24T07:16:06+00:00','x')",
                             (base.COMMIT, self.job['id'], FIX['commit'], error))
            store.db.commit()

    def tick(self, missing):
        def api(path, data=None, method=None):
            if path == 'git/ref/heads/main' and method is None:
                return {'object':{'sha':FIX['main']}}
            if path == 'git/refs/heads/main' and method == 'PATCH':
                raise RuntimeError('GitHub PATCH git/refs/heads/main: HTTP 500 ')
            raise AssertionError(path)
        with patch('news_mvp.publish.guard'), \
                patch('news_mvp.publish.cmd', side_effect=self.shell([])), \
                patch('news_mvp.publish.api', side_effect=api), \
                patch('news_mvp.publish.commit_objects_missing', return_value=missing) as check, \
                patch('news_mvp.publish.make_commit', return_value='n'*40):
            return p.site_refresh(self.case.config, self.case.cfg), check

    def row(self):
        with database(self.case.state) as store:
            return dict(store.db.execute("SELECT status,remote_commit,error FROM site_refreshes WHERE id='r1'").fetchone())

    def test_lost_objects_drop_commit_for_rebuild(self):
        self.seed(REAL)
        result, _ = self.tick(True)
        self.assertEqual(result['status'], 'preparation_continues')
        row = self.row()
        self.assertEqual((row['status'], row['remote_commit']), ('preparing', None))
        self.assertTrue(row['error'].startswith('OrphanCommit 1:'))

    def test_transient_500_is_counted_not_looped(self):
        self.seed(REAL)
        result, _ = self.tick(False)
        self.assertEqual(result['status'], 'ref_update_retry')
        self.assertTrue(self.row()['error'].startswith('RefUpdateRetry 1:'))

    def test_two_failed_retries_rebuild_even_if_check_is_unsure(self):
        self.seed('RefUpdateRetry 2: '+REAL)
        result, _ = self.tick(False)
        self.assertEqual(result['status'], 'preparation_continues')

    def test_exhausted_retries_become_unknown(self):
        self.seed(f'RefUpdateRetry {p.REF_UPDATE_RETRY_LIMIT}: OrphanCommit {p.ORPHAN_REBUILD_LIMIT}: '+REAL)
        with self.assertRaises(RuntimeError):
            self.tick(False)
        self.assertEqual(self.row()['status'], 'unknown')


class LostSubtreeDetection(unittest.TestCase):
    def test_real_lost_public_subtree_is_detected(self):
        trees = FIX['trees']
        def api(path, data=None, method=None):
            if path == 'git/ref/heads/main': return {'object':{'sha':FIX['main']}}
            if path.startswith('git/commits/'):
                return {'tree':{'sha':FIX['commit_tree'] if path.endswith(FIX['commit']) else FIX['main_tree']}}
            return {'tree':trees[path.split('/')[-1]]}
        def run(args, **kw):
            sha = args[2].split('/')[-1]
            if sha in FIX['lost']:
                return subprocess.CompletedProcess(args, 1, '', 'gh: Not Found (HTTP 404)')
            return subprocess.CompletedProcess(args, 0, sha+'\n', '')
        with patch('news_mvp.publish.api', side_effect=api), \
                patch('news_mvp.publish.subprocess.run', side_effect=run), \
                patch('news_mvp.publish.time.sleep'):
            self.assertFalse(p.commit_tree_missing(FIX['commit']))
            self.assertTrue(p.commit_objects_missing(FIX['commit']))
            FIX['lost'].clear()
            self.assertFalse(p.commit_objects_missing(FIX['commit']))


if __name__ == '__main__':
    unittest.main()

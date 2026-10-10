import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from cutover.check_release import check
from news_mvp.editorial import digest
from news_mvp.publish import (ensure_table, publish, public_bundle, site_refresh)
from news_mvp.release_contract import deployment_record, media
from news_mvp.site import article_path
from news_mvp.store import database
import test_release_v2 as release_v2

COMMIT = release_v2.COMMIT
REMOTE = release_v2.REMOTE


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SiteRefreshTests(unittest.TestCase):
    def setUp(self):
        # Reuse the release suite's fully reviewed, image-bearing synthetic article.
        self.case = release_v2.ReleaseV2(
            'test_text_and_image_full_actual_publish_workflow_canonical_next_tick')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.job, self.image_sha = self.case.image_job()
        packet, draft = json.loads(self.job['packet']), json.loads(self.job['draft'])
        with database(self.case.state) as store:
            ensure_table(store)
            store.db.execute(
                "INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,"
                "remote_commit,run_id,status) VALUES(?,?,?,?,?,?,?,'deployed')",
                (self.job['id'],digest(packet),digest(draft),self.image_sha,COMMIT,REMOTE,7))
            store.db.commit()

    @staticmethod
    def api(path, data=None, method=None):
        if path == 'git/ref/heads/main':
            return {'object':{'sha':REMOTE}}
        raise AssertionError(('unfaked api',path,data,method))

    def shell(self, calls):
        def run(*args):
            calls.append(args)
            if args[:3] == ('git','rev-parse','HEAD'):
                return COMMIT
            if args[:3] in (('gh','workflow','enable'),('gh','workflow','run')):
                return ''
            raise AssertionError(('unfaked command',args))
        return run

    def dispatch(self, calls):
        with patch('news_mvp.publish.guard'), \
                patch('news_mvp.publish.cmd',side_effect=self.shell(calls)), \
                patch('news_mvp.publish.api',side_effect=self.api), \
                patch('news_mvp.publish.make_commit',return_value=REMOTE), \
                patch('news_mvp.publish.matching_runs',return_value=[]):
            return site_refresh(self.case.config,self.case.cfg)

    def test_refuses_dirty_source(self):
        with patch('news_mvp.publish.cmd',return_value=' M news_mvp/site.py'), \
                patch('news_mvp.publish.make_commit') as commit:
            with self.assertRaisesRegex(ValueError,'Commit source changes'):
                site_refresh(self.case.config,self.case.cfg)
        commit.assert_not_called()

    def test_refuses_unresolved_publications(self):
        with database(self.case.state) as store:
            store.db.execute("UPDATE publications SET status='preparing'")
            store.db.commit()
        with patch('news_mvp.publish.guard'):
            with self.assertRaisesRegex(ValueError,'Unresolved publications'):
                site_refresh(self.case.config,self.case.cfg)

    def test_bundle_uses_exact_anchor_and_preserves_article_html_and_dates(self):
        with database(self.case.state) as store, \
                patch('news_mvp.publish.cmd',return_value=COMMIT):
            baseline_site, _ = public_bundle(store,self.job,self.case.state)
            article = article_path(self.job)+'index.html'
            baseline = (baseline_site/article).read_bytes()
            site, receipt = public_bundle(store,self.job,self.case.state,site_refresh=True)
            self.assertEqual((site/article).read_bytes(),baseline)
            self.assertEqual(receipt['release_kind'],'site_refresh')
            self.assertEqual(receipt['new_article_files'],[])
            self.assertEqual(receipt['anchor_article_file'],article)
            self.assertEqual(receipt['packet_sha256'],digest(json.loads(self.job['packet'])))
            self.assertEqual(receipt['draft_sha256'],digest(json.loads(self.job['draft'])))
            self.assertEqual(receipt['image_sha256'],self.image_sha)
            self.assertEqual(receipt['style_sha256'],receipt['files']['mvp-assets/style.css'])
            self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_dispatch_is_exactly_once_across_interrupted_resume(self):
        calls=[]
        normal_shell=self.shell(calls)

        def interrupted(*args):
            result=normal_shell(*args)
            if args[:3] == ('gh','workflow','run'):
                raise RuntimeError('synthetic lost dispatch response')
            return result

        with patch('news_mvp.publish.guard'), \
                patch('news_mvp.publish.cmd',side_effect=interrupted), \
                patch('news_mvp.publish.api',side_effect=self.api), \
                patch('news_mvp.publish.make_commit',return_value=REMOTE), \
                patch('news_mvp.publish.matching_runs',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'lost dispatch response'):
                site_refresh(self.case.config,self.case.cfg)
        self.assertEqual(self.dispatch(calls)['status'],'awaiting_dispatch_visibility')
        self.assertEqual(sum(call[:3] == ('gh','workflow','run') for call in calls),1)
        with database(self.case.state) as store:
            row=store.db.execute('SELECT * FROM site_refreshes').fetchone()
            self.assertEqual((row['status'],row['remote_commit']),('dispatching',REMOTE))

    def test_completed_run_artifact_and_live_stylesheet_are_reconciled(self):
        calls=[]
        self.assertEqual(self.dispatch(calls)['status'],'dispatched')
        receipt=json.loads((self.case.state/'release.json').read_text())
        deployment={'id':'refresh-deployment','url':'https://refresh.pages.dev',
                    'environment':'production','latest_stage':{'status':'success'},
                    'deployment_trigger':{'metadata':{'commit_hash':REMOTE}}}
        record=deployment_record(receipt,deployment,REMOTE)
        artifact=self.case.state/'site-refresh-deployments/123/live-deployment.json'
        artifact.parent.mkdir(parents=True)
        artifact.write_text(json.dumps(record))

        def read(request, **kwargs):
            url=request.full_url
            if url == 'https://uutistenlukija.fi/':
                return Response((self.case.state/'live-site/index.html').read_bytes())
            if url == 'https://uutistenlukija.fi/mvp-assets/style.css':
                return Response((self.case.state/'live-site/mvp-assets/style.css').read_bytes())
            raise AssertionError(('unfaked read',url))

        run={'databaseId':123,'status':'completed','conclusion':'success','headSha':REMOTE}
        with patch('news_mvp.publish.guard'), \
                patch('news_mvp.publish.cmd',side_effect=self.shell(calls)), \
                patch('news_mvp.publish.api',side_effect=self.api), \
                patch('news_mvp.publish.matching_runs',return_value=[run]), \
                patch('urllib.request.urlopen',side_effect=read):
            result=site_refresh(self.case.config,self.case.cfg)
        self.assertEqual(result['status'],'deployed')
        self.assertEqual(result['deployment_id'],'refresh-deployment')
        with database(self.case.state) as store:
            self.assertEqual(store.db.execute('SELECT status FROM site_refreshes').fetchone()[0],
                             'deployed')
        readback=json.loads((artifact.parent/'live-readback.json').read_text())
        self.assertEqual(readback['live_style_sha256'],receipt['style_sha256'])

    def test_normal_publish_behavior_is_unchanged_without_active_refresh(self):
        with database(self.case.state) as store, patch('news_mvp.publish.guard'):
            result=publish(store,self.job,self.case.state,self.case.cfg)
        self.assertEqual(result,{'status':'idle','job_id':self.job['id'],
                                 'remote_commit':REMOTE})
        self.assertEqual(media(json.loads(self.job['packet']),json.loads(self.job['draft']))[
                             'image_sha256'],self.image_sha)


if __name__ == '__main__':
    unittest.main()

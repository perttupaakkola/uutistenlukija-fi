import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone

from news_mvp.controller import ingest,load_config
from news_mvp.editorial import ROOT,FixtureModel,digest
from news_mvp.live import live_tick
from news_mvp.publish import ensure_table,publish
from news_mvp.site import render_site
from news_mvp.store import database
from news_mvp.intake import ArticleHTML


class Publication(unittest.TestCase):
    def test_precommit_failure_retries_are_bounded_but_unknown_commit_stays_blocked(self):
        from news_mvp.publish import UncommittedPreparationError
        draft=FixtureModel().call('writer',self.packet)
        draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source','preparing'));store.db.commit()
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',return_value='source'),patch('news_mvp.publish.public_bundle',return_value=(None,{})),patch('news_mvp.publish.make_commit',side_effect=UncommittedPreparationError('tree timeout')) as commit:
                for attempt in range(1,4):
                    with self.assertRaises(UncommittedPreparationError):publish(store,job,self.config['state_dir'],self.config_path)
                    row=store.db.execute('SELECT * FROM publications').fetchone()
                    self.assertEqual((row['status'],row['attempts'],row['remote_commit']),('preparing',attempt,None))
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'publication_blocked')
                self.assertEqual(commit.call_count,3)
            with store.db:store.db.execute("UPDATE publications SET attempts=0,status='preparing'")
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',return_value='source'),patch('news_mvp.publish.public_bundle',return_value=(None,{})),patch('news_mvp.publish.make_commit',side_effect=RuntimeError('commit response lost')) as commit:
                with self.assertRaises(RuntimeError):publish(store,job,self.config['state_dir'],self.config_path)
                self.assertEqual(store.db.execute('SELECT status FROM publications').fetchone()[0],'unknown')
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['reason'],'Unknown remote commit outcome')
                self.assertEqual(commit.call_count,1)

    def test_source_image_description_is_preserved_only_inside_article(self):
        parser=ArticleHTML('entry-content')
        parser.feed('<img alt="site logo"><div class="entry-content"><p>Monterrey.</p><img alt="Light city and green mountain ridges"></div><img alt="unrelated promotion">')
        self.assertIn('Light city and green mountain ridges',parser.article_text())
        self.assertNotIn('site logo',parser.article_text())
        self.assertNotIn('unrelated promotion',parser.article_text())

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config_path=self.root/'config.json';self.config_path.write_text(json.dumps({'enabled':True,'backend':'fixture','state_dir':str(self.root/'state'),'output_dir':str(self.root/'private')}))
        self.config=load_config(self.config_path);self.packet=json.loads((ROOT/'fixtures/source-packet.json').read_text())
        self.job=ingest(self.config,self.packet,datetime(2026,9,12,12,tzinfo=timezone.utc))['id']

    def test_live_controller_and_public_renderer_refuse_fixtures(self):
        with self.assertRaises(ValueError):live_tick(self.config_path)
        draft=FixtureModel().call('writer',self.packet)
        with database(self.config['state_dir']) as store:
            store.save_draft(self.job,draft,'fixture');store.finish_review(self.job,{'approved':True,'draft_sha256':digest(draft),'reasons':['fixture only']})
            with self.assertRaises(ValueError):render_site(store,self.root/'public',self.config['state_dir'],public=True)
        self.assertFalse((self.root/'public/index.html').exists())

    def test_dispatch_visibility_delay_never_dispatches_twice(self):
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source','remote','prepared'));store.db.commit()
            calls=[]
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=lambda *args:calls.append(args) or 'source'),patch('news_mvp.publish.api',return_value={'object':{'sha':'remote'}}),patch('news_mvp.publish.matching_runs',return_value=[]):
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
            self.assertEqual(sum(args[:3]==('gh','workflow','run') for args in calls),1)
            self.assertEqual(store.db.execute('SELECT count(*) FROM publications').fetchone()[0],1)

    def test_refused_dispatch_returns_to_prepared_and_redispatches_bounded(self):
        # 4 Nov 2026 real case: article 5a0d3abc, commit pushed, `gh workflow run`
        # exited 1 during a GitHub incident; row stuck in 'unknown' awaiting a run forever.
        import subprocess
        from news_mvp import publish as pub
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source','a3d44b042e0dddf3a4117e2db88df3dbdd697f8f','prepared'));store.db.commit()
            calls=[]
            def refusing(*args):
                calls.append(args)
                if args[:3]==('gh','workflow','run'):raise subprocess.CalledProcessError(1,args,output='',stderr='HTTP 503: Service Unavailable')
                return 'source'
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=refusing),patch('news_mvp.publish.api',return_value={'object':{'sha':'a3d44b042e0dddf3a4117e2db88df3dbdd697f8f'}}),patch('news_mvp.publish.matching_runs',return_value=[]):
                for attempt in range(1,pub.DISPATCH_REFUSAL_LIMIT+1):
                    result=publish(store,job,self.config['state_dir'],self.config_path)
                    self.assertEqual(result['status'],'dispatch_retry')
                    self.assertIn('HTTP 503',result['reason'])
                    row=store.db.execute('SELECT status,error FROM publications').fetchone()
                    self.assertEqual(row['status'],'prepared')
                    self.assertTrue(row['error'].startswith(f'DispatchRefused {attempt}: '))
                with self.assertRaises(pub.DispatchRefused):publish(store,job,self.config['state_dir'],self.config_path)
                self.assertEqual(store.db.execute('SELECT status FROM publications').fetchone()[0],'unknown')
                self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),pub.DISPATCH_REFUSAL_LIMIT+1)
            with store.db:store.db.execute("UPDATE publications SET status='prepared',error='DispatchRefused 1: x'")
            calls=[]
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=lambda *a:calls.append(a) or 'source'),patch('news_mvp.publish.api',return_value={'object':{'sha':'a3d44b042e0dddf3a4117e2db88df3dbdd697f8f'}}),patch('news_mvp.publish.matching_runs',return_value=[]):
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
            self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1)

    def test_startup_failure_run_is_redispatched_bounded(self):
        # 11 Nov 2026 real case: article f2b1b20b, commit d70eea41 on main, deploy run
        # 43096348961 concluded 'startup_failure' with zero jobs (nothing deployed).
        # The publisher marked the article failed for good; it must redispatch instead.
        from news_mvp import publish as pub
        commit='d70eea416cec9dda735f5dbc5322d63e51fc98f8'
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        runs=[{'databaseId':43096348961,'status':'completed','conclusion':'startup_failure','headSha':commit}]
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source',commit,'dispatched'));store.db.commit()
            calls=[]
            def listing(_commit):return [dict(r) for r in reversed(runs)]
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=lambda *a:calls.append(a) or 'source'),patch('news_mvp.publish.api',return_value={'object':{'sha':commit}}),patch('news_mvp.publish.matching_runs',side_effect=listing):
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1)
                # new run not visible yet: never a second dispatch for the same failure
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
                self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1)
                runs.append({'databaseId':43096400000,'status':'in_progress','conclusion':'','headSha':commit})
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'deploying')
                # bounded: the third startup failure is final
                runs[-1].update(status='completed',conclusion='startup_failure')
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                runs.append({'databaseId':43096500000,'status':'completed','conclusion':'startup_failure','headSha':commit})
                with self.assertRaises(ValueError):publish(store,job,self.config['state_dir'],self.config_path)
            self.assertEqual(store.db.execute('SELECT status FROM publications').fetchone()[0],'failed')
            self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),pub.STARTUP_FAILURE_LIMIT-1)

    def test_lost_dispatch_redispatched_after_wait_bounded(self):
        # 11 Nov 2026 real case: article f2b1b20b, commit 62137a85 pushed 21:30:56 UTC;
        # dispatch accepted 21:31:01 but GitHub ran it on the previous main f73cd97f
        # ('Reject superseded main'), so no run for our commit ever appeared.
        from datetime import datetime, timedelta, timezone
        from news_mvp import publish as pub
        commit='62137a850207b9f74386ce1c61fc4389a7562f01'
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source',commit,'prepared'));store.db.commit()
            calls=[]
            def age(minutes):
                with store.db:store.db.execute("UPDATE publications SET error=replace(error,substr(error,12,instr(error,' lost=')-12),?)",
                                               ((datetime.now(timezone.utc)-timedelta(minutes=minutes)).isoformat(),))
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=lambda *a:calls.append(a) or 'source'),patch('news_mvp.publish.api',return_value={'object':{'sha':commit}}),patch('news_mvp.publish.matching_runs',return_value=[]):
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                self.assertTrue(store.db.execute('SELECT error FROM publications').fetchone()[0].endswith(' lost=0'))
                age(5)
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
                for expected in (1,2):
                    age(25)
                    self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                    self.assertTrue(store.db.execute('SELECT error FROM publications').fetchone()[0].endswith(f' lost={expected}'))
                age(25)
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
            self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1+pub.DISPATCH_LOST_LIMIT)

    def test_cloudflare_step_failure_is_redispatched_bounded(self):
        # 13 Nov 2026 real case: article 884a46a6, commit 7515f29a, run 43451905694
        # failed only in 'Deploy to Cloudflare Pages' (wrangler: 'Failed to publish your
        # Function. Got error: Unknown internal error occurred.'). Nothing was deployed;
        # the article was marked failed for good. It must be redispatched, bounded.
        from news_mvp import publish as pub
        commit='7515f29a92537603eb87550d2b30f5231c87ea1d'
        step='Deploy to Cloudflare Pages (bounded retry on Cloudflare-side errors)'
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64,'local_path':'media/'+('a'*64)+'.jpg','url':'https://example.invalid/image.jpg','source_url':'https://example.invalid/story','license_url':'https://example.invalid/rights','license':'isolated test rights','alt':'Test','credit':'Test'}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image'];packet['fixture']=False
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft),'review':json.dumps({'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})}
        runs=[{'databaseId':43451905694,'status':'completed','conclusion':'failure','headSha':commit}]
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,?)',
                (self.job,digest(packet),digest(draft),'a'*64,'source',commit,'dispatched'));store.db.commit()
            calls=[]
            def listing(_commit):return [dict(r) for r in reversed(runs)]
            with patch('news_mvp.publish.guard'),patch('news_mvp.publish.cmd',side_effect=lambda *a:calls.append(a) or 'source'),patch('news_mvp.publish.api',return_value={'object':{'sha':commit}}),patch('news_mvp.publish.matching_runs',side_effect=listing),patch('news_mvp.publish.failed_step',return_value=step):
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1)
                # new run not visible yet: the same failure is never answered twice
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'awaiting_dispatch_visibility')
                self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),1)
                runs.append({'databaseId':43451999999,'status':'completed','conclusion':'failure','headSha':commit})
                self.assertEqual(publish(store,job,self.config['state_dir'],self.config_path)['status'],'dispatched')
                runs.append({'databaseId':43452999999,'status':'completed','conclusion':'failure','headSha':commit})
                with self.assertRaises(ValueError):publish(store,job,self.config['state_dir'],self.config_path)
            self.assertEqual(store.db.execute('SELECT status FROM publications').fetchone()[0],'failed')
            self.assertEqual(sum(a[:3]==('gh','workflow','run') for a in calls),pub.DEPLOY_STEP_RETRY_LIMIT)

    def test_check_step_failure_stays_final(self):
        from news_mvp.publish import deploy_step_redispatch
        runs=[{'databaseId':5,'status':'completed','conclusion':'failure'}]
        self.assertIsNone(deploy_step_redispatch(runs,None,lambda _id:'Reject superseded main'))
        self.assertIsNone(deploy_step_redispatch(runs,None,lambda _id:'Verify exact fresh public bundle'))
        self.assertEqual(deploy_step_redispatch(runs,None,lambda _id:'Deploy to Cloudflare Pages (bounded retry on Cloudflare-side errors)'),'redispatch')

    def test_real_deploy_failure_still_final(self):
        from news_mvp.publish import startup_failure_redispatch
        self.assertEqual(startup_failure_redispatch([{'databaseId':1,'conclusion':'failure'}],None),([{'databaseId':1,'conclusion':'failure'}],None,None))

    def test_deployed_source_skips_collection_and_publication_on_next_tick(self):
        recipe='sources/monterrey-2026-09-11.json';data=json.loads((ROOT/recipe).read_text());identity=digest('url:'+data['url'])
        cfg=json.loads(self.config_path.read_text());cfg.update(backend='hermes',source_recipes=[recipe]);self.config_path.write_text(json.dumps(cfg))
        with database(self.config['state_dir']) as store:
            ensure_table(store);store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',(identity,'p','d','i','s','deployed'));store.db.commit()
        with patch('news_mvp.live.collect',side_effect=AssertionError('Duplicate source fetch')),patch('news_mvp.live.publish',side_effect=AssertionError('Duplicate publish')):
            self.assertEqual(live_tick(self.config_path),{'status':'idle','publications':1})


class RequeueFailed(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config_path=self.root/'config.json';self.config_path.write_text(json.dumps({'enabled':True,'backend':'fixture','state_dir':str(self.root/'state'),'output_dir':str(self.root/'private')}))
        self.config=load_config(self.config_path);self.packet=json.loads((ROOT/'fixtures/source-packet.json').read_text())
        self.job=ingest(self.config,self.packet,datetime(2026,9,12,12,tzinfo=timezone.utc))['id']

    def test_resets_hashes_and_clears_run_state_for_reconciliation(self):
        from news_mvp.publish import requeue_failed
        draft=FixtureModel().call('writer',self.packet)
        with database(self.config['state_dir']) as store:
            store.save_draft(self.job,draft,'fixture')
            store.finish_review(self.job,{'approved':True,'draft_sha256':digest(draft),'reasons':['isolated test']})
            ensure_table(store)
            store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status,attempts,error) VALUES(?,?,?,?,?,?,?,?,?)",
                             (self.job,'old','old','old','source','remote','failed',2,'AttributeError'))
            store.db.commit()
        with patch('news_mvp.publish.media',return_value={'image_sha256':None}):
            result=requeue_failed(self.config)
        self.assertEqual(result['reset'],[self.job])
        with database(self.config['state_dir']) as store:
            row=store.db.execute("SELECT * FROM publications WHERE job_id=?",(self.job,)).fetchone()
            self.assertEqual((row['status'],row['attempts'],row['remote_commit'],row['error']),('preparing',0,None,None))
            self.assertEqual(row['draft_sha'],digest(json.loads(store.get(self.job)['draft'])))

    def test_skips_records_without_a_reviewed_draft(self):
        from news_mvp.publish import requeue_failed
        with database(self.config['state_dir']) as store:
            ensure_table(store)
            store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)",
                             (self.job,'p','d','i','s','failed'))
            store.db.commit()
        result=requeue_failed(self.config)
        self.assertEqual(result['reset'],[])
        self.assertTrue(result['skipped'])


if __name__=='__main__':unittest.main()

"""Actual consumers; only upstream/model/deployment boundaries are simulated.
All source/publication records here are synthetic and confined to temporary state.
"""
import copy,hashlib,io,json,os,re,subprocess,sys,tempfile,textwrap,unittest
from contextlib import ExitStack
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from news_mvp import official
from news_mvp.authorization import authorize,proposed_policy_v2
from news_mvp.controller import ingest,load_config,tick
from news_mvp.discovery import discover
from news_mvp.editorial import ROOT,digest
from news_mvp.live import live_tick
from news_mvp.publish import ensure_table,public_bundle,publish,restore_image_required_schema
from news_mvp.site import article_path, render_site
from news_mvp.release_contract import media,receipt_media,verify_intake
from news_mvp.store import database
from cutover.check_release import check
from image_helpers import editorial_images, scan
COMMIT='a'*40
REMOTE='b'*40
TEXT='Helsingin kaupunki kertoo uuden kirjaston avaamisesta syyskuussa. Kirjastossa voi lainata kirjoja ja käyttää lukutiloja. Kaupunki kertoo palveluista omilla verkkosivuillaan. Tämä synteettinen testitiedote koskee paikallisia kirjastopalveluja.'
class ReleaseV2(unittest.TestCase):
    def setUp(self):
        from image_helpers import approved_pixel_review
        pixels=patch("news_mvp.imagery.review_pixels",side_effect=approved_pixel_review);pixels.start();self.addCleanup(pixels.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.state=self.root/'state';self.state.mkdir()
        self.config={'enabled':True,'backend':'hermes','state_dir':str(self.state),'output_dir':str(self.root/'private'),'max_source_age_hours':48,'illustrations':False,'authorization_mode':'steady_state','source_recipes':[],'discovery':{'family':'news-reviewed-v2','max_candidates':5}}
        self.cfg=self.root/'config.json';self.cfg.write_text(json.dumps(self.config))
        policy=proposed_policy_v2(COMMIT);policy.update(enabled=True,approved_by='Hermes',review_ref='isolated-test-approval')
        (self.state/'steady-state-policy.json').write_text(json.dumps(policy));(self.state/'cutover').mkdir();(self.state/'cutover/drain-verified.json').write_text(json.dumps({'legacy_processes_active':False,'legacy_actions_active':False}))
        self.now=datetime.now(timezone.utc);self.url='https://www.hel.fi/fi/uutiset/test-library'
        self.rights=(ROOT/'fixtures/official/helsinki-rights.html').read_bytes()
        self.raw=f'<meta property="og:title" content="Kirjasto avataan | Helsingin kaupunki"><meta property="article:published_time" content="{self.now.isoformat()}"><div class="component--paragraph-text"><p>{TEXT}</p></div>'.encode()
        self.recipe={'family':'finnish-official','provider':'helsinki','url':self.url}
        with patch.object(official,'fetch',side_effect=self.source_fetch):self.packet,_=official.collect(self.recipe,self.state,self.now)
        self.draft={'title':'Helsinki avaa kirjaston','summary':'Kaupunki kertoo kirjastopalveluista.','category':'Kulttuuri','paragraphs':[{'text':'Helsingin kaupungin mukaan uusi kirjasto avataan syyskuussa.','source_ids':['A']},{'text':'Kirjastossa voi lainata kirjoja ja käyttää lukutiloja.','source_ids':['A']}],'image':None}
    def source_fetch(self,url,hosts):return (self.rights if url==official.policy()['providers']['helsinki']['rights_url'] else self.raw,'text/html',url)
    def ready(self,packet=None,draft=None):
        # Current publication fixtures require imagery; explicit arguments still build
        # historical text-only records for provenance and migration refusal tests.
        if packet is None and draft is None:
            from test_generated_integrity import GeneratedIntegrity
            packet,draft=GeneratedIntegrity.generated(self)
        packet=packet or self.packet;draft=draft or self.draft;identity=ingest(load_config(self.cfg),packet,self.now)['id']
        with database(self.state) as store:
            ensure_table(store);store.save_draft(identity,draft,'isolated-model-boundary');store.finish_review(identity,{'approved':True,'draft_sha256':digest(draft),'reasons':['Synthetic isolated review']});return store.get(identity)
    def image_job(self):
        packet=copy.deepcopy(self.packet);packet.pop('publication_basis');packet['story_key']='url:https://modis.gsfc.nasa.gov/gallery/individual.php?db_date='+self.now.date().isoformat();packet['sources'][0]['url']=packet['story_key'][4:];packet['sources'][0]['publisher']='NASA GSFC / MODIS';packet['sources'][0].pop('reuse')
        raw=b'\xff\xd8\xffisolated-jpeg';sha=hashlib.sha256(raw).hexdigest();(self.state/'media').mkdir(exist_ok=True);(self.state/'media'/f'{sha}.jpg').write_bytes(raw)
        packet['image']={'sha256':sha,'local_path':f'media/{sha}.jpg','url':'https://modis.gsfc.nasa.gov/gallery/images/test.jpg','source_url':packet['sources'][0]['url'],'license_url':'https://www.nasa.gov/nasa-brand-center/images-and-media/','license':'NASA editorial permission (synthetic test)','credit':'NASA GSFC','alt':'Synthetic source image','caption':'Synthetic test image'}
        draft={**self.draft,'title':'NASA synthetic image story','category':'Tiede','image':packet['image']}
        return self.ready(packet,draft),sha
    def shell(self,calls):
        def run(*args):
            calls.append(args)
            if args[:3]==('git','rev-parse','HEAD'):return COMMIT
            if args[:2]==('git','status'):return ''
            if args[:3]==('gh','run','list'):return '[]'
            if args[:3] in [('gh','workflow','enable'),('gh','workflow','run')]:return ''
            raise AssertionError(('unfaked command',args))
        return run
    def workflow(self,receipt):
        # Execute exact checked-in Actions Python consumer with only HTTP/env faked.
        code=(ROOT/'ops/deploy.yml').read_text().split("python3 - <<'PY'\n",1)[1].split('\n          PY',1)[0];code=textwrap.dedent(code)
        deployment={'id':'isolated-deployment','url':'https://isolated.pages.dev','environment':'production','latest_stage':{'status':'success'},'deployment_trigger':{'metadata':{'commit_hash':REMOTE}}}
        work=self.root/'workflow';work.mkdir(exist_ok=True);(work/'release').mkdir(exist_ok=True);(work/'release/release.json').write_text(json.dumps(receipt))
        previous=Path.cwd()
        try:
            os.chdir(work)
            with patch.dict(os.environ,{'GITHUB_SHA':REMOTE,'CF_ACCOUNT':'isolated','CF_TOKEN':'not-a-credential'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'success':True,'result':{'canonical_deployment':deployment}}).encode())):
                exec(compile(code,'actual ops/deploy.yml','exec'),{})
        finally:os.chdir(previous)
        return json.loads((work/'live-deployment.json').read_text())
    def test_text_and_image_full_actual_publish_workflow_canonical_next_tick(self):
        for kind in ['text','image']:
            with self.subTest(kind=kind):
                job=self.ready() if kind=='text' else self.image_job()[0]
                calls=[]
                with database(self.state) as store,patch('news_mvp.publish.cmd',side_effect=self.shell(calls)),patch('news_mvp.publish.api',return_value={'object':{'sha':REMOTE}}),patch('news_mvp.publish.make_commit',return_value=REMOTE),patch('news_mvp.publish.matching_runs',return_value=[]):
                    first=publish(store,job,self.state,self.cfg);self.assertEqual(first['status'],'dispatched')
                    second=publish(store,job,self.state,self.cfg);self.assertEqual(second['status'],'awaiting_dispatch_visibility')
                    self.assertEqual(sum(c[:3]==('gh','workflow','run') for c in calls),1)
                receipt=json.loads((self.state/'release.json').read_text());binding=receipt_media(receipt)
                result=subprocess.run([sys.executable,'-B',str(ROOT/'cutover/check_release.py'),str(self.state/'live-site'),str(self.state/'release.json')],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                record=self.workflow(receipt);self.assertEqual(record['image_sha256'],binding['image_sha256'])
                if kind=='text':self.assertEqual(record['text_only'],binding['text_only'])
                deployment=self.state/'deployments/123';deployment.mkdir(parents=True,exist_ok=True);(deployment/'live-deployment.json').write_text(json.dumps(record))
                requested=[]
                def read(request,**kwargs):
                    url=request.full_url;requested.append(url);return io.BytesIO((self.state/'live-site'/url.removeprefix('https://uutistenlukija.fi/')).joinpath('index.html').read_bytes()) if url.endswith('/') else io.BytesIO((self.state/'live-site'/url.removeprefix('https://uutistenlukija.fi/')).read_bytes())
                with database(self.state) as store,patch('news_mvp.publish.cmd',side_effect=self.shell(calls)),patch('news_mvp.publish.api',return_value={'object':{'sha':REMOTE}}),patch('news_mvp.publish.matching_runs',return_value=[{'databaseId':123,'status':'completed','conclusion':'success'}]),patch('urllib.request.urlopen',side_effect=read):
                    self.assertEqual(publish(store,job,self.state,self.cfg)['status'],'deployed')
                    self.assertEqual(publish(store,job,self.state,self.cfg)['status'],'idle')
                self.assertTrue(any(u.endswith('.jpg') for u in requested))
                readback=json.loads((deployment/'live-readback.json').read_text());self.assertEqual(readback['live_image_sha256'],binding['image_sha256'])
    def test_mixed_home_retains_old_image_receipt_and_honest_text(self):
        old,sha=self.image_job();job=self.ready()
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):
            store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,'deployed')",(old['id'],digest(json.loads(old['packet'])),digest(json.loads(old['draft'])),sha,COMMIT));store.db.commit()
            before=tuple(store.db.execute('SELECT * FROM publications WHERE job_id=?',(old['id'],)).fetchone())
            site,receipt=public_bundle(store,job,self.state);check(site,receipt)
            after=tuple(store.db.execute('SELECT * FROM publications WHERE job_id=?',(old['id'],)).fetchone());self.assertEqual(before,after)
            home=(site/'index.html').read_text();self.assertIn(self.draft['title'],home);self.assertIn('NASA synthetic image story',home)
            text=(site/(article_path(job)+"index.html")).read_text();self.assertNotIn('Luonnos',text)
            self.assertEqual(len(editorial_images(scan(text))),1)
            self.assertIn('CC BY 4.0',text);self.assertNotIn('Tämä uutinen julkaistaan ilman kuvaa.',text);self.assertTrue((site/f'mvp-assets/{sha}.jpg').exists())
    def test_wrong_missing_policy_rights_private_fixture_packet_refused(self):
        for mutation in ['policy','rights','private','fixture','source','image-required']:
            packet=copy.deepcopy(self.packet)
            if mutation=='policy':packet['publication_basis']['policy_sha256']='0'*64
            if mutation=='rights':packet['supporting_documents']=[]
            if mutation=='private':packet['private_only']=True
            if mutation=='fixture':packet['fixture']=True
            if mutation=='source':packet['sources'][0]['text']+='tamper'
            if mutation=='image-required':packet.pop('publication_basis')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):media(packet,self.draft)
    def test_local_source_bytes_and_receipt_packet_tamper_refused(self):
        path=self.state/'intake'/digest(self.packet)/'source.html';path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError):verify_intake(self.packet,self.state)
        # Receipt identity cannot be forged merely by retaining original packet hash.
        job=self.ready();path.write_bytes(self.raw)
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):_,r=public_bundle(store,job,self.state)
        r['packet']['sources'][0]['text']+='changed'
        with self.assertRaises(ValueError):receipt_media(r)
    def test_old_schema_rows_preserved_and_nullable_not_dummy_hash(self):
        other=self.root/'old'
        with database(other) as store:
            store.db.execute('CREATE TABLE publications (job_id TEXT PRIMARY KEY,packet_sha TEXT NOT NULL,draft_sha TEXT NOT NULL,image_sha TEXT NOT NULL,source_commit TEXT NOT NULL,remote_commit TEXT,run_id INTEGER,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT)')
            store.db.execute("INSERT INTO publications VALUES('old','p','d',?,'source','remote',17,'deployed',1,NULL)",('c'*64,));store.db.commit();before=tuple(store.db.execute('SELECT * FROM publications').fetchone())
            ensure_table(store);self.assertEqual(before,tuple(store.db.execute('SELECT * FROM publications').fetchone()));ensure_table(store)
            self.assertEqual(next(c for c in store.db.execute('PRAGMA table_info(publications)') if c[1]=='image_sha')[3],0)
            restore_image_required_schema(store);self.assertEqual(before,tuple(store.db.execute('SELECT * FROM publications').fetchone()))
            self.assertEqual(next(c for c in store.db.execute('PRAGMA table_info(publications)') if c[1]=='image_sha')[3],1)
            ensure_table(store);store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES('text','p','d',NULL,'s','deployed')");store.db.commit()
            with self.assertRaises(ValueError):restore_image_required_schema(store)
            self.assertEqual(store.db.execute('SELECT count(*) FROM publications').fetchone()[0],2)
    def test_policy_guards_config_and_does_not_pin_commit(self):
        authorize(self.config)
        for cfg in [{**self.config,'enabled':False},{**self.config,'max_source_age_hours':49}]:
            with self.assertRaises(ValueError):authorize(cfg)
        p=self.state/'steady-state-policy.json';policy=json.loads(p.read_text());policy['text_only_policy_sha256']='0'*64;p.write_text(json.dumps(policy))
        with self.assertRaises(ValueError):authorize(self.config)
        policy['text_only_policy_sha256']=digest(official.policy());p.write_text(json.dumps(policy))
        # a new commit must NOT require re-approval; the gate is about config, not code history
        self.assertIsNone(authorize(self.config))
    def test_partial_outage_other_providers_remain_and_terminal_sixth_discovered(self):
        items=''.join(f'<item><link>https://www.hel.fi/fi/uutiset/a{i}</link><pubDate>{self.now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate></item>' for i in range(8))
        raw=('<rss><channel>'+items+'</channel></rss>').encode();errors=[];excluded={f'https://www.hel.fi/fi/uutiset/a{i}' for i in range(5)}
        def response(url,hosts):
            # Helsinki serves a usable feed; every other provider has a source-local outage.
            if url=='https://www.hel.fi/fi/uutiset/rss':return raw
            raise OSError('source-local outage')
        with patch('news_mvp.discovery.fetch',side_effect=OSError('NASA unavailable')),patch.object(official,'response',side_effect=response):rows=discover(self.config,self.now,excluded,errors,after_provider='stat')
        self.assertEqual(rows[0]['url'],'https://www.hel.fi/fi/uutiset/a5')
        self.assertEqual({r['url'] for r in rows},{'https://www.hel.fi/fi/uutiset/a5','https://www.hel.fi/fi/uutiset/a6','https://www.hel.fi/fi/uutiset/a7'})
        # Every non-Helsinki provider fails for its own reason; assert the set is exactly the
        # configured providers minus the one that answered.
        self.assertEqual({e['provider'] for e in errors},set(official.PROVIDER_ORDER)-{'helsinki'})
    def test_one_real_controller_editorial_sequence_only_one_admission(self):
        from test_generated_integrity import GeneratedIntegrity
        self.packet,self.draft=GeneratedIntegrity.generated(self)
        collector=patch('news_mvp.live.collect',return_value=(self.packet,{}));collector.start();self.addCleanup(collector.stop)
        calls=[]
        class Model:
            name='isolated-model-boundary'
            def call(inner,role,packet,draft=None):
                calls.append(role)
                return self.draft if role=='writer' else {'approved':True,'draft_sha256':digest(draft),'reasons':['Synthetic sources only']}
        recipes=[self.recipe,{**self.recipe,'url':self.url+'-next'}]
        with patch('news_mvp.publish.cmd',side_effect=self.shell([])),patch('news_mvp.live.discover',return_value=recipes),patch.object(official,'fetch',side_effect=self.source_fetch),patch('news_mvp.controller.HermesModel',return_value=Model()),patch('news_mvp.publish.api',return_value={'object':{'sha':REMOTE}}),patch('news_mvp.publish.make_commit',return_value=REMOTE),patch('news_mvp.publish.matching_runs',return_value=[]):
            result=live_tick(self.cfg)
        self.assertEqual(result['status'],'dispatched');self.assertEqual(calls,['writer','reviewer'])
        with database(self.state) as store:self.assertEqual(store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_actual_deployed_mixed_tick_excludes_without_editorial_or_publish(self):
        job=self.ready()
        with database(self.state) as store:
            store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,NULL,?,'deployed')",(job['id'],digest(self.packet),digest(self.draft),COMMIT));store.db.commit()
        feed=('<rss><channel><item><link>'+self.url+'</link><pubDate>'+self.now.strftime('%a, %d %b %Y %H:%M:%S +0000')+'</pubDate></item></channel></rss>').encode()
        with patch('news_mvp.publish.cmd',side_effect=self.shell([])),patch('news_mvp.discovery.fetch',return_value=(b'<html></html>','text/html','https://modis.gsfc.nasa.gov/gallery/showall.php')),patch.object(official,'response',side_effect=lambda url,hosts:feed if url.endswith('/rss') else b'<main></main>'),patch('news_mvp.controller.HermesModel',side_effect=AssertionError('duplicate model')),patch('news_mvp.live.publish',side_effect=AssertionError('duplicate publication')):
            self.assertEqual(live_tick(self.cfg),{'status':'idle','publications':1})
    def test_actual_consumers_reject_wrong_policy_receipt_and_missing_image(self):
        job=self.ready()
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):site,receipt=public_bundle(store,job,self.state)
        bad=copy.deepcopy(receipt);bad['text_only']['policy']='unknown'
        with self.assertRaises(ValueError):check(site,bad)
        with self.assertRaises(ValueError):self.workflow(bad)
        image,sha=self.image_job()
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):site,receipt=public_bundle(store,image,self.state)
        (site/f'mvp-assets/{sha}.jpg').unlink()
        with self.assertRaises(ValueError):check(site,receipt)
    def test_provider_rotation_and_source_failure_reports(self):
        with patch('news_mvp.discovery.fetch',side_effect=OSError('nasa outage')),patch.object(official,'response',side_effect=OSError('official outage')):
            errors=[];self.assertEqual(discover(self.config,self.now,errors=errors),[]);self.assertEqual(len(errors),len(official.PROVIDER_ORDER))
        with patch('news_mvp.discovery.fetch',return_value=(b'not html','application/json','https://modis.gsfc.nasa.gov/gallery/showall.php')),patch.object(official,'response',return_value=b'<rss><channel/></rss>'):
            errors=[];discover(self.config,self.now,errors=errors);self.assertIn('nasa-modis',{e['provider'] for e in errors})
        nasa=b'<a href="individual.php?db_date='+self.now.date().isoformat().encode()+b'">story</a>'
        feed=('<rss><channel><item><link>'+self.url+'</link><pubDate>'+self.now.strftime('%a, %d %b %Y %H:%M:%S +0000')+'</pubDate></item></channel></rss>').encode()
        with patch('news_mvp.discovery.fetch',return_value=(nasa,'text/html','https://modis.gsfc.nasa.gov/gallery/showall.php')),patch.object(official,'response',side_effect=lambda url,hosts:feed if url.endswith('/rss') else b'<a href="/fi/julkaisu/test">story</a>'):
            for after,expected in [('nasa-modis','helsinki'),('helsinki','stat'),('stat','nasa-modis')]:
                rows=discover(self.config,self.now,after_provider=after);self.assertEqual(rows[0].get('provider',rows[0]['family']),expected)


    def test_schema_failure_rolls_back_real_sqlite_transaction(self):
        from news_mvp.publish import _image_constraint
        with database(self.root/'failure') as store:
            ensure_table(store)
            store.db.execute("INSERT INTO publications VALUES('old','p','d',?,'s','r',1,'deployed',1,NULL)",('c'*64,));store.db.commit()
            before=tuple(store.db.execute('SELECT * FROM publications').fetchone())
            original=store.db
            class Failure:
                def __enter__(inner):original.__enter__();return inner
                def __exit__(inner,*args):return original.__exit__(*args)
                def execute(inner,sql,*args):
                    if sql.startswith('ALTER TABLE publications_transition'):raise RuntimeError('isolated failure after DROP, before RENAME')
                    return original.execute(sql,*args)
            store.db=Failure()
            with self.assertRaises(RuntimeError):_image_constraint(store,True)
            store.db=original
            self.assertEqual(before,tuple(original.execute('SELECT * FROM publications').fetchone()))
            self.assertFalse(original.execute("SELECT 1 FROM sqlite_master WHERE name='publications_transition'").fetchone())


    def pending_case(self,mode):
        from test_generated_integrity import GeneratedIntegrity
        self.packet,self.draft=GeneratedIntegrity.generated(self)
        collector=patch('news_mvp.live.collect',return_value=(self.packet,{}));collector.start();self.addCleanup(collector.stop)
        model_calls=[];commands=[];promotions=[]
        class Model:
            name='isolated-model-boundary'
            def call(inner,role,packet,draft=None):
                model_calls.append(role)
                return self.draft if role=='writer' else {'approved':True,'draft_sha256':digest(draft),'reasons':['Synthetic sources only']}
        normal=self.shell(commands)
        def command(*args):
            if mode=='prepared' and args[:3]==('gh','workflow','enable'):raise KeyboardInterrupt('isolated crash after prepared record')
            if mode=='unknown' and args[:3]==('gh','workflow','run'):
                commands.append(args);raise OSError('dispatch response lost after request')
            return normal(*args)
        def api(path,*args,**kwargs):
            if args or kwargs:promotions.append((path,args,kwargs));return {}
            return {'object':{'sha':REMOTE}}
        with patch('news_mvp.publish.cmd',side_effect=command),patch('news_mvp.live.discover',return_value=[self.recipe]),patch.object(official,'fetch',side_effect=self.source_fetch),patch('news_mvp.controller.HermesModel',return_value=Model()),patch('news_mvp.publish.api',side_effect=api),patch('news_mvp.publish.make_commit',return_value=REMOTE),patch('news_mvp.publish.matching_runs',return_value=[]):
            if mode=='prepared':
                with self.assertRaises(KeyboardInterrupt):live_tick(self.cfg)
            elif mode=='unknown':
                with self.assertRaises(OSError):live_tick(self.cfg)
            else:self.assertEqual(live_tick(self.cfg)['status'],'dispatched')
        with database(self.state) as store:
            row=store.db.execute('SELECT * FROM publications').fetchone();job_id=row['job_id'];self.assertEqual(row['status'],mode)
        self.assertEqual(model_calls,['writer','reviewer'])
        pushes_before=len(promotions);dispatches_before=sum(c[:3]==('gh','workflow','run') for c in commands)
        # A rotated/new provider or vanished/stale old feed must not even be scanned.
        with patch('news_mvp.publish.cmd',side_effect=normal),patch('news_mvp.live.discover',side_effect=AssertionError('pending job must bypass all feeds')),patch('news_mvp.controller.HermesModel',side_effect=AssertionError('new writer before terminal outcome')),patch('news_mvp.publish.api',side_effect=api if mode=='prepared' else AssertionError('unknown/dispatched must not promote again')),patch('news_mvp.publish.matching_runs',return_value=[]):
            second=live_tick(self.cfg);self.assertEqual(second['job_id'],job_id)
            self.assertEqual(second['status'],'dispatched' if mode=='prepared' else 'awaiting_dispatch_visibility')
            third=live_tick(self.cfg);self.assertEqual(third['status'],'awaiting_dispatch_visibility');self.assertEqual(third['job_id'],job_id)
        self.assertEqual(len(promotions),pushes_before)
        self.assertEqual(sum(c[:3]==('gh','workflow','run') for c in commands),dispatches_before+(1 if mode=='prepared' else 0))
        with database(self.state) as store:self.assertEqual(store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
    def test_consecutive_live_ticks_resume_dispatched_without_feed_or_new_writer(self):
        self.pending_case('dispatched')
    def test_consecutive_live_ticks_resume_prepared_before_provider_rotation(self):
        self.pending_case('prepared')
    def test_unknown_dispatch_outcome_blocks_new_admission_push_and_redispatch(self):
        self.pending_case('unknown')

if __name__=='__main__':unittest.main()

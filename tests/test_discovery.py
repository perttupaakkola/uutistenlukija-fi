import copy,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from news_mvp.controller import load_config
from news_mvp.discovery import discover,INDEX
from news_mvp.editorial import ROOT,digest
from news_mvp.live import live_tick
from news_mvp.store import database
from news_mvp.publish import ensure_table
from news_mvp.authorization import authorize,proposed_policy

class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.path=self.root/'config.json';self.config={'enabled':True,'backend':'hermes','state_dir':str(self.root/'state'),'output_dir':str(self.root/'private'),'source_recipes':[],'discovery':{'family':'nasa-modis','max_candidates':5},'max_source_age_hours':48}
        self.path.write_text(json.dumps(self.config));self.packet=json.loads((ROOT/'fixtures/source-packet.json').read_text())
    def fixture_packet(self,url):
        p=copy.deepcopy(self.packet);p['fixture']=False;p['story_key']='url:'+url
        stamp=datetime.now(timezone.utc).isoformat()
        for s in p['sources']:s['published_at']=stamp
        p['sources'][0]['url']=url
        return p
    def render(self,config_path,**kwargs):
        with database(self.config['state_dir']) as store:store.db.execute("UPDATE jobs SET status='rendered' WHERE id=?",(kwargs['target_job_id'],));store.db.commit()
    def test_terminal_first_does_not_starve_ready_next(self):
        for terminal in ['rejected','failed','publication_failed']:
            with self.subTest(terminal=terminal):
                first='https://example.invalid/'+terminal;second=first+'-next'
                with database(self.config['state_dir']) as store:
                    for url in [first,second]:store.admit(self.fixture_packet(url),'2026-09-12T12:00:00+00:00')
                    identity=digest('url:'+first);ensure_table(store)
                    store.db.execute('UPDATE jobs SET status=? WHERE id=?',('rendered' if terminal=='publication_failed' else terminal,identity))
                    if terminal=='publication_failed':store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,'failed')",(identity,'p','d','i','s'))
                    store.db.commit()
                with patch('news_mvp.live.discover',return_value=[{'url':first},{'url':second}]),patch('news_mvp.live.collect',side_effect=AssertionError('already admitted')),patch('news_mvp.live.tick',side_effect=self.render) as model,patch('news_mvp.live.publish',return_value={'status':'dispatched'}) as publish:
                    self.assertEqual(live_tick(self.path)['status'],'dispatched');self.assertEqual(model.call_args.kwargs['target_job_id'],digest('url:'+second));self.assertEqual(publish.call_args.args[1]['id'],digest('url:'+second))
    def test_no_eligible_and_deployed_duplicates_do_no_editorial_work(self):
        url='https://example.invalid/done';identity=digest('url:'+url)
        with database(self.config['state_dir']) as store:
            ensure_table(store);store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,'deployed')",(identity,'p','d','i','s'));store.db.commit()
        for recipes in [[],[{'url':url},{'url':url}]]:
            with patch('news_mvp.live.discover',return_value=recipes),patch('news_mvp.live.collect',side_effect=AssertionError()),patch('news_mvp.live.tick',side_effect=AssertionError()),patch('news_mvp.live.publish',side_effect=AssertionError()):self.assertEqual(live_tick(self.path),{'status':'idle','publications':1})
    def test_only_one_new_admission_per_tick(self):
        recipes=[{'url':'https://example.invalid/'+str(i)} for i in range(3)]
        with patch('news_mvp.live.discover',return_value=recipes),patch('news_mvp.live.collect',side_effect=lambda recipe,state,**kw:(self.fixture_packet(recipe['url']),{})) as collect,patch('news_mvp.live.tick',side_effect=self.render),patch('news_mvp.live.publish',return_value={'status':'dispatched'}):
            live_tick(self.path);self.assertEqual(collect.call_count,1)
        with database(self.config['state_dir']) as store:self.assertEqual(store.db.execute('select count(*) from jobs').fetchone()[0],1)

    def test_permanent_collection_failure_is_remembered_and_expires(self):
        url = 'https://example.invalid/stale'
        recipe = {'url': url, 'provider': 'kuntaliitto'}
        base = 2_000_000_000.0
        with patch('news_mvp.live.discover', return_value=[recipe]), \
                patch('news_mvp.live.collect', side_effect=ValueError('Source is stale or future-dated')) as collect, \
                patch('news_mvp.live.time.time', return_value=base):
            first = live_tick(self.path)
            second = live_tick(self.path)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(first['source_errors'][0]['url'], url)
        self.assertEqual(second['status'], 'idle')
        with database(self.config['state_dir']) as store:
            row = store.db.execute('SELECT * FROM collection_failures WHERE url=?', (url,)).fetchone()
            self.assertEqual((row['provider'], row['count']), ('kuntaliitto', 1))
            self.assertEqual(store.collection_failure_urls(base + 7 * 24 * 60 * 60 + 1), set())

    def test_transient_collection_failure_retries_after_six_hours_then_gives_up(self):
        from news_mvp.store import COLLECTION_BACKOFF_SECONDS, COLLECTION_FAILURE_TTL_SECONDS
        url = 'https://example.invalid/timeout'
        base = 2_000_000_000.0
        with database(self.config['state_dir']) as store:
            store.record_collection_failure(url, 'valtioneuvosto', 'TimeoutError: timed out', base)
            self.assertEqual(store.collection_failure_urls(base + COLLECTION_BACKOFF_SECONDS - 1), {url})
            self.assertEqual(store.collection_failure_urls(base + COLLECTION_BACKOFF_SECONDS + 1), set())
            store.record_collection_failure(url, 'valtioneuvosto', 'OSError: HTTP 503', base + COLLECTION_BACKOFF_SECONDS + 1)
            store.record_collection_failure(url, 'valtioneuvosto', 'OSError: HTTP 503', base + 2 * COLLECTION_BACKOFF_SECONDS + 2)
            self.assertEqual(store.collection_failure_urls(base + 3 * COLLECTION_BACKOFF_SECONDS + 3), {url})
            self.assertEqual(store.collection_failure_urls(
                base + 2 * COLLECTION_BACKOFF_SECONDS + 2 + COLLECTION_FAILURE_TTL_SECONDS + 1), set())
    def test_due_ready_backlog_precedes_fresh_discovery(self):
        old='https://example.invalid/due-retry';identity=digest('url:'+old)
        with database(self.config['state_dir']) as store:
            store.admit(self.fixture_packet(old),datetime.now(timezone.utc).isoformat())
        with patch('news_mvp.live.discover',side_effect=AssertionError('retry must precede discovery')),patch('news_mvp.live.collect',side_effect=AssertionError()),patch('news_mvp.live.tick',side_effect=self.render) as model,patch('news_mvp.live.publish',return_value={'status':'dispatched'}):
            self.assertEqual(live_tick(self.path)['status'],'dispatched')
        self.assertEqual(model.call_args.kwargs['target_job_id'],identity)
    def test_discovery_rejects_stale_future_and_foreign_links_and_caps_candidates(self):
        links=['individual.php?db_date=2026-09-'+f'{day:02d}' for day in range(1,20)]+['https://evil.invalid/gallery/individual.php?db_date=2026-09-12']
        html=''.join('<a href="'+x+'">x</a>' for x in links).encode();cfg={**self.config,'max_source_age_hours':168}
        with patch('news_mvp.discovery.fetch',return_value=(html,'text/html',INDEX)):
            rows=discover(cfg,datetime(2026,9,12,12,tzinfo=timezone.utc));self.assertEqual(len(rows),5);self.assertTrue(rows[0]['url'].endswith('2026-09-12'));self.assertTrue(all('modis.gsfc.nasa.gov' in r['url'] for r in rows))
    def test_migration_canary_cap_blocks_another_new_admission(self):
        cfg={**self.config,'migration_publication_limit':1};self.path.write_text(json.dumps(cfg))
        with database(cfg['state_dir']) as store:
            ensure_table(store);store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES('done','p','d','i','s','deployed')");store.db.commit()
        with patch('news_mvp.live.discover',return_value=[{'url':'https://example.invalid/new'}]),patch('news_mvp.live.collect',side_effect=AssertionError('Extra canary admission')):
            self.assertEqual(live_tick(self.path),{'status':'idle','publications':1})

    def test_steady_state_requires_separate_explicit_approval(self):
        cfg={**self.config,'authorization_mode':'steady_state'};Path(cfg['state_dir']).mkdir();path=Path(cfg['state_dir'])/'steady-state-policy.json';policy=proposed_policy();path.write_text(json.dumps(policy))
        with self.assertRaises(ValueError):authorize(cfg)
        policy.update(enabled=True,approved_by='Hermes',review_ref='isolated-test-review');path.write_text(json.dumps(policy));authorize(cfg)
        with self.assertRaises(ValueError):authorize({**cfg,'enabled':False})
        policy['enabled']=False;path.write_text(json.dumps(policy))
        with self.assertRaises(ValueError):authorize(cfg)

if __name__=='__main__':unittest.main()

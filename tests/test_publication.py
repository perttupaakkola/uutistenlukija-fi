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
        draft=FixtureModel().call('writer',self.packet);draft['image']={'sha256':'a'*64}
        packet=copy.deepcopy(self.packet);packet['image']=draft['image']
        job={'id':self.job,'packet':json.dumps(packet),'draft':json.dumps(draft)}
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

    def test_deployed_source_skips_collection_and_publication_on_next_tick(self):
        recipe='sources/monterrey-2026-09-11.json';data=json.loads((ROOT/recipe).read_text());identity=digest('url:'+data['url'])
        cfg=json.loads(self.config_path.read_text());cfg.update(backend='hermes',source_recipes=[recipe]);self.config_path.write_text(json.dumps(cfg))
        with database(self.config['state_dir']) as store:
            ensure_table(store);store.db.execute('INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',(identity,'p','d','i','s','deployed'));store.db.commit()
        with patch('news_mvp.live.collect',side_effect=AssertionError('Duplicate source fetch')),patch('news_mvp.live.publish',side_effect=AssertionError('Duplicate publish')):
            self.assertEqual(live_tick(self.config_path),{'status':'idle','publications':1})


if __name__=='__main__':unittest.main()

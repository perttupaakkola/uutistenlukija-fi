import copy, hashlib, json, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from news_mvp import official
from news_mvp.controller import ingest, load_config, tick
from news_mvp.discovery import discover
from news_mvp.editorial import digest, validate_draft, validate_review
from news_mvp.intake import collect
from news_mvp.live import live_tick
from news_mvp.site import render_site
from news_mvp.store import database
NOW = datetime(2026, 9, 11, 15, tzinfo=timezone.utc)
TEXT = 'Helsingin kaupunki kertoo, että uusi kirjasto avataan syyskuussa. Kirjaston palveluihin kuuluvat kirjojen lainaus ja lukutilat. Kaupunki tiedottaa palveluista verkkosivuillaan. Tiedote koskee Helsingin asukkaille suunnattuja palveluita.'
def article(date='2026-09-11T13:00:00+03:00'):
    return f'<meta property="og:title" content="Uusi kirjasto avataan | Helsingin kaupunki"><meta property="article:published_time" content="{date}"><div class="component--paragraph-text"><p>{TEXT}</p><script>INJECTED</script></div><nav>NOT ARTICLE</nav>'.encode()
class Official(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.spec=copy.deepcopy(official.policy())
        self.rights=b'<div class="notes"><p>Official dataset permission</p></div><a rel="dc:rights" href="https://creativecommons.org/licenses/by/4.0/">CC</a><a rel="dc:rights" href="https://creativecommons.org/licenses/by/4.0/deed.fi">CC</a>'
        self.spec['providers']['helsinki']['rights_text_sha256']=hashlib.sha256(official.rights_text(self.rights,'helsinki').encode()).hexdigest()
        self.recipe={'family':'finnish-official','provider':'helsinki','url':'https://www.hel.fi/fi/uutiset/uusi-kirjasto'}
        self.config={'enabled':True,'backend':'hermes','state_dir':str(self.root/'state'),'output_dir':str(self.root/'site'),'max_source_age_hours':48,'discovery':{'family':'finnish-official','max_candidates':5}}
        self.cfg=self.root/'config.json';self.cfg.write_text(json.dumps(self.config))
    def packet(self,raw=None):
        def fetch(url,hosts):return (self.rights if url==self.spec['providers']['helsinki']['rights_url'] else raw or article(),'text/html',url)
        with patch.object(official,'policy',return_value=self.spec),patch.object(official,'fetch',side_effect=fetch):return collect(self.recipe,self.root/'state',NOW)[0]
    def draft(self,packet,category='Kulttuuri'):
        return {'title':'Helsinkiin avataan kirjasto','summary':'Kaupunki kertoo uuden kirjaston avaamisesta.','category':category,'paragraphs':[{'text':'Helsingin kaupungin mukaan kirjasto avataan syyskuussa.','source_ids':['A']},{'text':'Kirjastossa voi lainata kirjoja ja käyttää lukutiloja.','source_ids':['A']}],'image':None}
    def test_parser_no_script_or_navigation(self):
        p=self.packet();self.assertNotIn('INJECTED',p['sources'][0]['text']);self.assertNotIn('NOT ARTICLE',p['sources'][0]['text']);self.assertIsNone(p['image']);self.assertEqual(p['publication_basis']['policy'],'official-text-v1')
    def test_rights_missing_changed_and_source_unavailable(self):
        for failure in ['missing','changed','unavailable']:
            def fetch(url,hosts):
                if failure=='unavailable':raise OSError('Unavailable')
                return (b'<html>login</html>' if failure=='missing' else self.rights.replace(b'permission',b'restricted'),'text/html',url)
            with self.subTest(failure=failure),patch.object(official,'policy',return_value=self.spec),patch.object(official,'fetch',side_effect=fetch),self.assertRaises((ValueError,OSError)):collect(self.recipe,self.root/'refused',NOW)
        self.assertFalse((self.root/'refused').exists())
    def test_unallowlisted_and_redirect_refused(self):
        with self.assertRaises(ValueError):collect({**self.recipe,'url':'https://www.hel.fi/fi/uutiset/a?redirect=evil'},self.root,NOW)
        with patch.object(official,'fetch',return_value=(b'x','text/html','https://evil.invalid/')),self.assertRaises(ValueError):official.response('https://www.hel.fi/fi/uutiset/a',['www.hel.fi'])
    def test_stale_future_missing_date_thin_refused(self):
        for raw in [article('2026-09-01T10:00:00+03:00'),article('2026-09-12T10:00:00+03:00'),article(''),article().replace(TEXT.encode(),b'thin')]:
            with self.subTest(raw=raw[:90]),self.assertRaises(ValueError):self.packet(raw)
    def test_article_specific_rights_refused(self):
        with self.assertRaisesRegex(ValueError,'Article-specific rights'):
            self.packet(article().replace(TEXT.encode(),(TEXT+' All rights reserved.').encode()))
    def test_stat_native_timestamp_and_body(self):
        raw=f'<meta name="tk.published" content="11.9.2026"><meta property="og:title" content="Kustannukset nousivat | Tilastokeskus"><time datetime="2026-09-11T05:00:00+00:00"></time><div class="julkaisu_ingressText__actual"><p>{TEXT}</p></div>'.encode()
        self.assertEqual(official.source_fields(raw,'stat')['published_at'],'2026-09-11T05:00:00+00:00')
        with self.assertRaises(ValueError):official.source_fields(raw.replace(b'11.9.2026',b'10.9.2026'),'stat')
    def test_round_robin_discovery_dedupe_and_bounds(self):
        items=''.join(f'<item><link>https://www.hel.fi/fi/uutiset/a{i}</link><pubDate>Fri, 11 Sep 2026 13:00:00 +0300</pubDate></item>' for i in range(8))
        feed=('<rss><channel>'+items+items+'</channel></rss>').encode();index=''.join(f'<a href="/fi/julkaisu/a{i}">item</a>' for i in range(8)).encode()
        # Every RSS provider gets the same feed body; HTML providers get the link index.
        rss_hosts=('https://www.hel.fi/fi/uutiset/rss','https://www.ecb.europa.eu/rss/press.html',
                   'https://www.kuopio.fi/feed/','https://www.vantaa.fi/fi/rss')
        with patch.object(official,'response',side_effect=lambda url,hosts:feed if url in rss_hosts else index):rows=discover(self.config,NOW)
        # Discovery returns fallback depth rather than exactly one candidate per provider,
        # so a stale lead item cannot consume a provider's whole tick. The invariants that
        # matter are: no duplicate URLs, and the result stays bounded.
        self.assertGreater(len(rows),5)
        self.assertLessEqual(len(rows),official.DEPTH_PER_PROVIDER*len(official.PROVIDER_ORDER),'bounded per provider')
        self.assertEqual(len({r['url'] for r in rows}),len(rows),'discovery must not repeat a URL')
        with patch.object(official,'response',side_effect=OSError('Unavailable')),self.assertRaises(OSError):discover(self.config,NOW)
    def test_sqlite_dedupe_single_job(self):
        p=self.packet();a=ingest(load_config(self.cfg),p,NOW);b=ingest(load_config(self.cfg),p,NOW);self.assertTrue(a['admitted']);self.assertFalse(b['admitted']);self.assertEqual(a['id'],b['id'])
        with database(self.config['state_dir']) as store:self.assertEqual(store.db.execute('select count(*) from jobs').fetchone()[0],1)
    def test_categories_claim_references_and_image_identity(self):
        p=self.packet()
        for c in ['Kotimaa','Talous','Kulttuuri']:validate_draft(self.draft(p,c),p)
        bad=self.draft(p);bad['paragraphs'][0]['source_ids']=['RIGHTS']
        with self.assertRaises(ValueError):validate_draft(bad,p)
        bad=self.draft(p);bad['image']={'url':'https://example.invalid/generic.jpg'}
        with self.assertRaises(ValueError):validate_draft(bad,p)
    def run_editorial(self,approved):
        p=self.packet();ingest(load_config(self.cfg),p,NOW);draft=self.draft(p)
        if not approved:draft['paragraphs'][0]['text']='Kaikki Suomen kirjastot avataan samana päivänä.'
        class OfflineModel:
            name='explicit-offline-test-double'
            def __init__(self):self.calls=[]
            def call(self,role,packet,draft_arg=None):
                self.calls.append(role)
                if role=='writer':return draft
                return {'approved':approved,'draft_sha256':digest(draft_arg),'reasons':['A supports Helsinki library facts' if approved else 'A does not support nationwide opening claim']}
        model=OfflineModel();result=tick(self.cfg,model=model,now=NOW);self.assertEqual(model.calls,['writer','reviewer']);return result
    def test_private_imageless_render_with_attribution(self):
        self.assertEqual(self.run_editorial(True)['status'],'rendered');html=next((self.root/'site/uutiset').glob('*/index.html')).read_text()
        for word in ['Ei kuvaa:','CC BY 4.0','tietoja on tiivistetty','noindex,nofollow']:self.assertIn(word,html)
        self.assertNotIn('<img',html);self.assertNotIn('kuvan käyttöoikeus on tarkastettu',html)
        with database(self.config['state_dir']) as store,self.assertRaises(ValueError):render_site(store,self.root/'public',self.root/'state',public=True)
        self.assertFalse((self.root/'public').exists())
    def test_review_rejection_has_no_render(self):
        self.assertEqual(self.run_editorial(False)['status'],'rejected');self.assertFalse((self.root/'site').exists())
    def test_draft_hash_change_invalidates_review(self):
        draft=self.draft(self.packet());review={'approved':True,'draft_sha256':digest(draft),'reasons':['A supports this text']};draft['title']='An unsupported change'
        with self.assertRaises(ValueError):validate_review(review,draft)
    def test_live_tick_refuses_before_state_or_model(self):
        with self.assertRaisesRegex(ValueError,'private preparation'):live_tick(self.cfg)
        self.assertFalse((self.root/'state').exists())
if __name__=='__main__':unittest.main()

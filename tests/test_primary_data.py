"""Real captured public bytes at historical clocks; all I/O/provider effects are fixtures.
No production data, credentials, network or live publication acceptance.
"""
import copy
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from news_mvp import primary_data as adapter, official, intake, release_contract as contract, publish
from news_mvp.editorial import digest
from news_mvp.store import database
from cutover.check_release import check

FIXTURE=Path(__file__).parent/'fixtures/statfin_primary_data'
ORIGINAL=json.loads((FIXTURE/'packet.json').read_text())
RAW=(FIXTURE/'source.html').read_bytes()
RIGHTS=(FIXTURE/'rights.html').read_bytes()
BUNDLE={'metadata':(FIXTURE/'primary-metadata.json').read_bytes(),
        'response':(FIXTURE/'primary-response.json').read_bytes(),
        'receipt':json.loads((FIXTURE/'primary-receipt.json').read_text())}
NOW=datetime.fromisoformat(BUNDLE['receipt']['retrieved_at'])
SOURCE=ORIGINAL['sources'][0]


def response(url,*args,**kwargs):
    if url==SOURCE['url']:return RAW
    if url==ORIGINAL['supporting_documents'][0]['url']:return RIGHTS
    raise AssertionError('Uncaptured boundary')


def draft(packet):
    return {'title':'Yksityinen taulukkosopimustesti','summary':'Synteettinen tekninen testi, ei toimituksellinen hyväksyntä.',
            'category':'Talous','paragraphs':[{'text':'YKHI-ennakon elintarvikkeiden vuosimuutos oli 1,9 prosenttia ja kuukausimuutos 0,8 prosenttia.','source_ids':['A']},
                                         {'text':'Yksityinen synteettinen tekninen kappale.','source_ids':['A']}],'image':None}


class PrimaryData(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name)
        self.transport=patch.object(official,'response',side_effect=response);self.transport.start()
    def tearDown(self):self.transport.stop();self.tmp.cleanup()
    def collect(self,b=BUNDLE):
        return official.collect({'provider':'stat','url':SOURCE['url']},self.state,now=NOW,primary_data=b)
    def clone(self,p,mutate):
        q=copy.deepcopy(p);mutate(q);self.assertNotEqual(q,p)
        old=self.state/'intake'/digest(p);new=self.state/'intake'/digest(q);new.mkdir()
        for f in old.iterdir():(new/f.name).write_bytes(f.read_bytes())
        return q
    def test_collection_reconstruction_and_same_publisher_rule(self):
        p,r=self.collect();contract.verify_intake(p,self.state)
        self.assertIn('vuosimuutos 1,9 %, kuukausimuutos 0,8 %',p['sources'][0]['text'])
        self.assertEqual(len(p['supporting_documents']),1);self.assertEqual(r['packet_sha256'],digest(p))
        self.assertIn('text_only',contract.media(p,draft(p)))
        q=copy.deepcopy(p);extra=copy.deepcopy(q['sources'][0]);extra.update(id='B',url=adapter.API,related=True);q['sources'].append(extra)
        with self.assertRaisesRegex(ValueError,'cannot corroborate itself'):contract.media(q,draft(q))
    def test_historical_html_only(self):
        p,r=self.collect(None);self.assertEqual(p['sources'][0],SOURCE)
        self.assertNotIn('primary_data',p['publication_basis']);contract.verify_intake(p,self.state)
    def test_default_normal_intake_and_later_capture_clock(self):
        b=copy.deepcopy(BUNDLE);b['receipt']['retrieved_at']=(NOW+timedelta(seconds=2)).isoformat()
        with patch.object(official,'capture_primary',return_value=b) as api:
            p,r=intake.collect({'family':'finnish-official','provider':'stat','url':SOURCE['url']},self.state,now=NOW)
        self.assertEqual(api.call_count,1)
        self.assertEqual(p['supporting_documents'][0]['retrieved_at'],b['receipt']['retrieved_at'])
        self.assertEqual(p['sources'][0]['published_at'],SOURCE['published_at']);contract.verify_intake(p,self.state)
    def test_default_api_failure_has_no_partial_packet(self):
        with patch.object(official,'capture_primary',side_effect=ValueError('Fixture API refusal')):
            with self.assertRaisesRegex(ValueError,'Fixture API refusal'):
                intake.collect({'family':'finnish-official','provider':'stat','url':SOURCE['url']},self.state,now=NOW)
        self.assertFalse((self.state/'intake').exists())
    def test_unlinked_source_skips_api(self):
        changed=RAW.replace(adapter.TABLE.encode(),b'https://example.invalid/unrelated.px');self.assertNotEqual(changed,RAW)
        def fetch(url,*args,**kwargs):return changed if url==SOURCE['url'] else response(url)
        with patch.object(official,'response',side_effect=fetch),patch.object(official,'capture_primary',side_effect=AssertionError('Unexpected API')):
            p,r=intake.collect({'family':'finnish-official','provider':'stat','url':SOURCE['url']},self.state,now=NOW)
        self.assertNotIn('primary_data',p['publication_basis']);contract.verify_intake(p,self.state)
    def test_timezone_equivalent_revision_and_wrong_instant(self):
        source=copy.deepcopy(SOURCE)
        published=datetime.fromisoformat(source['published_at'])
        source['published_at']=published.astimezone(timezone(timedelta(hours=3))).isoformat()
        binding,text=adapter.binding_and_text(BUNDLE,source,RAW,RIGHTS,NOW)
        self.assertEqual(binding['month'],'2026M09')
        # A Z timestamp is UTC, never the offset of the source publication.
        b=copy.deepcopy(BUNDLE);data=json.loads(b['response'])
        data['metadata'][0]['updated']=(published+timedelta(hours=3)).strftime('%Y-%m-%dT%H.%M.%SZ')
        b['response']=json.dumps(data).encode();b['receipt']['response_sha256']=adapter.sha(b['response'])
        with self.assertRaisesRegex(ValueError,'revision disagreement'):
            adapter.binding_and_text(b,source,RAW,RIGHTS,NOW)
    def test_current_stale_refusal_no_redating(self):
        with self.assertRaisesRegex(ValueError,'Stale or future release'):
            adapter.binding_and_text(BUNDLE,SOURCE,RAW,RIGHTS,NOW+timedelta(days=3))
        self.assertEqual(SOURCE['published_at'],'2026-10-02T05:00:00+00:00')
    def test_projection_unknown_and_downgrade(self):
        p,r=self.collect();q=copy.deepcopy(p);q['image']={'generated':True};q.pop('image_note')
        contract.verify_intake(q,self.state)
        q=copy.deepcopy(p);q['publication_basis']['primary_data']['schema']='statfin-primary-data-v999'
        with self.assertRaisesRegex(ValueError,'Unknown primary-data'):contract.media(q,draft(q))
        q=self.clone(p,lambda q:q['publication_basis'].pop('primary_data'))
        with self.assertRaisesRegex(ValueError,'downgrade'):contract.verify_intake(q,self.state)
    def test_text_edit_with_refreshed_digest_and_raw_bytes(self):
        p,r=self.collect()
        def mutate(q):
            q['sources'][0]['text']+='\nPolttoaine selittää kaiken.';q['publication_basis']['source_fields_sha256']=digest(q['sources'][0])
        q=self.clone(p,mutate)
        with self.assertRaisesRegex(ValueError,'differs from reviewed'):contract.verify_intake(q,self.state)
        f=self.state/'intake'/digest(p)/adapter.FILES['response'];f.write_bytes(f.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):contract.verify_intake(p,self.state)
    def test_rehashed_semantic_mutations(self):
        mutations=[lambda d:d['data'][0]['key'].__setitem__(0,'2026M08'),lambda d:d['columns'][2].__setitem__('text','Indeksipisteluku'),
                   lambda d:d['data'].pop(),lambda d:d['data'][0]['values'].__setitem__(0,'NaN'),
                   lambda d:d.__setitem__('comments',['Unreviewed note']),lambda d:d['data'][1].__setitem__('key',d['data'][0]['key'])]
        for i,mutate in enumerate(mutations):
            with self.subTest(i=i):
                b=copy.deepcopy(BUNDLE);data=json.loads(b['response']);before=copy.deepcopy(data);mutate(data);self.assertNotEqual(data,before)
                b['response']=json.dumps(data).encode();b['receipt']['response_sha256']=adapter.sha(b['response'])
                with self.assertRaises(ValueError):self.collect(b)
    def test_json_and_rights_boundaries(self):
        for raw in [b'{"a":1,"a":2}',b'{"a":NaN}',b' '*(512*1024+1)]:
            with self.assertRaises(ValueError):adapter.load(raw)
        q=copy.deepcopy(SOURCE);q['reuse']['license_url']='https://example.invalid/license'
        with self.assertRaises(ValueError):adapter.binding_and_text(BUNDLE,q,RAW,RIGHTS,NOW)
        changed=RAW.replace(adapter.TABLE.encode(),b'https://example.invalid/table');self.assertNotEqual(changed,RAW)
        with self.assertRaisesRegex(ValueError,'exact table'):adapter.binding_and_text(BUNDLE,SOURCE,changed,RIGHTS,NOW)
    def test_bounded_capture_exact_request_and_fail_closed_identity(self):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return NOW
        class Headers:
            def get_content_type(self):return 'application/json'
        class Response(io.BytesIO):
            status=200;headers=Headers()
            def geturl(self):return adapter.API
        class Opener:
            def __init__(self):self.calls=[]
            def open(self,req,timeout):
                self.calls.append((req,timeout));return Response(BUNDLE['metadata'] if req.data is None else BUNDLE['response'])
        opener=Opener()
        with patch('urllib.request.build_opener',return_value=opener),patch.object(adapter,'datetime',Clock):
            b=adapter.capture_primary(SOURCE,RAW,RIGHTS,NOW)
        self.assertEqual(len(opener.calls),2)
        self.assertEqual(json.loads(opener.calls[1][0].data),BUNDLE['receipt']['query'])
        self.assertTrue(all(req.full_url==adapter.API and timeout==10 for req,timeout in opener.calls))
        self.assertEqual(b['response'],BUNDLE['response'])
        with patch('urllib.request.build_opener',return_value=opener),patch.object(Response,'geturl',return_value='https://example.invalid/'):
            with self.assertRaisesRegex(ValueError,'identity'):adapter.capture_primary(SOURCE,RAW,RIGHTS,NOW)
    def bundle(self):
        p,r=self.collect();p.pop('image_note',None)
        raw=b'SYNTHETIC structural image bytes, not reviewed pixels';sha=adapter.sha(raw)
        image={'url':f'https://uutistenlukija.fi/media/{sha}.jpg','local_path':f'media/{sha}.jpg','sha256':sha,
               'source_url':'https://uutistenlukija.fi/ai-kuvat/','license_url':'https://uutistenlukija.fi/ai-kuvat/',
               'license':'AI-generated illustration','credit':'AI-kuvitus','alt':'AI-generoitu kuva: yksityinen testi',
               'caption':'AI-generoitu kuva. Ei valokuva tapahtumasta.','generated':True,'model':'synthetic',
               'prompt_sha256':'a'*64,'prompt_version':'test','subject':'synthetic'}
        p['image']=image;d=draft(p);d['image']=image
        (self.state/'media').mkdir();(self.state/'media'/f'{sha}.jpg').write_bytes(raw)
        with database(self.state) as store:
            publish.ensure_table(store);identity,_=store.admit(p,NOW.isoformat());store.save_draft(identity,d,'synthetic-editorial-boundary')
            store.finish_review(identity,{'approved':True,'draft_sha256':digest(d),'reasons':['Synthetic structural fixture']})
            with patch.object(publish,'cmd',return_value='a'*40):return publish.public_bundle(store,store.get(identity),self.state)
    def test_full_bundle_hosted_checker_and_rehashed_render_drift(self):
        root,receipt=self.bundle();self.assertGreater(check(root,receipt),10)
        self.assertIn('primary_data',receipt['packet']['publication_basis'])
        self.assertEqual(contract.receipt_media(receipt),contract.media(receipt['packet'],receipt['draft']))
        file=receipt['new_article_files'][0];path=root/file;html=path.read_text()
        changed=html.replace('vuosimuutos oli 1,9 prosenttia','vuosimuutos oli 9,9 prosenttia');self.assertNotEqual(changed,html)
        path.write_text(changed);bad=copy.deepcopy(receipt);bad['files'][file]=adapter.sha(path.read_bytes())
        with self.assertRaisesRegex(ValueError,'differs from reviewed'):check(root,bad)
    def test_hosted_unknown_dropped_basis_and_missing_image(self):
        root,receipt=self.bundle()
        for mutate in [lambda p:p['publication_basis']['primary_data'].__setitem__('schema','statfin-primary-data-v999'),lambda p:p['publication_basis'].pop('primary_data')]:
            bad=copy.deepcopy(receipt);mutate(bad['packet']);self.assertNotEqual(bad,receipt);bad['packet_sha256']=digest(bad['packet'])
            with self.assertRaises(ValueError):check(root,bad)
        (root/('mvp-assets/'+receipt['image_sha256']+'.jpg')).unlink()
        with self.assertRaises(ValueError):check(root,receipt)

"""Synthetic real-schema checks of internal evidence branch; no live providers."""
import dataclasses
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock
from news_mvp import imagery
from news_mvp.amendments import AmendmentEvidence, CaptureBinding, _digest

DECISION = {'version':'article-first-v1','category':'Kotimaa','concepts':[
    {'rank':1,'safe_to_generate':False,'subject':'Kuopion päiväkoteja',
     'depictable_scene':'Kuopion oikean päiväkodin sisäänkäynti.',
     'must_show':['daycare building'],'must_avoid':['faces'],
     'search_queries':['Kuopion päiväkoti rakennus','Kuopio daycare building','kindergarten building Kuopio']},
    {'rank':2,'safe_to_generate':True,'subject':'esiopetuksen oppilaaksiotto',
     'depictable_scene':'Esiopetuksen kirjoja tyhjällä pöydällä.',
     'must_show':['preschool books'],'must_avoid':['faces'],
     'search_queries':['esiopetuksen kirjat pöydällä','preschool books classroom','preschool learning materials']}]}

class AmendmentImageEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        raw = b'synthetic-retained-image'
        (self.state/'media').mkdir()
        (self.state/'media/source.jpg').write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()
        self.image = {'sha256':self.sha,'local_path':'media/source.jpg',
                      'url':'https://example.org/photo','source_url':'https://example.org/story',
                      'license':'Synthetic rights','license_url':'https://example.org/rights',
                      'credit':'Synthetic source','generated':False,
                      'stock_provenance':{'provider':'pexels'}}
        self.draft = {'title':'Kuopio tarkentaa esiopetuksen oppilaaksiottoa',
                      'summary':'Kuopio tarkentaa esiopetuksen käytäntöjä.',
                      'category':'Kotimaa','paragraphs':[{'text':'Kuopion päiväkodit ja esiopetuksen oppilaaksiotto.','source_ids':['A']}],
                      'image':self.image}
        from tests.test_amendment_review import artifact_bytes
        from news_mvp.amendment_review import build_review_envelope
        artifact = json.loads(artifact_bytes())
        job = artifact['predecessor']['job']
        predecessor = json.loads(job['draft'])
        predecessor.update(title=self.draft['title'], category='Kotimaa', image=self.image)
        artifact['candidate_manuscript'].update(title=self.draft['title'], category='Kotimaa')
        predecessor['paragraphs'][0]['text'] = self.draft['paragraphs'][0]['text']
        artifact['candidate_manuscript']['paragraphs'][0]['text'] = predecessor['paragraphs'][0]['text']
        job['draft'] = json.dumps(predecessor)
        publication = artifact['predecessor']['publication']
        publication['draft_sha'] = _digest(predecessor)
        publication['image_sha'] = self.sha
        artifact['evidence']['predecessor_draft_sha256'] = _digest(predecessor)
        artifact['evidence']['predecessor_publication_sha256'] = _digest(publication)
        self.preparation = json.dumps(artifact).encode()
        self.packet = build_review_envelope(self.preparation)
        self.draft = self.packet['final_draft']
        self.predecessor = predecessor
        self.predecessor_packet = json.loads(job['packet'])
        self.artifact = artifact
        self.db = sqlite3.connect(self.state/'jobs.sqlite')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE jobs (
            id TEXT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE,
            source_url TEXT NOT NULL UNIQUE, packet TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, draft TEXT, review TEXT,
            adapter TEXT, created_at TEXT NOT NULL, error TEXT);
            CREATE TABLE publications (
            job_id TEXT PRIMARY KEY, packet_sha TEXT NOT NULL, draft_sha TEXT NOT NULL,
            image_sha TEXT, source_commit TEXT NOT NULL, remote_commit TEXT,
            run_id INTEGER, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT);''')
        self.target = '1'*64
        self.add_job(self.target, self.predecessor, self.predecessor_packet, 'rendered')
        self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?)',
                        tuple(publication[key] for key in ('job_id','packet_sha','draft_sha','image_sha',
                            'source_commit','remote_commit','run_id','status','attempts','error')))
        fields = dict(artifact['evidence'])
        for role in ('original_capture', 'update_capture'):
            fields[role] = CaptureBinding(**fields[role])
        self.evidence = AmendmentEvidence(**fields)
        self.db.commit()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.providers = [self.stack.enter_context(mock.patch.object(imagery, name, return_value=None))
                          for name in ('fetch_pexels','fetch_unsplash','fetch_wikimedia','fetch_google')]
        self.generation = self.stack.enter_context(mock.patch.object(imagery, '_build_image', return_value=None))
        self.pixels = self.stack.enter_context(mock.patch.object(imagery, 'review_pixels', side_effect=self.review))
        for name in ('news_mvp.release_contract.stock_binding', 'news_mvp.release_contract.media','news_mvp.image_providers.candidate_event',
                     'news_mvp.imagery._verify_attached_source_image'):
            self.stack.enter_context(mock.patch(name))

    def add_job(self, owner, draft, packet=None, status='rejected'):
        self.db.execute('INSERT INTO jobs(id,story_key,source_url,packet,draft,status,created_at) VALUES(?,?,?,?,?,?,?)',
            (owner,owner,'https://example.org/'+owner,json.dumps(packet or {}),json.dumps(draft),status,'2026-09-21T14:00:00Z'))
        self.db.commit()

    def review(self, raw, draft, generated=False, concept=None, **kwargs):
        return {'approved':True,'fit_score':9,'must_show_visible':[True],
                'image_sha256':hashlib.sha256(raw).hexdigest(),
                'article_text_sha256':imagery._article_text_sha(draft),'concept_sha256':_digest(concept),
                'alt_fi':'Päiväkodin sisäänkäynti näkyy kuvassa.',
                'description':'Real daycare exterior.','reason':'Synthetic fit.','no_people':True}

    def call(self, draft=None, evidence=None, ordinary=False, packet=None):
        before = (self.state/'jobs.sqlite').read_bytes()
        try:
            return imagery._build_image_article_first(draft or self.draft,self.state,'Kotimaa','fixture',1,
                DECISION,False,True,self.packet if packet is None else packet,
                **({} if ordinary else {'amendment_evidence':self.evidence if evidence is None else evidence,
                                          'amendment_preparation_bytes':self.preparation}))
        finally:
            self.assertEqual(before,(self.state/'jobs.sqlite').read_bytes())

    def assert_no_effects(self):
        self.pixels.assert_not_called()
        self.generation.assert_not_called()
        for provider in self.providers: provider.assert_not_called()

    def test_corrected_text_positive_with_real_preparation_envelope(self):
        self.assertNotEqual(self.draft, self.predecessor)
        self.assertEqual(self.packet['actual_diff']['text_change_indices'], [6])
        chosen = self.call()
        self.assertEqual(chosen['sha256'], self.sha)
        self.assertEqual(self.pixels.call_count, 2)
        for provider in self.providers: provider.assert_not_called()
        self.generation.assert_not_called()

    def test_substituted_preparation_refused_before_effects(self):
        from news_mvp.amendment_assessments import MAX_ARTIFACT_BYTES
        variants = [b'{}', b'{"schema":1,"schema":2}', b'\xff',
                    b' ' * (MAX_ARTIFACT_BYTES + 1), bytearray(self.preparation),
                    self.preparation.decode()]
        changed = json.loads(self.preparation)
        changed['candidate_manuscript']['paragraphs'][5]['text'] = 'Substituted corrected text.'
        variants.append(json.dumps(changed).encode())
        broken = json.loads(self.preparation)
        broken['rights'] = []
        variants.append(json.dumps(broken).encode())
        for preparation in variants:
            with self.subTest(kind=type(preparation), size=len(preparation)):
                self.preparation = preparation
                self.assertIsNone(self.call())
                self.assert_no_effects()

    def test_substituted_packet_refused_before_effects(self):
        self.assertIsNone(self.call(packet={**self.packet, 'scope':'substituted'}))
        self.assert_no_effects()

    def test_either_optional_argument_missing_refused_before_effects(self):
        for options in ({'amendment_evidence':self.evidence},
                        {'amendment_preparation_bytes':self.preparation}):
            self.assertIsNone(imagery._build_image_article_first(
                self.draft,self.state,'Kotimaa','fixture',1,DECISION,False,True,self.packet,**options))
            self.assert_no_effects()

    def test_different_publisher_envelope_refused_before_effects(self):
        from news_mvp.amendment_review import build_review_envelope
        artifact = json.loads(self.preparation)
        capture = artifact['captures']['update']
        source = capture['packet']['sources'][0]
        source['publisher'] = 'Other synthetic publisher'
        capture['packet']['publication_basis']['source_fields_sha256'] = _digest(source)
        capture['receipt']['packet_sha256'] = _digest(capture['packet'])
        artifact['citations'][1]['capture_source'] = source
        artifact['rights'][1]['publication_basis'] = capture['packet']['publication_basis']
        self.preparation = json.dumps(artifact).encode()
        self.packet = build_review_envelope(self.preparation)
        self.assertFalse(self.packet['source_relationship']['same_publisher'])
        self.assertIsNone(self.call())
        self.assert_no_effects()

    def test_unbound_amended_final_draft_refused_before_effects(self):
        self.assertIsNone(self.call(draft={**self.draft,'summary':'Changed final amendment text.'}))
        self.assert_no_effects()

    def test_arbitrary_evidence_refused_before_effects(self):
        self.assertIsNone(self.call(evidence={'job_id':self.target}))
        self.assert_no_effects()

    def test_stale_evidence_refused_before_effects(self):
        self.assertIsNone(self.call(evidence=dataclasses.replace(self.evidence,predecessor_publication_sha256='9'*64)))
        self.assert_no_effects()

    def test_other_job_identical_text_retained_pixels_refused(self):
        self.add_job('7'*64,self.draft)
        self.assertIsNone(self.call())
        self.assert_no_effects()

    def test_rejected_retained_image_refused(self):
        folder=self.state/'image-rejections'/'synthetic'; folder.mkdir(parents=True)
        (folder/'reject.json').write_text(json.dumps({'review':{'approved':False,'image_retryable':True},'draft':{'image':self.image}}))
        self.assertIsNone(self.call())
        self.assert_no_effects()

    def test_missing_database_not_created(self):
        self.db.close(); (self.state/'jobs.sqlite').unlink()
        self.assertIsNone(imagery._build_image_article_first(self.draft,self.state,'Kotimaa','fixture',1,
                          DECISION,False,True,self.packet,amendment_evidence=self.evidence,
                          amendment_preparation_bytes=self.preparation))
        self.assertFalse((self.state/'jobs.sqlite').exists())
        self.assert_no_effects()

    def test_other_job_candidate_stays_excluded_before_pixel_review(self):
        other = {**self.image,'local_path':'media/other.jpg','sha256':hashlib.sha256(b'other').hexdigest()}
        (self.state/'media/other.jpg').write_bytes(b'other')
        self.add_job('7'*64,{'image':other})
        self.providers[0].side_effect = lambda *args, **kw: kw['accept'](other)
        self.pixels.side_effect = lambda *args, **kw: {'approved':False,'fit_score':0,'reason':'Retained fit failed'}
        self.assertIsNone(self.call())
        self.assertEqual(self.providers[0].call_count, 2)
        self.assertEqual(self.pixels.call_count, 2)
        self.generation.assert_not_called()

    def test_read_only_transaction_rolled_back_and_connection_closed(self):
        from news_mvp import amendment_image_identity
        real = amendment_image_identity.retained_image_identity
        connections = []
        def checked(db, evidence, image, state_dir):
            connections.append(db)
            self.assertTrue(db.in_transaction)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE jobs SET status='failed'")
            result = real(db, evidence, image, state_dir)
            self.assertFalse(result['exhaustive_cross_image_byte_comparison'])
            return result
        with mock.patch.object(amendment_image_identity,'retained_image_identity',side_effect=checked):
            self.assertEqual(self.call()['sha256'],self.sha)
        self.assertEqual(len(connections),1)
        with self.assertRaises(sqlite3.ProgrammingError): connections[0].execute('SELECT 1')

    def test_malformed_other_owner_refused_before_effects(self):
        self.add_job('7'*64,{'image':{'sha256':'not-a-hash'}})
        self.assertIsNone(self.call())
        self.assert_no_effects()

    def test_evidence_subclass_refused_before_effects(self):
        class AlternateEvidence(AmendmentEvidence): pass
        alternate = AlternateEvidence(**{field.name:getattr(self.evidence,field.name)
                                         for field in dataclasses.fields(self.evidence)})
        self.assertIsNone(self.call(evidence=alternate))
        self.assert_no_effects()

    def test_rejected_different_candidate_stays_excluded(self):
        other = {**self.image,'local_path':'media/rejected.jpg','sha256':hashlib.sha256(b'rejected').hexdigest()}
        (self.state/'media/rejected.jpg').write_bytes(b'rejected')
        folder=self.state/'image-rejections'/'synthetic'; folder.mkdir(parents=True)
        (folder/'reject.json').write_text(json.dumps({'review':{'approved':False,'image_retryable':True},'draft':{'image':other}}))
        self.providers[0].side_effect = lambda *args, **kw: kw['accept'](other)
        self.pixels.side_effect = lambda *args, **kw: {'approved':False,'fit_score':0,'reason':'Retained fit failed'}
        self.assertIsNone(self.call())
        self.assertEqual(self.providers[0].call_count, 2)
        self.assertEqual(self.pixels.call_count, 2)
        self.generation.assert_not_called()

    def rebind_image(self, image):
        from news_mvp.amendment_review import build_review_envelope
        artifact = json.loads(self.preparation)
        predecessor = json.loads(artifact['predecessor']['job']['draft'])
        predecessor['image'] = image
        artifact['predecessor']['job']['draft'] = json.dumps(predecessor)
        publication = artifact['predecessor']['publication']
        publication['draft_sha'] = _digest(predecessor)
        artifact['evidence']['predecessor_draft_sha256'] = _digest(predecessor)
        artifact['evidence']['predecessor_publication_sha256'] = _digest(publication)
        self.db.execute('UPDATE jobs SET draft=? WHERE id=?', (json.dumps(predecessor), self.target))
        self.db.execute('UPDATE publications SET draft_sha=? WHERE job_id=?', (_digest(predecessor), self.target))
        self.db.commit()
        self.preparation = json.dumps(artifact).encode()
        self.packet = build_review_envelope(self.preparation)
        self.draft = self.packet['final_draft']
        self.evidence = dataclasses.replace(self.evidence,
            predecessor_draft_sha256=_digest(predecessor),
            predecessor_publication_sha256=_digest(publication))

    def test_provider_fallback_every_concept(self):
        other = {**self.image, 'local_path':'media/fallback.jpg',
                 'sha256':hashlib.sha256(b'fallback').hexdigest()}
        (self.state/'media/fallback.jpg').write_bytes(b'fallback')
        self.pixels.side_effect = lambda raw, *args, **kw: (
            self.review(raw, *args, **kw) if raw == b'fallback' else
            {'approved':False,'fit_score':0,'reason':'Retained fit failed'})
        self.providers[0].side_effect = lambda *args, **kw: kw['accept'](other)
        self.assertEqual(self.call()['sha256'], other['sha256'])
        self.assertEqual(self.providers[0].call_count, 2)
        self.assertEqual(self.pixels.call_count, 4)
        self.providers[2].assert_not_called()
        self.providers[3].assert_not_called()
        self.generation.assert_not_called()

    def test_nonstock_retained_refused_before_effects(self):
        self.rebind_image({k:v for k,v in self.image.items() if k != 'stock_provenance'})
        self.assertIsNone(self.call())
        self.assert_no_effects()

    def test_stored_review_hash_hotlink_changed_bytes_before_pixels(self):
        image = {k:v for k,v in self.image.items() if k not in {'sha256','local_path'}}
        image.update(hotlink=True, pixel_review={'image_sha256':self.sha})
        self.rebind_image(image)
        with mock.patch.object(imagery, '_get_external_bytes', return_value=b'changed'):
            self.assertIsNone(self.call())
        self.pixels.assert_not_called()
        self.assertEqual(self.providers[0].call_count, 2)
        self.assertEqual(self.providers[1].call_count, 2)
        self.generation.assert_not_called()

    def test_stored_review_hash_hotlink_matching_bytes_proceeds(self):
        image = {k:v for k,v in self.image.items() if k not in {'sha256','local_path'}}
        image.update(hotlink=True, pixel_review={'image_sha256':self.sha})
        self.rebind_image(image)
        with mock.patch.object(imagery, '_get_external_bytes', return_value=b'synthetic-retained-image'):
            self.assertEqual(self.call()['pixel_review']['image_sha256'], self.sha)
        self.assertEqual(self.pixels.call_count, 2)

    def test_changed_retained_hotlink_can_select_stock_replacement(self):
        image = {k:v for k,v in self.image.items() if k not in {'sha256','local_path'}}
        image.update(hotlink=True, pixel_review={'image_sha256':self.sha})
        self.rebind_image(image)
        other = {**self.image, 'local_path':'media/replacement.jpg',
                 'sha256':hashlib.sha256(b'replacement').hexdigest()}
        (self.state/'media/replacement.jpg').write_bytes(b'replacement')
        self.providers[0].side_effect = lambda *args, **kw: kw['accept'](other)
        with mock.patch.object(imagery, '_get_external_bytes', return_value=b'changed'):
            self.assertEqual(self.call()['sha256'], other['sha256'])
        self.assertEqual(self.pixels.call_count, 2)
        self.assertTrue(all(call.args[0] == b'replacement' for call in self.pixels.call_args_list))
        self.generation.assert_not_called()

    def test_optional_no_real_candidate_does_not_enter_generated_fallback(self):
        self.pixels.side_effect = lambda *args, **kwargs: {'approved':False,'fit_score':0,'reason':'Rejected synthetic pixels'}
        self.assertIsNone(self.call())
        self.assertEqual(self.pixels.call_count, 2)
        self.assertEqual(self.providers[0].call_count, 2)
        self.assertEqual(self.providers[1].call_count, 2)
        self.providers[2].assert_not_called()
        self.providers[3].assert_not_called()
        self.generation.assert_not_called()

    def test_ordinary_path_unchanged_and_generation_fallback_available(self):
        self.assertIsNone(self.call(ordinary=True,packet={}))
        self.generation.assert_called_once()

    def test_historical_unhashed_hotlinks_do_not_get_invented_hashes(self):
        for number in range(8):
            self.add_job(hashlib.sha256(str(number).encode()).hexdigest(),
                         {'image':{'hotlink':True,'generated':False,'url':'https://example.org/historical/'+str(number)}})
        self.assertEqual(self.call()['sha256'],self.sha)

if __name__ == '__main__': unittest.main()

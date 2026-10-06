"""Synthetic only: no state/capture reads outside private temporary fixtures."""
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from news_mvp.amendments import AmendmentEvidence, CaptureBinding, _digest

BASE = Path(__file__).parent

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=BASE)
        self.directory = Path(self.tmp.name)
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE publications (job_id TEXT PRIMARY KEY, packet_sha TEXT NOT NULL, draft_sha TEXT NOT NULL, image_sha TEXT, source_commit TEXT NOT NULL, remote_commit TEXT, run_id INTEGER, status TEXT NOT NULL, attempts INTEGER NOT NULL, error TEXT)')
        self.db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, story_key TEXT, source_url TEXT, packet TEXT, draft TEXT, review TEXT, status TEXT, created_at TEXT)')
        self.original = self.packet('original')
        self.update = self.packet('update')
        self.candidate = {'category':'Culture','title':'Stable title','summary':'New schedule', 'paragraphs':[{'text':'Updated schedule.', 'source_ids':['amendment:original:A','amendment:update:A']}]}
        self.old_draft = copy.deepcopy(self.candidate)
        self.old_draft['summary'] = 'Old schedule'
        self.job_id = 'a'*64
        self.pub = dict(zip(('job_id','packet_sha','draft_sha','image_sha','source_commit','remote_commit','run_id','status','attempts','error'), (self.job_id,_digest(self.original),_digest(self.old_draft),None,'abc','def',1,'deployed',1,None)))
        self.db.execute('INSERT INTO publications VALUES (?,?,?,?,?,?,?,?,?,?)', tuple(self.pub.values()))
        self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',(self.job_id,self.original['story_key'],self.original['sources'][0]['url'],encode(self.original).decode(),encode(self.old_draft).decode(),'{"approved":true}', 'rendered','2026-01-01T00:00:00+00:00'))
        self.raws = [encode(self.original), encode({'synthetic': 'original'}), encode(self.update), encode({'synthetic': 'update'})]
        self.bind()
        self.module = importlib.import_module('news_mvp.amendment_preparation')
        self.original_validation_draft = dict(copy.deepcopy(self.old_draft), image=None)
        self.update_validation_draft = dict(copy.deepcopy(self.candidate), image=None)
        self.calls = []
        def reconstruct(packet, draft, packet_raw, receipt_raw, state):
            self.calls.append(packet['sources'][0]['url'])
            expected = self.original if packet['sources'][0]['url'].endswith('/original') else self.update
            i = 0 if expected is self.original else 2
            if packet != expected or packet_raw != self.raws[i] or receipt_raw != self.raws[i+1]:
                raise ValueError('Synthetic reconstruction refused')
        self.mock = patch.object(self.module, '_reconstruct', side_effect=reconstruct, autospec=True)
        self.mock.start()

    def packet(self, role):
        url = 'https://www.vantaa.fi/fi/ajankohtaista/uutinen/'+role
        return {'story_key':'url:'+url,'image':None,'image_note':'text only','publication_basis':{'provider':'vantaa'},'sources':[{'id':'A','url':url,'publisher':'Vantaan kaupunki','title':role,'text':role+' schedule','reuse':{'license':'synthetic'}}], 'supporting_documents':[{'id':'RIGHTS','url':'https://www.vantaa.fi/rights','text':'Synthetic rights','sha256':'b'*64}]}

    def bind(self):
        binding = lambda i: CaptureBinding(*(hashlib.sha256(v).hexdigest() for v in self.raws[i:i+2]))
        self.evidence = AmendmentEvidence('published-amendment-preparation-v1',self.job_id,_digest(self.original),_digest(self.old_draft),_digest(self.pub),binding(0),binding(2),'Schedule changed','2026-02-01T00:00:00+00:00')

    def run_prepare(self, **kwargs):
        arguments = dict(db=self.db,evidence=self.evidence,original_packet_bytes=self.raws[0],original_receipt_bytes=self.raws[1],update_packet_bytes=self.raws[2],update_receipt_bytes=self.raws[3],original_validation_draft=self.original_validation_draft,update_validation_draft=self.update_validation_draft,candidate=self.candidate,state_root=self.directory/'unused-state',artifact_directory=self.directory)
        arguments.update(kwargs)
        return self.module.prepare(**arguments)

    def tearDown(self):
        if hasattr(self,'mock'):
            self.mock.stop()
        self.db.close()
        self.tmp.cleanup()

    def test_preparation_preserves_predecessor_and_two_roles(self):
        before = self.db.total_changes
        result = self.run_prepare()
        artifact = json.loads(Path(result['artifact_path']).read_bytes())
        self.assertEqual(self.calls,[self.original['sources'][0]['url'],self.update['sources'][0]['url']])
        self.assertEqual(artifact['predecessor']['job']['review'],'{"approved":true}')
        self.assertEqual(artifact['identity']['story_key'],self.original['story_key'])
        self.assertEqual(artifact['identity']['created_at'],'2026-01-01T00:00:00+00:00')
        self.assertFalse(artifact['approval'])
        self.assertFalse(artifact['activation'])
        self.assertEqual([v['role'] for v in artifact['citations']],['original','update'])
        self.assertEqual(self.db.total_changes,before)
        self.assertEqual(json.loads(Path(result['reference_path']).read_bytes())['artifact_sha256'],result['artifact_sha256'])

    def assert_refused(self, **kwargs):
        before = self.db.total_changes
        listing = sorted(p.name for p in self.directory.iterdir())
        with self.assertRaises((ValueError, OSError, KeyError)):
            self.run_prepare(**kwargs)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()),listing)
        self.assertEqual(self.db.total_changes,before)

    def test_capture_byte_mutations_refused_without_writes(self):
        for field, index in [('original_packet_bytes',0),('original_receipt_bytes',1),('update_packet_bytes',2),('update_receipt_bytes',3)]:
            with self.subTest(field=field):
                self.assert_refused(**{field:self.raws[index]+b' '})

    def test_predecessor_mutation_refused_without_writes(self):
        self.db.execute("UPDATE jobs SET draft=?", ('{}',))
        self.assert_refused()

    def test_capture_roles_cannot_be_swapped(self):
        self.assert_refused(original_packet_bytes=self.raws[2],original_receipt_bytes=self.raws[3],update_packet_bytes=self.raws[0],update_receipt_bytes=self.raws[1])

    def test_original_projection_mutation_even_when_rebound(self):
        original = copy.deepcopy(self.original)
        original['sources'][0]['text'] = 'Changed text'
        self.raws[0] = encode(original)
        self.bind()
        self.assert_refused()

    def test_original_job_story_key_must_match(self):
        self.db.execute("UPDATE jobs SET story_key='url:https://wrong.example'")
        self.assert_refused()

    def test_provider_publisher_and_related_source_refused(self):
        saved = copy.deepcopy(self.update)
        for change in ('provider','publisher','related'):
            with self.subTest(change=change):
                self.update = copy.deepcopy(saved)
                if change == 'provider':
                    self.update['publication_basis']['provider'] = 'helsinki'
                elif change == 'publisher':
                    self.update['sources'][0]['publisher'] = 'Other publisher'
                else:
                    self.update['sources'][0]['related'] = True
                self.raws[2] = encode(self.update)
                self.bind()
                self.assert_refused()

    def test_same_url_refused_even_with_distinct_bytes(self):
        self.update['sources'][0]['url'] = self.original['sources'][0]['url']
        self.update['story_key'] = self.original['story_key']
        self.raws[2] = encode(self.update)
        self.bind()
        self.assert_refused()

    def test_candidate_fields_title_category_and_citations_refused(self):
        variants = []
        for field in ('status','created_at','image','approval'):
            candidate = copy.deepcopy(self.candidate)
            candidate[field] = 'forged'
            variants.append(candidate)
        for field in ('title','category'):
            candidate = copy.deepcopy(self.candidate)
            candidate[field] = 'Changed'
            variants.append(candidate)
        for ids in (['A'],['amendment:original:A'],[],['amendment:update:A','amendment:update:A']):
            candidate = copy.deepcopy(self.candidate)
            candidate['paragraphs'][0]['source_ids'] = ids
            variants.append(candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate['paragraphs'][0]['control'] = True
        variants.append(candidate)
        for candidate in variants:
            with self.subTest(candidate=candidate):
                self.assert_refused(candidate=candidate)

    def test_reconstruction_failure_of_either_capture_refused(self):
        self.mock.stop()
        for index in (0,1):
            self.calls.clear()
            def refusal(*args):
                self.calls.append(args[0]['story_key'])
                if len(self.calls)-1 == index:
                    raise ValueError('Unreconstructable licensed evidence')
            with patch.object(self.module,'_reconstruct',side_effect=refusal,autospec=True):
                self.assert_refused()
            self.assertEqual(len(self.calls),index+1)

    def test_append_duplicate_does_not_overwrite(self):
        result = self.run_prepare()
        before = {p.name:p.read_bytes() for p in self.directory.iterdir()}
        with self.assertRaises(FileExistsError):
            self.run_prepare()
        self.assertEqual({p.name:p.read_bytes() for p in self.directory.iterdir()},before)
        self.assertEqual(hashlib.sha256(Path(result['artifact_path']).read_bytes()).hexdigest(),result['artifact_sha256'])

    def test_artifact_directory_symlink_refused(self):
        actual = self.directory/'actual'
        actual.mkdir(mode=0o700)
        link = self.directory/'link'
        link.symlink_to(actual, target_is_directory=True)
        self.assert_refused(artifact_directory=link)
        self.assertEqual(list(actual.iterdir()),[])

    def test_parent_directory_symlink_refused(self):
        actual = self.directory/'actual'
        actual.mkdir(mode=0o700)
        (actual/'child').mkdir(mode=0o700)
        link = self.directory/'link'
        link.symlink_to(actual,target_is_directory=True)
        self.assert_refused(artifact_directory=link/'child')
        self.assertEqual(list((actual/'child').iterdir()),[])

    def test_existing_artifact_symlink_is_not_followed(self):
        result = self.run_prepare()
        artifact = Path(result['artifact_path'])
        artifact.unlink()
        target = self.directory/'target'
        target.write_bytes(b'untouched')
        artifact.symlink_to(target)
        self.assert_refused()
        self.assertEqual(target.read_bytes(),b'untouched')

    def test_private_directory_required(self):
        self.directory.chmod(0o755)
        self.assert_refused()

    def test_bounded_inputs_refused(self):
        self.assert_refused(update_packet_bytes=b' '* (self.module.MAX_CAPTURE+1))
        candidate = copy.deepcopy(self.candidate)
        candidate['summary'] = 'x'*3001
        self.assert_refused(candidate=candidate)

    def test_default_reconstruction_uses_installed_verifier_twice(self):
        # This replaces only the installed read/reconstruction boundaries with
        # synthetic fixtures. It never reads a live intake capture.
        self.mock.stop()
        state = self.directory/'synthetic-state'
        from news_mvp.release_contract import digest
        for packet, index in ((self.original,0),(self.update,2)):
            capture = state/'intake'/digest(packet)
            capture.mkdir(parents=True)
            for name, raw in [('packet.json',self.raws[index]),('receipt.json',self.raws[index+1]),('source.html',b'x'*self.module.MAX_HTML),('rights.html',b'synthetic rights')]:
                (capture/name).write_bytes(raw)
        with patch('news_mvp.release_contract.media', return_value={}, autospec=True) as policy, patch('news_mvp.release_contract.verify_intake', return_value=None, autospec=True) as verifier:
            self.run_prepare(state_root=state)
            self.assertEqual(verifier.call_count,2)
            self.assertEqual([c.args[0] for c in verifier.call_args_list],[self.original,self.update])
            self.assertTrue(all(not c.kwargs for c in verifier.call_args_list))
            self.assertEqual(policy.call_count,2)
            self.assertEqual([c.args for c in policy.call_args_list],[(self.original,self.original_validation_draft),(self.update,self.update_validation_draft)])
            self.assertTrue(all(not c.kwargs for c in policy.call_args_list))

    def test_boolean_verifier_is_not_licensing_proof(self):
        self.mock.stop()
        state = self.directory/'synthetic-state'
        from news_mvp.release_contract import digest
        capture = state/'intake'/digest(self.original)
        capture.mkdir(parents=True)
        for name, raw in [('packet.json',self.raws[0]),('receipt.json',self.raws[1]),('source.html',b'synthetic'),('rights.html',b'synthetic')]:
            (capture/name).write_bytes(raw)
        with patch('news_mvp.release_contract.media',return_value={},autospec=True), patch('news_mvp.release_contract.verify_intake',return_value=True,autospec=True):
            with self.assertRaises(ValueError):
                self.module._reconstruct(self.original,self.original_validation_draft,self.raws[0],self.raws[1],state)

    def test_lexical_parent_component_refused(self):
        actual = self.directory/'actual'
        actual.mkdir(mode=0o700)
        self.assert_refused(artifact_directory=actual/'..')

    def test_artifact_size_refusal_has_no_writes(self):
        with patch.object(self.module,'MAX_ARTIFACT',1):
            self.assert_refused()

    def test_durability_orders_artifact_before_reference(self):
        seen = []
        append = self.module._append
        def ordered(fd,name,raw):
            if name.endswith('.ref'):
                artifact_name = name[:-4]+'.json'
                leaf = os.open(artifact_name,os.O_RDONLY,dir_fd=fd)
                os.close(leaf)
            seen.append(name)
            return append(fd,name,raw)
        with patch.object(self.module,'_append',side_effect=ordered):
            self.run_prepare()
        self.assertTrue(seen[0].endswith('.json'))
        self.assertTrue(seen[1].endswith('.ref'))

    def test_reference_failure_leaves_only_durable_orphan_artifact(self):
        append = self.module._append
        def crash(fd,name,raw):
            if name.endswith('.ref'):
                raise OSError('Synthetic crash before reference')
            return append(fd,name,raw)
        with patch.object(self.module,'_append',side_effect=crash):
            with self.assertRaises(OSError):
                self.run_prepare()
        entries = list(self.directory.iterdir())
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0].suffix,'.json')
        self.assertTrue(json.loads(entries[0].read_bytes())['preparation_only'])

    def test_forged_receipt_bound_bytes_still_need_reconstruction(self):
        self.mock.stop()
        self.raws[3] = encode({'approved':True,'license':'invented'})
        self.bind()
        def reconstruct(packet,*args):
            if packet == self.update:
                raise ValueError('Synthetic installed receipt reconstruction failure')
        with patch.object(self.module,'_reconstruct',side_effect=reconstruct,autospec=True):
            self.assert_refused()

    def test_duplicate_json_keys_refused_even_if_hashes_rebound(self):
        self.raws[3] = b'{"proof":true,"proof":false}'
        self.bind()
        self.assert_refused()

    def test_capture_symlink_refused_before_verifier(self):
        self.mock.stop()
        state = self.directory/'synthetic-state'
        from news_mvp.release_contract import digest
        capture = state/'intake'/digest(self.original)
        capture.mkdir(parents=True)
        for name,raw in [('packet.json',self.raws[0]),('receipt.json',self.raws[1]),('rights.html',b'synthetic')]:
            (capture/name).write_bytes(raw)
        target = self.directory/'synthetic-source'
        target.write_bytes(b'synthetic')
        (capture/'source.html').symlink_to(target)
        with patch('news_mvp.release_contract.verify_intake',autospec=True) as verifier:
            self.assert_refused(state_root=state)
            verifier.assert_not_called()

    def test_validation_drafts_are_provenance_not_approval(self):
        result = self.run_prepare()
        artifact = json.loads(Path(result['artifact_path']).read_bytes())
        for role, draft in [('original',self.original_validation_draft),('update',self.update_validation_draft)]:
            self.assertEqual(artifact['captures'][role]['validation_draft'],draft)
        self.assertEqual(artifact['validation_drafts_purpose'],'capture-validation-provenance-only-not-amendment-approval')
        self.assertEqual(artifact['candidate_manuscript'],self.candidate)
        self.assertFalse(artifact['approval'])

    def test_validation_draft_images_and_original_text_mutation_refused(self):
        for field in ('original_validation_draft','update_validation_draft'):
            draft = copy.deepcopy(getattr(self,field))
            draft['image'] = {'forged':True}
            self.assert_refused(**{field:draft})
            draft.pop('image')
            self.assert_refused(**{field:draft})
        draft = copy.deepcopy(self.original_validation_draft)
        draft['summary'] = 'Not predecessor text'
        self.assert_refused(original_validation_draft=draft)

    def test_html_boundary_retains_json_bound(self):
        path = self.directory/'source.html'
        fd = self.module._directory(self.directory)
        try:
            path.write_bytes(b'x'*self.module.MAX_HTML)
            self.assertEqual(len(self.module._read_at(fd,'source.html',self.module.MAX_HTML)),self.module.MAX_HTML)
            with self.assertRaises(ValueError):
                self.module._read_at(fd,'source.html')
            path.write_bytes(b'x'*(self.module.MAX_HTML+1))
            with self.assertRaises(ValueError):
                self.module._read_at(fd,'source.html',self.module.MAX_HTML)
        finally:
            os.close(fd)

    def test_actual_media_signature_regression(self):
        from news_mvp.release_contract import media
        import inspect
        signature = inspect.signature(media)
        signature.bind(self.original,self.original_validation_draft)
        self.assertIs(signature.parameters['policy_gate'].default,True)
        with self.assertRaises(TypeError):
            signature.bind(self.original,required=False)

    def test_update_validation_draft_policy_refusal_prevents_artifact(self):
        self.mock.stop()
        from news_mvp.release_contract import digest
        state = self.directory/'synthetic-state'
        for packet, index in ((self.original,0),(self.update,2)):
            capture = state/'intake'/digest(packet)
            capture.mkdir(parents=True)
            for name, raw in [('packet.json',self.raws[index]),('receipt.json',self.raws[index+1]),('source.html',b'synthetic'),('rights.html',b'synthetic')]:
                (capture/name).write_bytes(raw)
        def gate(packet,draft,policy_gate=True):
            self.assertTrue(policy_gate)
            if packet == self.update:
                self.assertEqual(draft,self.update_validation_draft)
                raise ValueError('Synthetic update draft rejected by installed media boundary')
        with patch('news_mvp.release_contract.media',autospec=True,side_effect=gate) as policy, patch('news_mvp.release_contract.verify_intake',autospec=True,return_value=None) as verifier:
            self.assert_refused(state_root=state)
            self.assertEqual(policy.call_count,2)
            self.assertEqual(verifier.call_count,1)

    def test_validation_draft_json_bound(self):
        draft = copy.deepcopy(self.update_validation_draft)
        draft['summary'] = 'x'*self.module.MAX_CAPTURE
        self.assert_refused(update_validation_draft=draft)

    def test_no_public_production_override(self):
        import inspect
        names = inspect.signature(self.module.prepare).parameters
        self.assertNotIn('verifier',names)
        self.assertNotIn('reconstruct',names)
        self.assertEqual(names['artifact_directory'].default,inspect.Parameter.empty)
        for name in ('original_validation_draft','update_validation_draft'):
            self.assertEqual(names[name].default,inspect.Parameter.empty)

if __name__ == '__main__':
    unittest.main()

"""Generated-image intake integrity: synthetic packets, temporary state only.

Reuses ReleaseV2's fixture methods by assignment (not by subclassing), so the
upstream/model/deployment boundary stays simulated exactly as in the v2 suite.
The controller replaces a captured original with the reviewed generated image
and drops ``image_note``; the intake identity is the packet projection without
``image``/``image_note``, so the ORIGINAL intake directory must keep verifying
and no second digest directory may appear.
"""
import copy,hashlib,json,unittest
from unittest.mock import patch
import test_release_v2 as base
COMMIT=base.COMMIT
from news_mvp.editorial import digest
from news_mvp import official
from news_mvp.publish import public_bundle,publish
from news_mvp.release_contract import media,receipt_media,verify_intake
from news_mvp.store import database
from cutover.check_release import check
SYNTHETIC=b'synthetic-jpeg'
class GeneratedIntegrity(unittest.TestCase):
    setUp=base.ReleaseV2.setUp
    source_fetch=base.ReleaseV2.source_fetch
    ready=base.ReleaseV2.ready
    workflow=base.ReleaseV2.workflow
    def generated(self):
        sha=hashlib.sha256(SYNTHETIC).hexdigest()
        packet=copy.deepcopy(self.packet);packet.pop('image_note',None)
        image={'url':f'https://uutistenlukija.fi/media/{sha}.jpg','local_path':f'media/{sha}.jpg','sha256':sha,
               'source_url':'https://uutistenlukija.fi/kuvituskuvat/','license_url':'https://uutistenlukija.fi/kuvituskuvat/',
               'license':'AI-generated illustration','credit':'AI synthetic','alt':'Kuvituskuva: synthetic library',
               'caption':'Kuvituskuva. Kuva on luotu tekoälyllä, ei valokuva tapahtumasta.','generated':True,
               'model':'synthetic','prompt_sha256':'a'*64,'prompt_version':'test','subject':'synthetic'}
        packet['image']=image
        draft=copy.deepcopy(self.draft);draft['image']=image
        (self.state/'media').mkdir(exist_ok=True);(self.state/'media'/f'{sha}.jpg').write_bytes(SYNTHETIC)
        return packet,draft
    def test_generated_official_media_still_runs_policy_provider_rights_gate(self):
        packet,draft=self.generated()
        media(packet,draft)
        for label,mutate in [('policy',lambda p: p['publication_basis'].__setitem__('policy_sha256','0'*64)),
                             ('provider',lambda p: p['sources'][0].__setitem__('publisher','Impostor Publisher')),
                             ('rights',lambda p: p.__setitem__('supporting_documents',[]))]:
            bad=copy.deepcopy(packet);mutate(bad)
            with self.subTest(gate=label,image=True),self.assertRaises(ValueError):media(bad,draft)
    def test_generated_binding_keeps_text_provenance_and_not_applicable_marker(self):
        packet,draft=self.generated()
        original=media(self.packet,self.draft);self.assertIsNone(original['image_sha256'])
        generated=media(packet,draft)
        self.assertEqual(generated['image_sha256'],packet['image']['sha256']);self.assertEqual(generated['text_only'],original['text_only'])
        self.assertIsNone(media(self.packet,self.draft)['image_sha256'])
        bare=copy.deepcopy(packet);bare.pop('publication_basis')
        marker=media(bare,draft)
        self.assertEqual(marker['image_sha256'],packet['image']['sha256']);self.assertEqual(marker['text_provenance'],'not-applicable')
    def test_generated_packet_uses_original_intake_and_rejects_source_rights_tamper(self):
        packet,draft=self.generated()
        verify_intake(packet,self.state)
        directory=self.state/'intake'/digest(self.packet);source=directory/'source.html';raw=source.read_bytes()
        source.write_bytes(raw+b'changed')
        with self.assertRaises(ValueError):verify_intake(packet,self.state)
        source.write_bytes(raw);verify_intake(packet,self.state)
        rights=directory/'rights.html';raw=rights.read_bytes()
        rights.write_bytes(raw+b'changed')
        with self.assertRaises(ValueError):verify_intake(packet,self.state)
        rights.write_bytes(raw);verify_intake(packet,self.state)
    def test_generated_receipt_bindings_schema2_downgrade_and_single_intake_directory(self):
        packet,draft=self.generated();job=self.ready(packet,draft)
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):
            site,receipt=public_bundle(store,job,self.state)
        binding=receipt_media(receipt);self.assertEqual(receipt['schema_version'],2)
        self.assertEqual(binding['image_sha256'],packet['image']['sha256']);self.assertEqual(binding['text_only'],media(self.packet,self.draft)['text_only'])
        check(site,receipt)
        bad=copy.deepcopy(receipt);bad.pop('text_only')
        with self.assertRaises(ValueError):check(site,bad)
        with self.assertRaises(ValueError):self.workflow(bad)
        self.assertTrue((self.state/'intake'/digest(self.packet)).is_dir())
        self.assertFalse((self.state/'intake'/digest(packet)).exists())
    def test_generated_packet_current_and_stored_nonimage_tamper_rejected(self):
        packet,draft=self.generated()
        verify_intake(packet,self.state)
        for field in ['text','title']:
            tampered=copy.deepcopy(packet);tampered['sources'][0][field]=tampered['sources'][0][field]+'tamper'
            with self.subTest(field=field):
                with self.assertRaises(ValueError):verify_intake(tampered,self.state)
        path=self.state/'intake'/digest(self.packet)/'packet.json';raw=path.read_bytes()
        stored=json.loads(raw);stored['sources'][0]['text']=stored['sources'][0]['text']+'tamper'
        path.write_text(json.dumps(stored))
        with self.assertRaises(ValueError):verify_intake(packet,self.state)
        path.write_bytes(raw);verify_intake(packet,self.state)
    def test_generated_additional_provider_receipt_identity_branch(self):
        # Receipt-branch isolation, not an end-to-end additional-provider parser test: this
        # keeps the existing synthetic Helsinki capture and only forces provider dispatch
        # through the ADDITIONAL_PROVIDERS branch, with the two parser entry points pinned to
        # the genuine values already parsed from those captured bytes. verify_intake's real
        # byte/hash/receipt checks therefore run unchanged.
        packet,draft=self.generated()
        directory=self.state/'intake'/digest(self.packet)
        raw=(directory/'source.html').read_bytes();rights=(directory/'rights.html').read_bytes()
        url=self.packet['sources'][0]['url']
        real_rights=official.rights_text(rights,'helsinki');real_fields=official.source_fields(raw,'helsinki',url)
        self.assertEqual(real_rights,self.packet['supporting_documents'][0]['text'])
        self.assertEqual(real_fields,{k:self.packet['sources'][0][k] for k in real_fields})
        self.assertEqual(json.loads((directory/'receipt.json').read_text())['image_status'],'explicit-text-only')
        with patch.object(official,'ADDITIONAL_PROVIDERS',official.ADDITIONAL_PROVIDERS+('helsinki',)),\
             patch.object(official,'rights_text',return_value=real_rights),\
             patch.object(official,'source_fields',return_value=real_fields):
            verify_intake(packet,self.state)
            path=directory/'receipt.json';receipt=path.read_bytes()
            changed=json.loads(receipt);changed['packet_sha256']=digest(packet)
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):verify_intake(packet,self.state)
            path.write_bytes(receipt)
            changed=json.loads(receipt);changed['image_status']='generated-image'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):verify_intake(packet,self.state)
            path.write_bytes(receipt);verify_intake(packet,self.state)
    def test_generated_publication_stops_on_captured_source_tamper(self):
        packet,draft=self.generated();job=self.ready(packet,draft)
        verify_intake(packet,self.state)
        source=self.state/'intake'/digest(self.packet)/'source.html';raw=source.read_bytes()
        source.write_bytes(raw+b'changed')
        try:
            with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):
                with self.assertRaises(ValueError) as caught:public_bundle(store,job,self.state)
            self.assertIn('Captured intake bytes changed',str(caught.exception))
            with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT),\
                 patch('news_mvp.publish.guard'),\
                 patch('news_mvp.publish.api',side_effect=AssertionError('external api reached')) as api,\
                 patch('news_mvp.publish.make_commit',side_effect=AssertionError('commit boundary reached')) as commit,\
                 patch('news_mvp.publish.matching_runs',side_effect=AssertionError('run lookup reached')) as runs:
                with self.assertRaises(ValueError) as caught:publish(store,job,self.state,str(self.cfg))
                self.assertIn('Captured intake bytes changed',str(caught.exception))
            api.assert_not_called();commit.assert_not_called();runs.assert_not_called()
        finally:
            source.write_bytes(raw)
        verify_intake(packet,self.state)
if __name__=='__main__':unittest.main()

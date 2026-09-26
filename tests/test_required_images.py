"""Missing/rejected imagery withholds publication while keeping writing work retryable."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from news_mvp import imagery
from news_mvp.controller import ingest, load_config, tick
from news_mvp.editorial import digest
from news_mvp.publish import publish, ensure_table
from news_mvp.store import database
from image_helpers import approved_pixel_review
import test_generated_integrity as generated
from test_imagery import _structured_png


class RequiredImages(unittest.TestCase):
    def setUp(self):
        self.case=generated.GeneratedIntegrity('test_generated_binding_keeps_text_provenance_and_not_applicable_marker')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.decision={'subject':self.case.draft['title'],'depictable_scene':'Illustrated library building and book shelves',
            'must_show':['library building','book shelves'],'must_avoid':['people'],
            'search_queries':['library building exterior','public library books','library reading room'],
            'category':self.case.draft['category']}

    def test_provider_failure_retries_saved_draft_without_review_or_publication(self):
        c=self.case
        c.config['illustrations']=True;c.cfg.write_text(json.dumps(c.config))
        identifier=ingest(load_config(c.cfg),c.packet,c.now)['id']
        with database(c.state) as store:ensure_table(store)
        calls=[]
        class Model:
            name='offline-image-failure'
            def call(self,role,packet,draft=None):
                calls.append(role)
                if role!='writer':raise AssertionError('No editorial review without image')
                return copy.deepcopy(c.draft)
        with patch.object(imagery,'classify_draft',return_value={}),patch.object(imagery,'build_image',return_value=None):
            for attempt in range(5):
                now=c.now+timedelta(minutes=16*attempt)
                result=tick(c.cfg,Model(),now)
                self.assertEqual(result['status'],'image_pending')
                with database(c.state) as store:
                    row=store.get(identifier)
                    self.assertEqual(row['status'],'ready');self.assertEqual(row['attempts'],0)
                    self.assertEqual(json.loads(row['draft']),c.draft)
                    self.assertGreaterEqual(row['next_attempt'],now.timestamp()+900)
                    self.assertIsNone(row['review'])
                    self.assertEqual(store.db.execute('SELECT count(*) FROM publications').fetchone()[0],0)
        self.assertEqual(calls,['writer'])
        self.assertFalse((c.root/'private').exists())

    def test_direct_publisher_refuses_an_approved_text_only_job(self):
        c=self.case;job=c.ready(c.packet,c.draft)
        with database(c.state) as store,patch('news_mvp.publish.guard'),patch('news_mvp.publish.public_bundle') as bundle:
            result=publish(store,job,c.state,c.cfg)
            self.assertEqual(result['status'],'image_pending');self.assertTrue(result['retryable'])
            bundle.assert_not_called()
            self.assertEqual(store.db.execute('SELECT count(*) FROM publications').fetchone()[0],0)

    def test_actual_deployment_entrypoint_refuses_text_only_even_with_valid_legacy_provenance(self):
        from news_mvp.release_contract import media
        c=self.case;job=c.ready(c.packet,c.draft)
        receipt={'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi',
            'ga4_id':'G-35XERS8V6J','source_commit':'a'*40,'job_id':job['id'],'schema_version':2,
            'packet':c.packet,'draft':c.draft,'review':json.loads(job['review']),
            'packet_sha256':digest(c.packet),'draft_sha256':digest(c.draft),**media(c.packet,c.draft)}
        path=c.root/'text-only-release.json';path.write_text(json.dumps(receipt))
        script=Path(__file__).resolve().parents[1]/'cutover/check_release.py'
        result=subprocess.run([sys.executable,'-B',str(script),str(c.root),str(path)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Text-only publication is prohibited',result.stderr)

    def test_editorial_image_only_refusal_keeps_candidate_history_and_retries(self):
        c=self.case;packet,draft=c.generated()
        identifier=ingest(load_config(c.cfg),packet,c.now)['id']
        class Model:
            name='offline-image-only-review'
            def call(self,role,packet,value=None):
                if role=='writer':return copy.deepcopy(draft)
                return {'approved':False,'image_retryable':True,'draft_sha256':digest(value),'reasons':['Image caption claims a specific event']}
        result=tick(c.cfg,Model(),c.now)
        self.assertEqual(result['status'],'image_pending')
        with database(c.state) as store:
            row=store.get(identifier);self.assertEqual(row['status'],'ready');self.assertEqual(row['attempts'],0)
            self.assertIsNone(json.loads(row['packet'])['image']);self.assertIsNone(json.loads(row['draft'])['image'])
            self.assertEqual(json.loads(row['draft'])['paragraphs'],draft['paragraphs'])
        history=list((c.state/'image-rejections'/identifier).glob('*.json'));self.assertEqual(len(history),1)
        saved=json.loads(history[0].read_text());self.assertEqual(saved['draft']['image']['sha256'],draft['image']['sha256'])
        self.assertEqual(saved['review']['draft_sha256'],digest(saved['draft']))

    def test_exact_pixels_and_final_article_are_both_bound(self):
        c=self.case;packet,draft=c.generated();image=packet['image']
        good=imagery.reviewed_image(image,draft,c.state)
        imagery.validate_pixel_review(good,draft)
        changed=copy.deepcopy(draft);changed['paragraphs'][0]['text']+=' Changed fact.'
        with self.assertRaisesRegex(ValueError,'final article'):imagery.validate_pixel_review(good,changed)
        changed=copy.deepcopy(good);changed['sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'exact image'):imagery.validate_pixel_review(changed,draft)
        changed=copy.deepcopy(good);changed['pixel_review']['no_people']=False
        with self.assertRaisesRegex(ValueError,'contain people'):imagery.validate_pixel_review(changed,draft)
        (c.state/image['local_path']).write_bytes(b'changed pixels')
        with self.assertRaisesRegex(imagery.GenerationError,'bytes changed'):
            imagery.reviewed_image(image,draft,c.state)

    def test_default_generator_cannot_accept_a_failed_independent_pixel_review(self):
        c=self.case
        rejected=lambda raw,draft,generated=False:{**approved_pixel_review(raw,draft,generated),'approved':False}
        with patch.object(imagery,'fetch_pexels',return_value=None),patch.object(imagery,'fetch_unsplash',return_value=None), \
             patch.object(imagery,'generate',return_value=(_structured_png(),'safe prompt','test-model')), \
             patch.object(imagery,'describe',return_value=None),patch.object(imagery,'review_pixels',side_effect=rejected):
            self.assertIsNone(imagery.build_image(c.draft,c.state,attempts=1,decision=self.decision,allow_open_sources=False))
        self.assertFalse((c.state/'media').exists())

    def test_stock_refusal_continues_to_generated_fallback(self):
        c=self.case;packet,draft=c.generated()
        reviews=[]
        def review(raw,draft,generated=False):
            reviews.append(generated)
            return {**approved_pixel_review(raw,draft,generated),'approved':generated}
        with patch.object(imagery,'fetch_pexels',return_value=packet['image']),patch.object(imagery,'fetch_unsplash',return_value=None), \
             patch.object(imagery,'generate',return_value=(_structured_png(),'safe prompt','test-model')), \
             patch.object(imagery,'describe',return_value=None),patch.object(imagery,'review_pixels',side_effect=review):
            result=imagery.build_image(draft,c.state,attempts=1,decision=self.decision,allow_open_sources=False)
        self.assertTrue(result['generated']);self.assertEqual(reviews,[False,True])
        imagery.validate_pixel_review(result,draft)
        self.assertEqual(result['alt'],'AI-generoitu kuva: Kirjoja kirjaston hyllyillä.')

    def test_sensitive_named_person_is_not_copied_into_safe_scene_prompt(self):
        prompt=imagery._prompt_for('Named politician facing a violent crime investigation',
            'Kotimaa','An illustrated courthouse doorway and legal files',
            ['courthouse doorway','legal files'],['people','text'])
        self.assertNotIn('Named politician',prompt)
        self.assertIn('No people, faces, human likenesses',prompt)
        self.assertIn('never documentary photography',prompt)
        self.assertIn('courthouse doorway',prompt)
        self.assertNotIn('People, if shown',prompt)

    def test_image_used_by_another_article_is_refused_before_review_and_falls_back(self):
        c=self.case;packet,draft=c.generated()
        previous=copy.deepcopy(draft);previous['title']='Different already stored article'
        c.ready(packet,previous)
        with self.assertRaisesRegex(imagery.GenerationError,'different article'):
            imagery.reviewed_image(packet['image'],draft,c.state)
        with patch.object(imagery,'fetch_pexels',return_value=packet['image']),patch.object(imagery,'fetch_unsplash',return_value=None), \
             patch.object(imagery,'generate',return_value=(_structured_png(),'safe prompt','test-model')), \
             patch.object(imagery,'review_pixels',side_effect=approved_pixel_review) as review:
            result=imagery.build_image(draft,c.state,attempts=1,decision=self.decision,allow_open_sources=False)
        self.assertTrue(result['generated'])
        self.assertEqual(review.call_count,1)
        self.assertTrue(review.call_args.kwargs['generated'])
        self.assertNotEqual(result['sha256'],packet['image']['sha256'])

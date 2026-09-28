"""The public image path searches every ranked concept before exact fallback."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import imagery
from news_mvp.editorial import digest
from PIL import Image


DRAFT = {'title':'Kuopio tarkentaa esiopetuksen oppilaaksiottoa',
    'summary':'Kuopio tarkentaa esiopetuksen oppilaaksioton käytäntöjä.',
    'category':'Kotimaa','paragraphs':[
        {'text':'Esiopetuksen oppilaaksiotto koskee Kuopion päiväkoteja.',
         'source_ids':['A']},
        {'text':'Kaupunki valmistelee perheille uudet ohjeet.',
         'source_ids':['A']}]}
DECISION = {'version':'article-first-v1','category':'Kotimaa','concepts':[
    {'rank':1,'safe_to_generate':False,'subject':'Kuopion päiväkoteja',
     'depictable_scene':'Kuopion oikean päiväkodin sisäänkäynti.',
     'must_show':['daycare building'],'must_avoid':['unrelated phone'],
     'search_queries':['Kuopion päiväkoti rakennus','Kuopio daycare building',
                       'kindergarten building Kuopio']},
    {'rank':2,'safe_to_generate':True,'subject':'esiopetuksen oppilaaksiotto',
     'depictable_scene':'Esiopetuksen kirjoja ja värikyniä tyhjällä luokkahuoneen pöydällä.',
     'must_show':['preschool books'],'must_avoid':['faces'],
     'search_queries':['esiopetuksen kirjat pöydällä','preschool books classroom',
                       'preschool learning materials']}]}


class ArticleFirstPipeline(unittest.TestCase):
    def test_street_name_alone_cannot_prove_an_exact_numbered_building(self):
        concept = {'subject':'Turunlinnantie 12',
            'depictable_scene':'Turunlinnantie 12 building exterior',
            'must_show':['building exterior'],'must_avoid':['unrelated building'],
            'search_queries':['Turunlinnantie 12 Helsinki','Turunlinnantie building Helsinki',
                              'Turunlinnantie office exterior'],'category':'Kotimaa'}
        draft = {**DRAFT,'title':'Turunlinnantie 12 building',
                 'summary':'The building at Turunlinnantie 12.'}
        raster = io.BytesIO()
        Image.new('RGB',(800,600),(120,110,100)).save(raster,format='JPEG')
        vision = {'approved':True,'no_people':True,'fit_score':9,
            'must_show_visible':[True],
            'description':'A building on a winter street.',
            'reason':'A street-side building exterior.',
            'alt_fi':'Rakennuksen julkisivu ja luminen katu näkyvät talvisessa näkymässä.'}
        with mock.patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}), \
                mock.patch('news_mvp.image_providers.google_vision',return_value=vision):
            review=imagery.review_pixels(raster.getvalue(),draft,concept=concept)
        self.assertFalse(review['approved'])
        self.assertEqual(review['fit_score'],7)
        self.assertFalse(imagery._exact_address_supported(concept,
            {'title':'Turunlinnantie - panoramio.jpg'}))
        self.assertTrue(imagery._exact_address_supported(concept,
            {'title':'Turunlinnantie 12 Helsinki.jpg'}))

    def test_high_scoring_real_classroom_is_refused_when_independent_ocr_finds_text(self):
        concept = {**imagery.concept_decision(DECISION,DECISION['concepts'][1]),
            'must_avoid':['readable text']}
        raster = io.BytesIO()
        Image.new('RGB',(800,600),(120,110,100)).save(raster,format='JPEG')
        primary = {'approved':True,'no_people':True,'fit_score':9,
            'must_show_visible':[True],
            'description':'An empty classroom with tables and books.',
            'reason':'Concrete preschool setting.',
            'alt_fi':'Tyhjässä luokkahuoneessa on matalia pöytiä, tuoleja ja kirjoja.'}
        audit = {'readable_text_present':True,'examples':['Math word problems']}
        with mock.patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}), \
                mock.patch('news_mvp.image_providers.google_vision',side_effect=[primary,audit]) as vision:
            review=imagery.review_pixels(raster.getvalue(),DRAFT,concept=concept)
        self.assertEqual(vision.call_count,2)
        self.assertFalse(review['approved'])
        self.assertEqual(review['fit_score'],7)
        self.assertEqual(review['text_audit'],audit)

    def test_recognizable_child_face_breaks_a_no_faces_concept(self):
        concept = {**imagery.concept_decision(DECISION,DECISION['concepts'][1]),
            'must_avoid':['recognizable faces']}
        raster = io.BytesIO()
        Image.new('RGB',(800,600),(120,110,100)).save(raster,format='JPEG')
        primary = {'approved':True,'no_people':False,'fit_score':9,
            'must_show_visible':[True],
            'description':'An adult and child at a low classroom table.',
            'reason':'Concrete preschool activity.',
            'alt_fi':'Aikuinen ja lapsi istuvat matalan pöydän ääressä värikynien kanssa.'}
        audit = {'recognizable_faces_present':True,'children_faces_present':True,
                 'visible_people_count':2,'reason':'Both faces are visible.'}
        with mock.patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}), \
                mock.patch('news_mvp.image_providers.google_vision',side_effect=[primary,audit]) as vision:
            review=imagery.review_pixels(raster.getvalue(),DRAFT,concept=concept)
        self.assertEqual(vision.call_count,2)
        self.assertFalse(review['approved'])
        self.assertEqual(review['fit_score'],7)
        self.assertEqual(review['face_audit'],audit)

    def test_exact_fallback_reaches_generator_with_multilingual_queries(self):
        decision = {'subject':'käyttövälineiden vaihtoa',
            'depictable_scene':'Steriilejä tarvikkeita suljetulla työtasolla.',
            'must_show':['sealed sterile syringes','sharps container'],
            'must_avoid':['readable text'],
            'search_queries':['needle exchange supplies','sterile syringe packets',
                              'sharps disposal container'],'category':'Kotimaa'}
        draft = {**DRAFT,'title':'Käyttövälineiden vaihtoa palvelussa',
                 'summary':'Steriilejä tarvikkeita on tarjolla.'}
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery,'generate',
                    side_effect=imagery.GenerationError('generator reached')) as generate:
            self.assertIsNone(imagery._build_image(draft,state,decision=decision,
                attempts=1,allow_open_sources=False,require_pixel_review=False,
                skip_stock=True,exact_concept=True))
            generate.assert_called_once()

    def test_two_or_three_ranked_concepts_and_safe_fallback_required(self):
        self.assertEqual(imagery.validate_image_decision(DECISION,DRAFT),DECISION)
        for change in (
            {**DECISION,'concepts':DECISION['concepts'][:1]},
            {**DECISION,'concepts':DECISION['concepts']+[DECISION['concepts'][0],DECISION['concepts'][1]]},
            {**DECISION,'concepts':[DECISION['concepts'][0],
                {**DECISION['concepts'][1],'rank':3}]},
            {**DECISION,'concepts':[{**x,'safe_to_generate':False} for x in DECISION['concepts']]},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    imagery.validate_image_decision(change,DRAFT,require_concepts=True)
        with self.assertRaises(ValueError):
            imagery.validate_image_decision(imagery.concept_decision(DECISION,DECISION['concepts'][0]),
                                            DRAFT,require_concepts=True)
        unsafe = {**DECISION, 'concepts': [DECISION['concepts'][0],
            {**DECISION['concepts'][1], 'depictable_scene':
                'Kaksi lasta askartelee pöydän ääressä.', 'safe_to_generate': True}]}
        with self.assertRaisesRegex(ValueError, 'cannot depict people'):
            imagery.validate_image_decision(unsafe,DRAFT,require_concepts=True)

    def _run(self, scores, generated=None):
        with tempfile.TemporaryDirectory() as state:
            path=Path(state)/'media';path.mkdir()
            calls=[]
            for rank in (1,2):
                (path/f'candidate{rank}.jpg').write_bytes(f'pixel-{rank}'.encode())
            def provider(draft,state_dir,decision,accept,**kwargs):
                rank=next(x['rank'] for x in DECISION['concepts']
                          if x['subject']==decision['subject'])
                calls.append(('search',rank))
                raw=f'pixel-{rank}'.encode();sha=hashlib.sha256(raw).hexdigest()
                return accept({'generated':False,'url':'https://images.pexels.com/photo.jpg',
                    'source_url':f'https://www.pexels.com/photo/{rank}/',
                    'license':'Pexels License','sha256':sha,
                    'local_path':f'media/candidate{rank}.jpg',
                    'relevance_check':{'accepted':True,'method':'metadata',
                        'evidence':'preschool','matched':['preschool'],'reason':'fixture'},
                    'classifier_output':decision})
            def review(raw,draft,generated=False,concept=None,**kwargs):
                rank=next(x['rank'] for x in DECISION['concepts']
                          if x['subject']==concept['subject'])
                calls.append(('review',rank))
                return {'approved':True,'fit_score':scores[rank-1],
                    'must_show_visible':[True] * len(concept['must_show']),
                    'image_sha256':hashlib.sha256(raw).hexdigest(),
                    'article_text_sha256':imagery._article_text_sha(draft),
                    'concept_sha256':digest(concept),
                    'alt_fi':'Kirjoja ja värikyniä pöydällä.',
                    'description':'Books and pencils on a classroom table.',
                    'reason':'Visible article subject.','no_people':True}
            def generate(*args,**kwargs):
                concept=args[5];calls.append(('generate',concept['subject']))
                raw=b'generated-pixels';score=9
                return {'generated':True,'sha256':hashlib.sha256(raw).hexdigest(),
                    'pixel_review':{'approved':True,'fit_score':score,
                        'must_show_visible':[True] * len(concept['must_show']),
                        'image_sha256':hashlib.sha256(raw).hexdigest(),
                        'article_text_sha256':imagery._article_text_sha(DRAFT),
                        'concept_sha256':digest(concept),'no_people':True},
                    'classifier_output':concept}
            with mock.patch.object(imagery,'fetch_pexels',side_effect=provider), \
                 mock.patch.object(imagery,'fetch_unsplash',return_value=None), \
                 mock.patch.object(imagery,'review_pixels',side_effect=review), \
                 mock.patch.object(imagery,'_build_image',side_effect=generate), \
                 mock.patch('news_mvp.release_contract.stock_binding',side_effect=lambda x:x), \
                 mock.patch('news_mvp.image_providers.candidate_event'):
                image=imagery._build_image_article_first(DRAFT,state,'Kotimaa','fixture',1,
                    DECISION,False,True,None)
            return image,calls

    def test_exact_pixel_score_eight_gate_and_all_concepts_searched(self):
        image,calls=self._run((7,9))
        self.assertFalse(image['generated'])
        self.assertEqual(image['selection_evidence']['selected']['concept_rank'],2)
        self.assertEqual(image['selection_evidence']['selected']['fit_score'],9)
        self.assertEqual([x for x in calls if x[0]=='search'],[('search',1),('search',2)])
        self.assertFalse(any(x[0]=='generate' for x in calls))
        scored=[item['candidates'][0]['fit_score'] for item in image['selection_evidence']['searches']
                if item['candidates']]
        self.assertEqual(scored,[7,9])
        imagery.validate_selection_evidence(image,DRAFT)
        with self.assertRaises(ValueError):
            imagery.validate_selection_evidence({**image,'selection_evidence':{
                **image['selection_evidence'],'selected':{
                    **image['selection_evidence']['selected'],'fit_score':7}}},DRAFT)

    def test_generation_waits_for_all_real_candidates_and_matches_best_safe_concept(self):
        image,calls=self._run((6,7))
        self.assertTrue(image['generated'])
        self.assertEqual(image['selection_evidence']['selected']['concept_rank'],2)
        self.assertEqual([x for x in calls if x[0]=='search'],[('search',1),('search',2)])
        self.assertEqual(calls[-1],('generate',DECISION['concepts'][1]['subject']))
        imagery.validate_selection_evidence(image,DRAFT)


if __name__=='__main__':
    unittest.main()

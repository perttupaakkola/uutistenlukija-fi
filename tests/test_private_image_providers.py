import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from news_mvp import imagery, image_providers as providers
from test_imagery import _structured_png


class PrivateImageProviders(unittest.TestCase):
    def test_failed_attempt_records_bounded_transport_fields_without_private_error(self):
        with tempfile.TemporaryDirectory() as state:
            with self.assertRaises(RuntimeError):
                with providers.image_attempt({'title':'Article'},state):
                    providers.request_event('api.kie.ai',429,'HTTPError')
                    raise RuntimeError('private response must not be persisted')
            receipt=json.loads(next(Path(state).rglob('*.json')).read_text())
            self.assertEqual(receipt['outcome'],'image_pending')
            self.assertEqual(receipt['requests'],[{'host':'api.kie.ai','http_status':429,'error_type':'HTTPError'}])
            self.assertIsNone(providers.REQUEST_EVENTS.get())
            self.assertNotIn('private response',json.dumps(receipt))

    def test_google_generation_cache_survives_review_outage_and_rejection_refreshes(self):
        response={'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'image/png',
                  'data':base64.b64encode(_structured_png()).decode()}}]}}]}
        with tempfile.TemporaryDirectory() as state,patch.object(imagery,'_credential_value',return_value='synthetic'), \
                patch.object(providers,'_json',return_value=response) as api:
            first=providers.generate_google('subject','safe scene',state)
            self.assertEqual(first,providers.generate_google('subject','safe scene',state))
            self.assertEqual(api.call_count,1)
            providers.reject_google('subject','safe scene',state)
            providers.generate_google('subject','safe scene',state)
            self.assertEqual(api.call_count,2)
            providers.reject_google('subject','safe scene',state)
            api.return_value={'candidates':[]}
            with self.assertRaises(imagery.GenerationError):providers.generate_google('subject','safe scene',state)

    def test_pending_task_is_resumed_without_second_submission_and_refusal_gets_new_task(self):
        with tempfile.TemporaryDirectory() as state,patch.object(imagery,'provider_key',return_value='synthetic-key'), \
                patch.object(imagery,'_get_external_bytes',return_value=b'exact-image'):
            calls=[]
            def request(url,host,headers,body=None,**kwargs):
                calls.append((url,body))
                if body:return {'code':200,'data':{'taskId':'task-'+str(sum(b is not None for _,b in calls))}}
                task=url.split('taskId=')[1]
                return {'code':200,'data':{'taskId':task,'model':providers.KIE_MODEL,'state':'success',
                    'resultJson':json.dumps({'resultUrls':['https://images.example.com/one.png']})}}
            with patch.object(providers,'_json',side_effect=request):
                with self.assertRaisesRegex(imagery.GenerationError,'pending'):
                    providers.generate_kie('article','safe scene',state,timeout=0)
                self.assertEqual(providers.generate_kie('article','safe scene',state)[0],b'exact-image')
                self.assertEqual(sum(body is not None for _,body in calls),1)
                providers.reject_kie('article','safe scene',state)
                providers.generate_kie('article','safe scene',state)
                self.assertEqual(sum(body is not None for _,body in calls),2)
                self.assertNotIn('synthetic-key',''.join(p.read_text() for p in Path(state).rglob('*.json')))

    def test_wrong_task_identity_or_failed_task_never_returns_pixels(self):
        for value in ({'taskId':'other','model':providers.KIE_MODEL,'state':'success'},
                      {'taskId':'one','model':providers.KIE_MODEL,'state':'fail'}):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as state, \
                    patch.object(imagery,'provider_key',return_value='synthetic-key'), \
                    patch.object(providers,'_json',side_effect=[{'code':200,'data':{'taskId':'one'}},{'code':200,'data':value}]), \
                    patch.object(imagery,'_get_external_bytes') as download:
                with self.assertRaises(imagery.GenerationError):providers.generate_kie('article','safe scene',state)
                download.assert_not_called()

    def test_configured_google_review_binds_exact_pixels_and_full_article(self):
        raw=_structured_png();draft={'title':'Library','summary':'New shelves','category':'Kotimaa','paragraphs':[{'text':'Books in a library.'}]}
        with patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}),patch.object(providers,'google_vision',
                return_value={'approved':True,'no_people':True,'description':'Books and shelves','reason':'Illustrates the library','alt_fi':'Kirjoja kirjaston hyllyillä.'}) as vision:
            review=imagery.review_pixels(raw,draft,generated=True)
            self.assertEqual(review['image_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(review['model'],'google:'+providers.VISION_MODEL)
            self.assertEqual(review['alt_fi'],'Kirjoja kirjaston hyllyillä.')
            self.assertIn('Books in a library.',vision.call_args.args[1])
            self.assertIn('no faces/likenesses',vision.call_args.args[1])
        with patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}),patch.object(providers,'google_vision',return_value={'approved':True}):
            with self.assertRaises(imagery.GenerationError):imagery.review_pixels(raw,draft,generated=True)

    def test_credentialed_calls_use_pinned_no_redirect_transport_and_safe_errors(self):
        import urllib.error
        with patch.object(imagery,'_open',side_effect=urllib.error.HTTPError('private',401,'secret body',{},None)) as opener:
            with self.assertRaises(imagery.GenerationError) as raised:
                providers._json('https://api.kie.ai/api/v1/jobs/createTask','api.kie.ai',{'Authorization':'Bearer synthetic-key'},{})
            self.assertNotIn('synthetic-key',str(raised.exception));self.assertNotIn('secret body',str(raised.exception))
            self.assertTrue(opener.call_args.kwargs['credentialed'])

    def test_stock_review_supplies_complete_finnish_alt_without_truncation(self):
        raw=_structured_png();draft={'title':'Library','summary':'Shelves','category':'Kotimaa','paragraphs':[{'text':'Library books.'}]}
        response={'approved':True,'no_people':True,'description':'A long provider description',
                  'reason':'Library books match the article','alt_fi':'Kirjoja kirjaston hyllyillä.'}
        with patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}),patch.object(providers,'google_vision',return_value=response):
            review=imagery.review_pixels(raw,draft,generated=False)
        self.assertEqual(imagery._stock_alt(review),'Arkistokuva: Kirjoja kirjaston hyllyillä.')
        self.assertEqual(review['image_sha256'],hashlib.sha256(raw).hexdigest())

    def test_missing_truncated_or_overlong_stock_alt_fails_closed(self):
        for value in (None,'Description cut mid word','x'*201+'.'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'complete'):
                imagery._stock_alt({'alt_fi':value})

    def test_pixel_reviewer_receives_the_entire_final_article(self):
        draft={'title':'Long report','summary':'Details','category':'Kotimaa',
               'paragraphs':[{'text':'Context. '*1500},{'text':'Final paragraph changes the image interpretation.'}]}
        response={'approved':False,'no_people':True,'description':'Unrelated scene','reason':'Final paragraph mismatch'}
        with patch.dict('os.environ',{'UUTIS_VISION_PROVIDER':'google'}),patch.object(providers,'google_vision',return_value=response) as vision:
            review=imagery.review_pixels(_structured_png(),draft,generated=True)
        self.assertIn('Final paragraph changes the image interpretation.',vision.call_args.args[1])
        self.assertFalse(review['approved'])


if __name__=='__main__':unittest.main()

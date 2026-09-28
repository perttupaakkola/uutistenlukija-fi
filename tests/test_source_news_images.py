"""Image-specific Helsinki grants must never become unrelated stock/text permission."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from news_mvp import imagery, source_news_images as news, site
from news_mvp.editorial import digest
from news_mvp.release_contract import stock_binding, _check_rendered_stock, media
from test_stock_imagery import _checkerboard_bytes

URL='https://www.hel.fi/fi/uutiset/kentta-uudistuu'
IMAGE='https://stplattaprod.blob.core.windows.net/etusivu64e62prod/styles/1_5_863w_576h/azure/trees.jpg.webp?itok=example'
TITLE='Kentän uusille istutuksille valmistui suoja-aita'
HTML=(f'<link rel="canonical" href="{URL}"><main><h1>{TITLE}</h1>'
    f'<figure class="image main-image"><picture><img src="{IMAGE}" width="863" height="576"></picture>'
    '<figcaption>Puita kentän uudistuksessa. Kuva: <span>Fixture Photographer</span></figcaption></figure></main>').encode()
RIGHTS=('<p>'+news.GRANT+'</p>').encode()
DRAFT=dict(title=TITLE,summary='Kentän uudistuksen yhteydessä istutettiin puita.',category='Kotimaa',
    paragraphs=[{'text':'Uusien taimien ympärille rakennettiin aita.','source_ids':['A']}])
PACKET={'publication_basis':{'provider':'helsinki'},'sources':[{'id':'A','url':URL,'title':TITLE}]}
DECISION=dict(subject=TITLE,category='Kotimaa',depictable_scene='Puita ja aita kentän vieressä.',
    must_show=['trees'],must_avoid=['violence'],search_queries=['trees field','trees fence','trees planting'])


class SourceNewsImages(unittest.TestCase):
    def record(self, state):
        raw=_checkerboard_bytes();c=news.candidate(URL,HTML,RIGHTS)
        c['news_evidence']['source_image_sha256']=news.sha(raw)
        image_sha,path,pixels=imagery._persist_verified_image(raw,state)
        record=imagery._open_source_record('helsinki',c,TITLE,state,pixels,image_sha,path,
            'Trees beside a fence.',DECISION,imagery.relevance_check('Trees beside a fence.',DECISION,'vision'),
            '2026-09-26T20:00:00Z')
        return self.reviewed(record),raw

    def reviewed(self, record):
        review={'approved':True,'alt_fi':'Puita kasvaa aidan vieressä.','description':'Trees beside a fence.',
            'reason':'New trees are explicitly discussed in this field-renovation article.',
            'no_people':True,'image_sha256':record['sha256'],
            'article_text_sha256':hashlib.sha256(json.dumps(DRAFT,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'model':'fixture-review','reviewed_at':'2026-09-26T20:01:00+00:00'}
        return {**record,'pixel_review':review,'alt':imagery._stock_alt(review)}

    def test_explicit_image_grant_exact_credit_and_rendered_binding(self):
        with tempfile.TemporaryDirectory() as state:record,_=self.record(state)
        stock_binding(record);news.validate_relation(record['stock_provenance'],PACKET,DRAFT)
        html=site.image_rights_html(record)
        self.assertIn('Helsingin kaupunki</a> / <a href="'+URL+'">Fixture Photographer</a>',html)
        self.assertIn(news.LICENSE,html);self.assertNotIn('CC BY',html)
        article='<article>'+site.article_hero_figure(record,f'/mvp-assets/{record["sha256"]}.jpg')+html+'</article>'
        _check_rendered_stock(article,record)
        with self.assertRaises(ValueError):_check_rendered_stock(article.replace('Fixture Photographer','Other'),record)

    def test_text_cc_licence_is_not_an_image_grant(self):
        with self.assertRaises(ValueError):news.candidate(URL,HTML,b'<p>Text may be used under CC BY 4.0.</p>')

    def test_wrong_source_missing_credit_multiple_main_photos_and_foreign_pixels_refuse(self):
        variants=[HTML.replace(URL.encode(),b'https://www.hel.fi/fi/uutiset/other'),
            HTML.replace(b'Kuva:',b'Author:'),HTML.replace(b'</main>',HTML[HTML.index(b'<figure'):HTML.index(b'</main>')]+b'</main>'),
            HTML.replace(b'stplattaprod.blob.core.windows.net',b'foreign.invalid'),
            HTML.replace(b'Fixture Photographer',b'Fixture Photographer - all rights reserved')]
        for raw in variants:
            with self.subTest(raw=raw[-70:]),self.assertRaises(ValueError):news.candidate(URL,raw,RIGHTS)

    def test_rehashed_credit_grant_image_and_source_substitutions_refuse(self):
        with tempfile.TemporaryDirectory() as state:record,_=self.record(state)
        for key,value in [('photographer','Another'),('photo_url',URL+'-other'),('image_url',IMAGE+'x'),('license','CC BY 4.0')]:
            r=deepcopy(record);r['stock_provenance'][key]=value;r['stock_provenance_sha256']=digest(r['stock_provenance'])
            with self.subTest(key=key),self.assertRaises(ValueError):stock_binding(r)
        r=deepcopy(record);r['stock_provenance']['news_evidence']['rights_grant']='Text rights only'
        r['stock_provenance_sha256']=digest(r['stock_provenance'])
        with self.assertRaises(ValueError):stock_binding(r)

    def test_related_news_scope_cannot_be_transferred_to_another_packet(self):
        with tempfile.TemporaryDirectory() as state:record,_=self.record(state)
        for packet in ({**PACKET,'sources':[{'id':'A','url':URL+'-other'}]},
                       {**PACKET,'publication_basis':{'provider':'vantaa'}},
                       {**PACKET,'sources':[{'id':'B','url':URL}]}):
            with self.assertRaises(ValueError):news.validate_relation(record['stock_provenance'],packet,DRAFT)
        # Exercise the actual release boundary, before any unrelated text-policy checks.
        with mock.patch('news_mvp.release_contract.validate_draft'),self.assertRaisesRegex(ValueError,'another article'):
            media({**PACKET,'fixture':False,'sources':[{'id':'A','url':URL+'-other'}]}, {**DRAFT,'image':record})

    def test_real_fetch_entrypoint_captures_grant_source_pixels_and_requires_review(self):
        with tempfile.TemporaryDirectory() as state, mock.patch.object(news,'_read_html',side_effect=lambda u:RIGHTS if u==news.RIGHTS_URL else HTML), \
                mock.patch.object(imagery,'_get_bytes',return_value=_checkerboard_bytes()), \
                mock.patch.object(imagery,'describe',return_value='Trees beside a fence.'):
            self.assertIsNone(news.fetch(PACKET,DRAFT,state,DECISION,lambda r:r))
            result=news.fetch(PACKET,DRAFT,state,DECISION,self.reviewed)
            self.assertIsNotNone(result);stock_binding(result)
            evidence=result['stock_provenance']['news_evidence'];folder=Path(state)/'source-news-rights'
            self.assertEqual((folder/(evidence['rights_html_sha256']+'.html')).read_bytes(),RIGHTS)
            self.assertEqual((folder/(evidence['source_html_sha256']+'.html')).read_bytes(),HTML)
            self.assertEqual((folder/(evidence['source_image_sha256']+'.image')).read_bytes(),_checkerboard_bytes())

    def test_ordinary_tree_prioritizes_explicit_source_grant_and_exact_review(self):
        with tempfile.TemporaryDirectory() as state:
            record,_=self.record(state);review=record['pixel_review']
            with mock.patch.object(news,'_read_html',side_effect=lambda u:RIGHTS if u==news.RIGHTS_URL else HTML), \
                    mock.patch.object(imagery,'_get_bytes',return_value=_checkerboard_bytes()), \
                    mock.patch.object(imagery,'describe',return_value='Trees beside a fence.'), \
                    mock.patch.object(imagery,'review_pixels',return_value=review) as inspected, \
                    mock.patch.object(imagery,'fetch_pexels') as stock, mock.patch.object(imagery,'generate') as generated:
                result=imagery.build_image(DRAFT,state,decision=DECISION,packet=PACKET)
                self.assertEqual(result['stock_provenance']['provider'],'helsinki')
                inspected.assert_called_once();stock.assert_not_called();generated.assert_not_called()
                self.assertEqual(inspected.call_args.kwargs['source_context']['image_sha256'],result['sha256'])

    def test_bad_source_grant_continues_to_regular_licensed_provider(self):
        with tempfile.TemporaryDirectory() as state:
            record,_=self.record(state)
            with mock.patch.object(news,'_read_html',return_value=b'<p>Only texts are reusable</p>'), \
                    mock.patch.object(imagery,'fetch_wikimedia',return_value=None) as local, \
                    mock.patch.object(imagery,'fetch_pexels',return_value=record) as stock, \
                    mock.patch.object(imagery,'review_pixels',return_value=record['pixel_review']):
                self.assertIsNotNone(imagery.build_image(DRAFT,state,decision=DECISION,packet=PACKET))
                local.assert_called_once()
                stock.assert_called_once()

    def test_source_pixel_context_refuses_changed_exact_bytes(self):
        with tempfile.TemporaryDirectory() as state:record,raw=self.record(state)
        context=imagery._record_pixel_context(record);context['image_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'identity'):
            imagery.review_pixels(raw,DRAFT,source_context=context)


if __name__=='__main__':unittest.main()

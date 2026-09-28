"""Owner-facing image presentation, fallback style and bounded intake mix."""
import unittest
from unittest.mock import patch

from news_mvp import imagery, site
from news_mvp.discovery import discover_mixed


class EditorialFrontpageCorrection(unittest.TestCase):
    def test_stock_credit_lives_only_in_article_rights(self):
        image = {'alt':'Arkistokuva: Oulun rakennus.','caption':'Arkistokuva artikkelin aiheesta.',
                 'credit':'Photo by Estormiz on Wikimedia Commons','license':'CC0',
                 'license_url':'https://creativecommons.org/publicdomain/zero/1.0/',
                 'source_url':'https://commons.wikimedia.org/wiki/File:Oulu.jpg',
                 'stock_provenance':{'provider':'wikimedia','photographer':'Estormiz',
                     'photographer_url':'https://commons.wikimedia.org/wiki/User:Estormiz',
                     'photo_url':'https://commons.wikimedia.org/wiki/File:Oulu.jpg',
                     'attribution':{'title':'Oulu.jpg','changes':'JPEG-muoto.'}}}
        surfaces = [site.homepage_image_figure(image,'/image.jpg',False),
                    site.listing_image_slot(image,'/image.jpg','portal-teaser__thumb','/story/','Story'),
                    site.article_hero_figure(image,'/image.jpg')]
        for markup in surfaces:
            self.assertNotIn('portal-lead__credit',markup)
            self.assertNotIn('portal-lead__image-label',markup)
            self.assertNotIn('>Arkistokuva<',markup)
        self.assertIn('href="/story/"',surfaces[1])
        rights = site.image_rights_html(image)
        self.assertEqual(rights.count('>Estormiz</a>'),1)
        self.assertIn('Kuvan käyttöoikeudet',rights)
        self.assertIn('Kuvan lähde',rights)

    def test_generated_disclosure_only_below_hero(self):
        caption = 'AI-generoitu kuva. Ei valokuva tapahtumasta.'
        image = {'alt':'AI-generoitu kuva: neutraali rakennus.','caption':caption,
                 'generated':True,'license_url':'https://uutistenlukija.fi/ai-kuvat/'}
        self.assertEqual(site.article_hero_figure(image,'/image.jpg').count(caption),1)
        self.assertNotIn(caption,site.homepage_image_figure(image,'/image.jpg',False))
        self.assertNotIn(caption,site.image_rights_html(image))

    def test_category_classes_are_taxonomy_driven(self):
        self.assertIn('portal-list-header--kulttuuri',
                      site.category_page_body('Kulttuuri','Uutiset',[],'Ei juttuja'))
        items = [({'created_at':'2026-09-28T08:00:00+00:00'},
                  {'category':category,'title':'Aihe'},'/story/','28.09.2026')
                 for category in ('Kotimaa','Maailma','Talous','Tiede','Kulttuuri','Urheilu')]
        strip = site.homepage_topic_strip(items)
        for slug in ('kotimaa','ulkomaat','talous','tiede','kulttuuri','urheilu'):
            self.assertIn('portal-topic-card--'+slug,strip)

    def test_ai_fallback_prompt_allows_photographic_exact_concept(self):
        prompt = imagery._prompt_for('Suomen koulu','Kotimaa','yleinen koulutila',['school books'],[])
        self.assertIn('exact visual match',prompt)
        self.assertIn('photographic editorial aesthetic is allowed',prompt)
        self.assertIn('No cartoon',prompt)
        self.assertIn('flat vector',prompt)
        self.assertIn('watercolor',prompt)
        self.assertIn('glossy 3D',prompt)
        self.assertIn('identifiable real building',prompt)
        self.assertNotIn('Visibly non-documentary',prompt)
        self.assertNotIn('Flat two-dimensional editorial drawing',prompt)
        self.assertNotIn('matte gouache',prompt)

    def test_diversity_guard_changes_only_candidate_priority_after_four_civic_stories(self):
        config = {'discovery':{'family':'news-reviewed-v2','max_candidates':1}}
        def official(*args,provider_only=None,**kwargs):
            return [{'provider':provider_only,'url':'https://example.test/'+provider_only}]
        with patch('news_mvp.official.discover',side_effect=official), patch(
                'news_mvp.discovery.discover',return_value=[{'provider':'nasa-modis','url':'https://example.test/nasa'}]):
            ordinary = discover_mixed(config,after_provider='nasa-modis')
            guarded = discover_mixed(config,after_provider='nasa-modis',recent_categories=['Kotimaa']*4)
        self.assertEqual(ordinary[0]['provider'],'helsinki')
        self.assertIn(guarded[0]['provider'],{'stat','ecb','nasa-modis'})
        self.assertEqual({x['url'] for x in ordinary},{x['url'] for x in guarded})


if __name__=='__main__':
    unittest.main()

"""Article page markup and category/latest/guides pages from the same listing items.

Fixtures reuse the ReleaseV2/GeneratedIntegrity synthetic pipeline, so the reviewed
records, HTML escapes and temporary state boundaries stay exactly as the v2 suites
build them. Nothing here reaches the network, the model boundary or production state.
"""
import copy,hashlib,json,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path

from news_mvp import site
from news_mvp.release_contract import check_article
import test_generated_integrity as generated

SEED='test_generated_binding_keeps_text_provenance_and_not_applicable_marker'
IMAGE_MODEL='synthetic-model-x'  # stored model name; must never reach reader markup
CREDIT_FROM_MODEL='AI-kuvitus ('+IMAGE_MODEL+')'
ARTICLE_RE=re.compile(r'<article class="([^"]*)">(.*?)</article>',re.S)
SINGLE_RE=re.compile(r'<article class="([^"]*\bsingle-article\b[^"]*)">(.*?)</article>',re.S)
CATEGORY_LINK_RE=re.compile(r'<a class="category-label category-label--badge" href="([^"]+)"[^>]*>([^<]*)</a>')
H1_RE=re.compile(r'<h1[^>]*>(.*?)</h1>',re.S)
HERO_RE=re.compile(r'<figure class="article-hero">(.*?)</figure>',re.S)
CANON_RE=re.compile(r'<link rel="canonical" href="([^"]+)"')
LD_RE=re.compile(r'<script type="application/ld\+json">(.*?)</script>',re.S)
OG_RE=re.compile(r'<meta property="og:url" content="([^"]+)"')
INDEX_LD_RE=re.compile(r'@type": "ItemList"')
FEED_ITEM_RE=re.compile(r'<article class="portal-feed-item[^"]*">(.*?)</article>',re.S)
FEED_LINK_RE=re.compile(r'<h3><a href="([^"]+)"')


class PageScan(HTMLParser):
    """Start tags, images and visible text of one rendered page."""
    def __init__(self):
        super().__init__();self.starts=[];self.imgs=[];self.captions=[];self.text=[];self._caption=0
    def handle_starttag(self,tag,attrs):
        pairs=dict(attrs);self.starts.append((tag,pairs))
        if tag=='img':self.imgs.append(pairs)
        if tag=='figcaption':self._caption+=1
    def handle_endtag(self,tag):
        if tag=='figcaption':self._caption-=1
    def handle_data(self,data):
        self.text.append(data)
        if self._caption:self.captions.append(data)


class FakeStore:
    def __init__(self,jobs):self.jobs=jobs
    def articles(self):return list(self.jobs)
    def mark_rendered(self,ids):pass


class ArticleAndCategoryRendering(unittest.TestCase):
    def setUp(self):
        case=generated.GeneratedIntegrity(SEED);case.setUp();self.addCleanup(case.doCleanups)
        self.case=case
        self.packet,self.draft=case.generated()
        self.packet['image']['credit']='AI-kuvitus'
        self.packet['image']['model']=IMAGE_MODEL
        self.packet['image']['alt']='AI-generoitu kuva: Kirjaston hyllyt ja lukupöytä.'
        self.draft['image']=self.packet['image']
        self.template=case.ready(self.packet,self.draft)

    def jobs(self,categories):
        """One cloned approved job per (category,index); newest first by created_at."""
        jobs=[]
        for index,(category,tag) in enumerate(categories):
            job=dict(self.template)
            job['id']=hashlib.sha256(f'article-category:{index}:{tag}'.encode()).hexdigest()
            job['created_at']=(datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(minutes=index)).isoformat()
            draft=copy.deepcopy(self.draft);draft['category']=category
            job['draft']=json.dumps(draft)
            review=json.loads(job['review']);review['draft_sha256']=generated.digest(draft)
            job['review']=json.dumps(review)
            jobs.append(job)
        return jobs

    def render(self,categories,public=True):
        jobs=self.jobs(categories)
        output=Path(tempfile.mkdtemp(dir=self.case.root))
        count=site.render_site(FakeStore(jobs),output,self.case.state,public=public)
        return jobs,output,count

    def article_text(self,output,job):
        return (output/site.article_path(job)/'index.html').read_text()

    def test_article_preserves_content_metadata_and_related_and_source_list(self):
        jobs,output,_=self.render([('Kulttuuri','a'),('Kulttuuri','b')])
        html=self.article_text(output,jobs[0])
        match=SINGLE_RE.search(html)
        self.assertIsNotNone(match,'article must carry the native single-article class')
        body=match.group(2)
        draft=json.loads(jobs[0]['draft'])
        for paragraph in draft['paragraphs']:
            self.assertIn(paragraph['text'],body)
        self.assertIn(draft['title'],body);self.assertIn(draft['summary'],body)
        # Sources, method disclosure and the related-article rail all survive.
        self.assertIn('id="lahde-1"',body)
        self.assertIn('Teksti on tuotettu tekoälyn avulla ja tarkastettu erillisessä',body)
        self.assertIn('Lue myös',body)
        self.assertIn(site.article_path(jobs[1]),body)
        # The prose container is the theme's own .content, not the legacy .story-body.
        self.assertIn('<div class="content">',body)
        self.assertNotIn('story-body',body)
        self.assertNotIn('Luonnos',html)

    def test_article_hero_has_small_generated_caption_and_rights_sit_after_prose(self):
        jobs,output,_=self.render([('Kulttuuri','a'),('Kulttuuri','b')])
        html=self.article_text(output,jobs[0])
        hero=HERO_RE.search(html)
        self.assertIsNotNone(hero,'hero must be figure.article-hero')
        self.assertIn('<figcaption class="article-hero-caption">',hero.group(1))
        scan=PageScan();scan.feed(html)
        self.assertEqual(scan.captions,[self.packet['image']['caption']])
        self.assertIn('width="',hero.group(1));self.assertIn('height="',hero.group(1))
        self.assertIn('referrerpolicy="no-referrer"',hero.group(1))
        self.assertNotIn('portal-lead__image-label',hero.group(1))
        self.assertNotIn('AI-generoitu kuva · tekoälyllä luotu',html)
        prose_end=html.index('</div>',html.index('<div class="content">'))
        rights=html.index('<section class="image-rights">')
        sources=html.index('<section class="sources">')
        related=html.index('<section class="related">')
        self.assertLess(prose_end,rights,'image rights must follow the prose')
        self.assertLess(sources,rights,'image rights sit alongside the sources')
        self.assertLess(rights,related)
        self.assertIn('AI-kuvitus',html)
        self.assertIn('AI-kuvien käyttöehdot',html)
        # The complete honest caption and the licence terms link both stay.
        self.assertIn(self.packet['image']['caption'],html)
        self.assertIn(self.packet['image']['license_url'],html)
        # Stored model name is internal: it may never appear in reader markup.
        self.assertNotIn(IMAGE_MODEL,html)
        self.assertNotIn(CREDIT_FROM_MODEL,html)

    def test_article_badge_links_its_category_page_with_display_name(self):
        for stored,slug,display in [('Kotimaa','kotimaa','Kotimaa'),('Maailma','ulkomaat','Ulkomaat')]:
            with self.subTest(category=stored):
                jobs,output,_=self.render([(stored,'badge-'+slug)])
                html=self.article_text(output,jobs[0])
                match=CATEGORY_LINK_RE.search(html)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1),f'/categories/{slug}/')
                self.assertEqual(match.group(2),display)

    def test_category_pages_filter_and_map_maailma_and_show_empty_honestly(self):
        jobs,output,_=self.render([('Maailma','m1'),('Talous','t1'),('Tiede','x1')])
        ulkomaat=(output/'categories/ulkomaat/index.html').read_text()
        self.assertIn('Ulkomaat',ulkomaat)
        self.assertIn(json.loads(jobs[0]['draft'])['title'],ulkomaat)
        self.assertEqual([FEED_LINK_RE.search(item).group(1) for item in FEED_ITEM_RE.findall(ulkomaat)],
                         ['/'+site.article_path(jobs[0])])
        self.assertNotIn('Maailma',ulkomaat)
        # An empty category still publishes, and says so.
        urheilu=(output/'categories/urheilu/index.html').read_text()
        self.assertEqual(FEED_ITEM_RE.findall(urheilu),[])
        self.assertIn('Ei vielä tarkastettuja uutisia tässä kategoriassa.',urheilu)
        # The guides hub publishes honestly empty.
        oppaat=(output/'oppaat/index.html').read_text()
        self.assertIn('Oppaita ei ole vielä julkaistu.',oppaat)
        self.assertEqual(FEED_ITEM_RE.findall(oppaat),[])

    def test_latest_page_lists_every_reviewed_item_and_uses_feed_markup(self):
        categories=[('Kotimaa','l1'),('Talous','l2'),('Urheilu','l3')]
        jobs,output,_=self.render(categories)
        latest=(output/'tuoreimmat/index.html').read_text()
        self.assertIn('portal-list-page',latest)
        self.assertIn('portal-list-header',latest)
        self.assertIn('portal-list-feed',latest)
        self.assertNotIn('portal-front-grid',latest)
        links=[FEED_LINK_RE.search(item).group(1) for item in FEED_ITEM_RE.findall(latest)]
        self.assertEqual(links,['/'+site.article_path(j) for j in jobs])
        self.assertIn('portal-feed-item__time',latest)
        self.assertIn('portal-feed-item__body',latest)

    def test_public_pages_own_canonical_and_itemlist_private_stay_noindex(self):
        categories=[('Kotimaa','p1'),('Talous','p2')]
        jobs,output,_=self.render(categories)
        pages={'/tuoreimmat/':'tuoreimmat/index.html','/oppaat/':'oppaat/index.html',
               '/categories/kotimaa/':'categories/kotimaa/index.html',
               '/categories/urheilu/':'categories/urheilu/index.html'}
        for path,relative in pages.items():
            with self.subTest(path=path):
                html=(output/relative).read_text()
                self.assertEqual(CANON_RE.search(html).group(1),'https://uutistenlukija.fi'+path)
                self.assertEqual(OG_RE.search(html).group(1),'https://uutistenlukija.fi'+path)
                lists=[json.loads(block) for block in LD_RE.findall(html)]
                item_lists=[data for data in lists if data.get('@type')=='ItemList']
                self.assertEqual(len(item_lists),1)
                expected=2 if path=='/tuoreimmat/' else 1 if path=='/categories/kotimaa/' else 0
                self.assertEqual(len(item_lists[0]['itemListElement']),expected)
        latest=(output/'tuoreimmat/index.html').read_text()
        positions=[item['position'] for item in json.loads(LD_RE.findall(latest)[-1])['itemListElement']]
        self.assertEqual(positions,[1,2])
        # The private preview stays unindexed with no metadata at all.
        _,private,_=self.render(categories,public=False)
        private_html=(private/'tuoreimmat/index.html').read_text()
        self.assertIn('<meta name="robots" content="noindex,nofollow">',private_html)
        self.assertNotIn('rel="canonical"',private_html)
        self.assertNotIn('og:',private_html)
        self.assertNotIn('application/ld+json',private_html)


class BrandingImageContract(unittest.TestCase):
    """check_article must allow the exact brand logo and reject every other image."""

    def _draft(self):
        from test_cdn_email_contract import draft_with,PARAGRAPH
        return draft_with(PARAGRAPH)

    def _packet(self):
        from test_cdn_email_contract import packet
        return packet()

    def _html(self,images):
        from html import escape
        from test_cdn_email_contract import PARAGRAPH
        draft=self._draft();p=self._packet()
        source_items="".join(f'<li><a href="{escape(s["url"])}">{escape(s["publisher"])}: {escape(s["title"])}</a></li>' for s in p['sources'])
        return ('<!doctype html><html><body>'
                '<header>'+images['header']+'</header>'
                f'<h1>{escape(draft["title"])}</h1><p>{escape(draft["summary"])}</p>'
                f'<p>{escape(PARAGRAPH)}</p><ul>{source_items}</ul>'
                '<p>Tämä uutinen julkaistaan ilman kuvaa.</p>'
                '<footer>'+images['footer']+'</footer>'
                '</body></html>')

    def test_exact_logo_in_header_and_footer_is_allowed(self):
        for src in ['/mvp-assets/images/logo.png','/assets/images/logo.png']:
            with self.subTest(src=src):
                html=self._html({'header':f'<img src="{src}" alt="Uutistenlukija">',
                                 'footer':f'<img src="{src}" alt="Uutistenlukija">'})
                check_article(html,self._packet(),self._draft())  # must not raise

    def test_non_exact_branding_source_is_rejected(self):
        for src in ['/mvp-assets/images/logo2.png',
                    'https://foreign.example/images/logo.png',
                    '/uploads/images/logo.png',
                    '/mvp-assets/images/logo.png?x=1']:
            with self.subTest(src=src):
                html=self._html({'header':f'<img src="{src}" alt="logo">','footer':''})
                with self.assertRaises(ValueError):
                    check_article(html,self._packet(),self._draft())

    def test_logo_outside_header_and_footer_and_foreign_srcset_are_rejected(self):
        with self.subTest(place='body'):
            html=self._html({'header':'','footer':''}).replace('<h1>','<img src="/mvp-assets/images/logo.png"><h1>')
            with self.assertRaises(ValueError):
                check_article(html,self._packet(),self._draft())
        with self.subTest(kind='srcset'):
            html=self._html({'header':'<img src="/mvp-assets/images/logo.png" srcset="/mvp-assets/evil.jpg 2x">','footer':''})
            with self.assertRaises(ValueError):
                check_article(html,self._packet(),self._draft())
        with self.subTest(kind='foreign'):
            html=self._html({'header':'<img src="/mvp-assets/foreign-editorial.jpg">','footer':''})
            with self.assertRaises(ValueError):
                check_article(html,self._packet(),self._draft())

    def test_duplicate_picture_and_nested_article_branding_bypasses_are_rejected(self):
        duplicate=self._html({'header':'<img src="/mvp-assets/images/logo.png" src="https://foreign.example/images/logo.png">',
                              'footer':''})
        picture=self._html({'header':'<picture><source srcset="/uploads/images/logo.png"><img src="/mvp-assets/images/logo.png"></picture>',
                            'footer':''})
        nested=self._html({'header':'','footer':''}).replace(
            '<h1>', '<main><article class="portal-teaser"><img src="/mvp-assets/images/logo.png"></article><h1>'
        ).replace('<footer>', '</main><footer>')
        for name,html in [('duplicate',duplicate),('picture',picture),('nested',nested)]:
            with self.subTest(kind=name),self.assertRaises(ValueError):
                check_article(html,self._packet(),self._draft())

    def test_disclosure_and_preview_marker_still_mandatory(self):
        ok=self._html({'header':'' ,'footer':''})
        check_article(ok,self._packet(),self._draft())
        for damage in [lambda h:h.replace('Tämä uutinen julkaistaan ilman kuvaa.',''),
                       lambda h:h.replace('<body>','<body><div class="preview">Yksityinen esikatselu · ei julkaistu</div>')]:
            with self.subTest():
                with self.assertRaises(ValueError):
                    check_article(damage(ok),self._packet(),self._draft())


class GeneratedCreditContract(unittest.TestCase):
    """AI-kuvitus is the required normalized reader credit."""

    def _draft(self):
        from test_cdn_email_contract import GENERATED_IMAGE,draft_with,PARAGRAPH
        draft=draft_with(PARAGRAPH);draft['image']=GENERATED_IMAGE;return draft

    def _html(self,credit):
        from html import escape
        from test_cdn_email_contract import GENERATED_IMAGE,PARAGRAPH,packet
        draft=self._draft();p=packet()
        source_items="".join(f'<li><a href="{escape(s["url"])}">{escape(s["publisher"])}: {escape(s["title"])}</a></li>' for s in p['sources'])
        return ('<!doctype html><html><body>'
                f'<h1>{escape(draft["title"])}</h1><p>{escape(draft["summary"])}</p><p>{escape(PARAGRAPH)}</p>'
                f'<figure><img src="/mvp-assets/{"a"*64}.jpg" alt="{escape(GENERATED_IMAGE["alt"])}"></figure>'
                f'<p>{escape(GENERATED_IMAGE["caption"])} {escape(credit)} · '
                f'<a href="{escape(GENERATED_IMAGE["license_url"])}">AI-kuvien käyttöehdot</a></p>'
                f'<ul>{source_items}</ul></body></html>')

    def test_normalized_ai_kuvitus_credit_passes(self):
        check_article(self._html('AI-kuvitus'),self._packet_for(),self._draft())

    def test_stored_normalized_credit_passes_and_wrong_credit_fails(self):
        from test_cdn_email_contract import GENERATED_IMAGE
        check_article(self._html(GENERATED_IMAGE['credit']),self._packet_for(),self._draft())
        with self.assertRaises(ValueError):
            check_article(self._html('Kuvitus'),self._packet_for(),self._draft())

    def test_missing_caption_or_license_still_fails(self):
        from html import escape
        from test_cdn_email_contract import GENERATED_IMAGE
        html=self._html('AI-kuvitus')
        with self.assertRaises(ValueError):
            check_article(html.replace(escape(GENERATED_IMAGE['caption']),''),self._packet_for(),self._draft())
        with self.assertRaises(ValueError):
            check_article(html.replace(escape(GENERATED_IMAGE['license_url']),'/muu/'),self._packet_for(),self._draft())

    def _packet_for(self):
        from test_cdn_email_contract import packet
        return packet()


if __name__=='__main__':
    unittest.main()

"""Homepage rendering of reviewed generated images, and private archive pagination.

Synthetic images only: the illustrated stories carry the same synthetic JPEG the
generated-integrity suite builds, and every rendered byte lives under a temporary
directory. The public homepage must present a reviewed illustration exactly as it
was reviewed (asset bytes, dimensions, alt text, AI-illustration label, lazy rules),
and the private listing archive must stay unindexed and image-free.

Image selection here excludes branding by exact identity only, never by URL prefix:
the site logo is the one image allowed to appear outside the reviewed-image
inventory, and it is dropped as ``/mvp-assets/images/logo.png`` (public) or
``/assets/images/logo.png`` (private) alone. Every other ``<img>`` on the page -
including one at a foreign URL - is editorial and must match the reviewed fixture's
local asset, so a stray or private image can never hide behind a filter.
"""
import copy,hashlib,json,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from news_mvp import site
from news_mvp.release_contract import _only_branding_images
import test_generated_integrity as generated
from image_helpers import BRANDING_SRCS, editorial_images, scan, PageScan

ARTICLE_RE=re.compile(r'<article class="([^"]*)">(.*?)</article>',re.S)
H2_RE=re.compile(r'<h[23][^>]*>\s*<a href="([^"]+)"')
LINK_RE=re.compile(r'<a[^>]*href="([^"]+)"')
IMG_RE=re.compile(r'<img [^>]*>')
NEXT_RE=re.compile(r'<a [^>]*rel="next"[^>]*href="([^"]+)"')
PREV_RE=re.compile(r'<a [^>]*rel="prev"[^>]*href="([^"]+)"')
SEED='test_generated_binding_keeps_text_provenance_and_not_applicable_marker'

def images(fragment):
    """Every <img> in one fragment, as HTMLParser parsed it."""
    return [scan(match.group(0)).imgs[0] for match in IMG_RE.finditer(fragment)]

class FakeStore:
    def __init__(self,jobs):self.jobs=jobs
    def articles(self):return list(self.jobs)
    def mark_rendered(self,ids):pass

class HomepageImages(unittest.TestCase):
    def jobs(self,template,count,tag):
        jobs=[]
        for index in range(count):
            job=dict(template)
            job['id']=hashlib.sha256(f'{tag}:{index}:{template["id"]}'.encode()).hexdigest()
            job['created_at']=(datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(minutes=index)).isoformat()
            jobs.append(job)
        return jobs

    def test_public_homepage_renders_reviewed_generated_images(self):
        case=generated.GeneratedIntegrity(SEED);case.setUp();self.addCleanup(case.doCleanups)
        packet,draft=case.generated();job=case.ready(packet,draft)
        stored=json.loads(job['packet'])['image'];sha=stored['sha256']
        jobs=self.jobs(job,4,'homepage-images')
        self.assertTrue(all(isinstance(j[f],str) for j in jobs for f in ('packet','draft','review')))
        for cloned in jobs:
            for field in ('packet','draft','review'):
                json.loads(cloned[field])
        self.assertEqual(len({j['id'] for j in jobs}),4)
        self.assertTrue(all(len(j['id'])==64 for j in jobs))
        self.assertEqual([j['created_at'] for j in jobs],sorted((j['created_at'] for j in jobs),reverse=True))
        output=Path(tempfile.mkdtemp(dir=case.root))
        self.assertEqual(site.render_site(FakeStore(jobs),output,case.state,public=True),4)
        home=(output/'index.html').read_text()
        entries=[(cls,body) for cls,body in ARTICLE_RE.findall(home)]
        links=[LINK_RE.search(body).group(1) for _,body in entries]
        self.assertEqual(links,['/'+site.article_path(j) for j in jobs])
        self.assertEqual(len(set(links)),4)
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries),
                          sum(cls.startswith('portal-teaser') for cls,_ in entries)],[1,3])
        lead=images(entries[0][1])[0]
        self.assertEqual((lead['src'],lead['width'],lead['height'],lead['decoding']),
                         (f'/mvp-assets/{sha}.jpg','1536','1024','async'))
        self.assertEqual(lead['alt'],stored['alt'])
        self.assertNotIn('loading',lead)
        for cls,body in entries[1:]:
            self.assertEqual(images(body),[])
            self.assertTrue(cls.startswith('portal-teaser') or cls.startswith('portal-row-card'),cls)
            self.assertIn('--no-image',cls)
        parsed=scan(home)
        self.assertEqual(len(editorial_images(parsed)),1)
        self.assertEqual(parsed.captions,[])
        self.assertNotIn('<figcaption',home)
        self.assertNotIn('<article class="card"',home)
        self.assertNotIn('<section class="grid"',home)
        self.assertEqual(home.count('<article class="'),4)
        self.assertEqual(sum('Kuvituskuva' in text for text in parsed.text),1)
        self.assertEqual(sum('tekoälyllä luotu' in text for text in parsed.text),1)
        self.assertIn('Seuraa uutisia',home)
        self.assertIn('href="/rss.xml"',home)
        self.assertIn('portal-right-rail',home)
        asset=output/f'mvp-assets/{sha}.jpg'
        self.assertEqual(sorted(p.name for p in (output/'mvp-assets').glob('*.jpg')),[f'{sha}.jpg'])
        data=asset.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),sha)
        self.assertEqual(data,generated.SYNTHETIC)
        for link in links:
            article=scan((output/link.lstrip('/')/'index.html').read_text())
            self.assertEqual([attrs['src'] for attrs in editorial_images(article)],[f'/mvp-assets/{sha}.jpg'])
            self.assertEqual([attrs['alt'] for attrs in editorial_images(article)],[stored['alt']])
            self.assertTrue(any('Kuvituskuva' in text for text in article.text))

    def test_generated_image_alt_and_credit_stay_escaped_text(self):
        case=generated.GeneratedIntegrity(SEED);case.setUp();self.addCleanup(case.doCleanups)
        packet,draft=case.generated()
        alt='Kuvituskuva <b>AI</b> & "lainaus" <script>alert(1)</script>'
        credit='AI <i>synthetic</i> & "credit" <img src=x onerror=alert(1)>'
        image=dict(packet['image']);image['alt']=alt;image['credit']=credit
        packet['image']=image;draft['image']=copy.deepcopy(image)
        job=case.ready(packet,draft)
        sha=json.loads(job['packet'])['image']['sha256']
        jobs=self.jobs(job,4,'homepage-escaping')
        output=Path(tempfile.mkdtemp(dir=case.root))
        self.assertEqual(site.render_site(FakeStore(jobs),output,case.state,public=True),4)
        home=(output/'index.html').read_text()
        self.assertNotIn('<b>',home)
        self.assertNotIn('<i>',home)
        self.assertNotIn('<script>alert(1)</script>',home)
        self.assertEqual(home.count('<img'),2)
        parsed=scan(home)
        self.assertEqual([attrs['alt'] for attrs in editorial_images(parsed)],[alt])
        self.assertEqual([attrs['src'] for attrs in editorial_images(parsed)],[f'/mvp-assets/{sha}.jpg'])
        self.assertEqual(parsed.captions,[])
        self.assertNotIn(credit,home)
        self.assertEqual(sum('Kuvituskuva' in text for text in parsed.text),1)
        self.assertEqual(sum('tekoälyllä luotu' in text for text in parsed.text),1)
        self.assertNotIn('AI-kuvitus',home)
        self.assertNotIn('synthetic',home)
        self.assertNotIn('explicit-offline-test-double',home)
        for path in sorted(output.rglob('*.html')):
            page=scan(path.read_text())
            self.assertTrue(set(tag for tag,_ in page.starts).isdisjoint({'b','i','blink'}),path)
            self.assertFalse(any('onerror' in attrs for _,attrs in page.starts),path)
            for attrs in editorial_images(page):
                self.assertEqual(attrs['src'],f'/mvp-assets/{sha}.jpg',path)

    def test_private_archive_pages_stay_noindex_and_image_free(self):
        case=generated.GeneratedIntegrity(SEED);case.setUp();self.addCleanup(case.doCleanups)
        template=case.ready()
        self.assertIsNone(json.loads(template['draft'])['image'])
        jobs=self.jobs(template,31,'homepage-private')
        output=Path(tempfile.mkdtemp(dir=case.root))
        self.assertEqual(site.render_site(FakeStore(jobs),output,case.state,public=False),31)
        listing={relative:(output/relative).read_text() for relative in ('index.html','sivu/2/index.html')}
        for relative,html in listing.items():
            with self.subTest(page=relative):
                self.assertIn('<meta name="robots" content="noindex,nofollow">',html)
                self.assertNotIn('rel="canonical"',html)
                self.assertNotIn('og:',html)
                self.assertNotIn('application/ld+json',html)
                self.assertEqual([attrs['src'] for attrs in editorial_images(scan(html))],[])
                self.assertEqual([attrs['src'] for attrs in scan(html).imgs],['/assets/images/logo.png'])
        first,second=listing['index.html'],listing['sivu/2/index.html']
        entries_first=[(cls,body) for cls,body in ARTICLE_RE.findall(first)]
        entries_second=[(cls,body) for cls,body in ARTICLE_RE.findall(second)]
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries_first),len(entries_first)],[1,30])
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries_second),len(entries_second)],[0,1])
        self.assertEqual(sum(cls.startswith('portal-teaser') for cls,_ in entries_first),4)
        self.assertEqual(sum(cls.startswith('portal-row-card') for cls,_ in entries_first),25)
        self.assertIn('portal-front-grid',first)
        self.assertIn('portal-right-rail',first)
        self.assertNotIn('portal-right-rail',second)
        self.assertNotIn('portal-front-grid',second)
        self.assertIn('portal-river',first)
        self.assertNotIn('portal-river',second)
        # This fixture is intentionally imageless: the newest story remains a text-only
        # lead and must not acquire an invented hash or placeholder image.
        self.assertEqual(editorial_images(scan(first)),[])
        self.assertTrue(all(images(body)==[] for _,body in entries_first[1:]),first)
        self.assertNotIn('portal-row-card__thumb',first)
        expected=['/'+site.article_path(j) for j in jobs]
        self.assertEqual([LINK_RE.search(body).group(1) for _,body in entries_first]+
                         [LINK_RE.search(body).group(1) for _,body in entries_second],expected)
        self.assertEqual(len(set(expected)),31)
        self.assertEqual(NEXT_RE.findall(first),[])
        self.assertEqual(PREV_RE.findall(first),[])
        self.assertEqual(PREV_RE.findall(second),['/'])
        self.assertEqual(NEXT_RE.findall(second),[])
        self.assertNotIn('<nav class="pager"',first)
        self.assertIn('<nav class="pager"',second)
        self.assertTrue((output/'sivu/2/index.html').is_file())
        for link in expected:self.assertTrue((output/link.lstrip('/')/'index.html').is_file())

    def test_branding_acceptance_matrix_is_exact_and_contextual(self):
        outer = scan('<header><img src="/mvp-assets/images/logo.png">'
                     '<img src="/assets/images/logo.png"></header><footer>'
                     '<img src="/mvp-assets/images/logo.png"></footer>')
        self.assertEqual(editorial_images(outer), [])
        for src in ['https://foreign.example/images/logo.png', '/uploads/images/logo.png',
                    '/mvp-assets/images/logo.png?alternate=1']:
            with self.subTest(src=src):
                self.assertEqual(len(editorial_images(scan(f'<header><img src="{src}"></header>'))), 1)
        for wrapper in ['<main><img src="/mvp-assets/images/logo.png"></main>',
                        '<article><img src="/mvp-assets/images/logo.png"></article>',
                        '<div class="portal-teaser"><img src="/mvp-assets/images/logo.png"></div>']:
            with self.subTest(wrapper=wrapper):
                self.assertEqual(len(editorial_images(scan(wrapper))), 1)

    def test_branding_parser_tracks_actual_nested_scopes(self):
        bypasses = [
            '<header><div class="article"><div>intro</div><header>'
            '<img src="/mvp-assets/images/logo.png"></header></div></header>',
            '<header><div class="portal-teaser"><div>intro</div>'
            '<img src="/mvp-assets/images/logo.png"></div></header>',
        ]
        for html in bypasses:
            with self.subTest(html=html):
                self.assertFalse(_only_branding_images(html))
                self.assertEqual(len(editorial_images(scan(html))), 1)
        valid_nested = ('<header><div><header><img src="/mvp-assets/images/logo.png"></header>'
                        '</div></header>')
        self.assertEqual(editorial_images(scan(valid_nested)), [])
        self.assertTrue(_only_branding_images(
            valid_nested
        ))

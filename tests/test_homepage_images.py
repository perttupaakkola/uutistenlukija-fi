"""Homepage rendering of reviewed generated images, and private archive pagination.

Synthetic images only: the illustrated stories carry the same synthetic JPEG the
generated-integrity suite builds, and every rendered byte lives under a temporary
directory. The public homepage must present a reviewed illustration exactly as it
was reviewed (asset bytes, dimensions, alt text, AI-illustration label, lazy rules),
and the private listing archive must stay unindexed and image-free.
"""
import copy,hashlib,json,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path
from news_mvp import site
import test_generated_integrity as generated

ARTICLE_RE=re.compile(r'<article class="([^"]*)">(.*?)</article>',re.S)
LINK_RE=re.compile(r'<h2[^>]*>\s*<a href="([^"]+)"')
IMG_RE=re.compile(r'<img [^>]*>')
NEXT_RE=re.compile(r'<a [^>]*rel="next"[^>]*href="([^"]+)"')
PREV_RE=re.compile(r'<a [^>]*rel="prev"[^>]*href="([^"]+)"')
SEED='test_generated_binding_keeps_text_provenance_and_not_applicable_marker'

class PageScan(HTMLParser):
    """Start tags, parsed attributes and visible text of one rendered page."""
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

def scan(text):
    parsed=PageScan();parsed.feed(text);return parsed

def article_image(fragment):
    """The single <img> of one homepage card, as HTMLParser parsed it."""
    return scan(IMG_RE.search(fragment).group(0)).imgs[0]

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
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries),sum(cls=='card' for cls,_ in entries)],[1,3])
        images=[article_image(body) for _,body in entries]
        self.assertEqual(len(images),4)
        for attrs in images:
            self.assertEqual(attrs['src'],f'/mvp-assets/{sha}.jpg')
            self.assertEqual((attrs['width'],attrs['height'],attrs['decoding']),('1536','1024','async'))
            self.assertEqual(attrs['alt'],stored['alt'])
        self.assertNotIn('loading',images[0])
        self.assertEqual([attrs.get('loading') for attrs in images[1:]],['lazy']*3)
        parsed=scan(home)
        self.assertEqual(len(parsed.imgs),4)
        self.assertEqual(sum('Kuvituskuva' in text for text in parsed.text),4)
        asset=output/f'mvp-assets/{sha}.jpg'
        self.assertEqual(sorted(p.name for p in (output/'mvp-assets').glob('*.jpg')),[f'{sha}.jpg'])
        data=asset.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),sha)
        self.assertEqual(data,generated.SYNTHETIC)
        for link in links:
            article=scan((output/link.lstrip('/')/'index.html').read_text())
            self.assertEqual([attrs['src'] for attrs in article.imgs],[f'/mvp-assets/{sha}.jpg'])
            self.assertEqual([attrs['alt'] for attrs in article.imgs],[stored['alt']])
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
        self.assertEqual(home.count('<img'),4)
        parsed=scan(home)
        self.assertEqual([attrs['alt'] for attrs in parsed.imgs],[alt]*4)
        self.assertEqual(parsed.captions.count('Kuvituskuva · '+credit),4)
        self.assertEqual(parsed.text.count('Kuvituskuva · '+credit),4)
        self.assertEqual([attrs['src'] for attrs in parsed.imgs],[f'/mvp-assets/{sha}.jpg']*4)
        for path in sorted(output.rglob('*.html')):
            page=scan(path.read_text())
            self.assertTrue(set(tag for tag,_ in page.starts).isdisjoint({'b','i','blink'}),path)
            self.assertFalse(any('onerror' in attrs for _,attrs in page.starts),path)
            self.assertTrue(all(attrs['src'].startswith('/mvp-assets/') for attrs in page.imgs),path)

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
                self.assertNotIn('<img',html)
        first,second=listing['index.html'],listing['sivu/2/index.html']
        entries_first=[(cls,body) for cls,body in ARTICLE_RE.findall(first)]
        entries_second=[(cls,body) for cls,body in ARTICLE_RE.findall(second)]
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries_first),len(entries_first)],[1,30])
        self.assertEqual([sum('lead-story' in cls for cls,_ in entries_second),len(entries_second)],[0,1])
        expected=['/'+site.article_path(j) for j in jobs]
        self.assertEqual([LINK_RE.search(body).group(1) for _,body in entries_first]+
                         [LINK_RE.search(body).group(1) for _,body in entries_second],expected)
        self.assertEqual(len(set(expected)),31)
        self.assertEqual(NEXT_RE.findall(first),['/sivu/2/'])
        self.assertEqual(PREV_RE.findall(first),[])
        self.assertEqual(PREV_RE.findall(second),['/'])
        self.assertEqual(NEXT_RE.findall(second),[])
        self.assertTrue((output/'sivu/2/index.html').is_file())
        for link in expected:self.assertTrue((output/link.lstrip('/')/'index.html').is_file())

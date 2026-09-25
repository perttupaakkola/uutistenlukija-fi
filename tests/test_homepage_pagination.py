"""Pagination counts, story identity and per-page metadata for the public homepage.

The homepage keeps the portal shape: one promoted lead, the first configured
remaining stories as center teaser rows inside the top grid, and every later story as a
text-only river row outside it. Archive pages keep plain text rows and their pager.
"""
import copy,hashlib,json,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from news_mvp import site
import test_release_v2 as base

SITE="https://uutistenlukija.fi"
ARTICLE_RE=re.compile(r'<article class="([^"]*)">(.*?)</article>',re.S)
H2_RE=re.compile(r'<h[23][^>]*>\s*<a href="([^"]+)"')
LD_RE=re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',re.S)
CANON_RE=re.compile(r'<link rel="canonical" href="([^"]+)"')
OG_RE=re.compile(r'<meta property="og:url" content="([^"]+)">')
PREV_RE=re.compile(r'<a [^>]*rel="prev"[^>]*href="([^"]+)"')
NEXT_RE=re.compile(r'<a [^>]*rel="next"[^>]*href="([^"]+)"')
IMG_RE=re.compile(r'<img [^>]*src="([^"]+)"')

def images_in(html):
    """Every image src on the page; the homepage must show only the brand logo."""
    return IMG_RE.findall(html)

class FakeStore:
    def __init__(self,jobs):self.jobs=jobs
    def articles(self):return list(self.jobs)
    def mark_rendered(self,ids):pass

class HomepagePagination(unittest.TestCase):
    def test_counts_identity_and_metadata(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        template=case.ready()
        for count in (0,1,30,31,61):
            with self.subTest(count=count):
                jobs=[]
                for index in range(count):
                    job=dict(template)
                    job['id']=hashlib.sha256(f'{count}:{index}:{template["id"]}'.encode()).hexdigest()
                    job['created_at']=(datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(minutes=index)).isoformat()
                    jobs.append(job)
                output=Path(tempfile.mkdtemp(dir=case.root))
                self.assertEqual(site.render_site(FakeStore(jobs),output,case.state,public=True),count)
                expected_links=['/'+site.article_path(job) for job in jobs]
                page_count=max(1,-(-count//30))
                listing_files=sorted(str(p.relative_to(output)) for p in output.glob('index.html'))
                listing_files+=sorted(str(p.relative_to(output)) for p in output.glob('sivu/*/index.html'))
                self.assertEqual(listing_files,['index.html']+[f'sivu/{n}/index.html' for n in range(2,page_count+1)])
                seen=[]
                for page_number in range(1,page_count+1):
                    page_path='/' if page_number==1 else f'/sivu/{page_number}/'
                    html=(output/('index.html' if page_number==1 else f'sivu/{page_number}/index.html')).read_text()
                    entries=[(cls,H2_RE.search(body).group(1)) for cls,body in ARTICLE_RE.findall(html)]
                    slice_links=expected_links[(page_number-1)*30:page_number*30]
                    self.assertEqual([link for _,link in entries],slice_links)
                    self.assertLessEqual(len(entries),30)
                    self.assertEqual(sum('lead-story' in cls for cls,_ in entries),1 if page_number==1 and count else 0)
                    if page_number==1 and count:
                        self.assertIn('portal-front-grid',html)
                        self.assertIn('portal-right-rail',html)
                        remaining=min(count,30)-1
                        self.assertEqual(sum(cls.startswith('portal-teaser') for cls,_ in entries),
                                         min(remaining,site.HOMEPAGE_CENTER_ROWS))
                        self.assertEqual(sum(cls.startswith('portal-row-card') for cls,_ in entries),
                                         max(0,remaining-site.HOMEPAGE_CENTER_ROWS))
                        # Every illustrated story uses its original native image slot.
                        self.assertEqual(len(images_in(html)),1 + len(entries))
                        self.assertEqual(images_in(html)[0],'/mvp-assets/images/logo.png')
                        if remaining>site.HOMEPAGE_CENTER_ROWS:
                            self.assertIn('portal-river',html)
                            self.assertIn('portal-river__grid',html)
                        else:
                            self.assertNotIn('portal-river',html)
                    self.assertNotIn('<article class="card"',html)
                    self.assertNotIn('<section class="grid"',html)
                    self.assertNotIn('<figcaption',html)
                    self.assertEqual(CANON_RE.search(html).group(1),SITE+page_path)
                    self.assertEqual(OG_RE.search(html).group(1),SITE+page_path)
                    item_lists=[json.loads(block) for block in LD_RE.findall(html)]
                    item_lists=[data for data in item_lists if data.get('@type')=='ItemList']
                    self.assertEqual(len(item_lists),1)
                    elements=item_lists[0]['itemListElement']
                    self.assertEqual([e['url'] for e in elements],[SITE+link for link in slice_links])
                    self.assertEqual([e['position'] for e in elements],list(range((page_number-1)*30+1,(page_number-1)*30+len(slice_links)+1)))
                    if page_number==1:
                        # The homepage shows the newest stories only and carries no pager.
                        self.assertEqual(PREV_RE.findall(html),[])
                        self.assertEqual(NEXT_RE.findall(html),[])
                        self.assertNotIn('<nav class="pager"',html)
                    else:
                        self.assertEqual(PREV_RE.findall(html),['/'] if page_number==2 else [f'/sivu/{page_number-1}/'])
                        self.assertEqual(NEXT_RE.findall(html),[f'/sivu/{page_number+1}/'] if page_number<page_count else [])
                        self.assertIn('<nav class="pager"',html)
                    seen+=slice_links
                self.assertEqual(seen,expected_links)
                self.assertEqual(len(seen),len(set(seen)))
                if count<=30:self.assertFalse((output/'sivu/2/index.html').exists())
                for link in expected_links:self.assertTrue((output/link.lstrip('/')/'index.html').is_file())
                self.assertEqual((output/'rss.xml').read_text().count('<item>'),count)

    def test_maailma_shows_ulkomaat_without_changing_the_reviewed_draft(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        template=case.ready()
        draft=json.loads(template['draft']);draft['category']='Maailma'
        job=case.ready(json.loads(template['packet']),draft)
        self.assertEqual(json.loads(job['draft'])['category'],'Maailma')
        jobs=[]
        for index in range(6):
            clone=dict(job)
            clone['id']=hashlib.sha256(f'maailma:{index}:{job["id"]}'.encode()).hexdigest()
            clone['created_at']=(datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(minutes=index)).isoformat()
            jobs.append(clone)
        output=Path(tempfile.mkdtemp(dir=case.root))
        self.assertEqual(site.render_site(FakeStore(jobs),output,case.state,public=True),6)
        html=(output/'index.html').read_text()
        # Reader-visible label and colour slug are mapped locally while the stored
        # draft keeps the category it was reviewed with.
        self.assertNotIn('Maailma',html)
        self.assertIn('>Ulkomaat<',html)
        story_labels=(html.count('>Ulkomaat<')
                      - html.count('<a href="/categories/ulkomaat/">Ulkomaat</a>')
                      - html.count('portal-topic-card__label'))
        self.assertEqual(story_labels,6)
        self.assertIn('portal-teaser__category--ulkomaat',html)
        if len(jobs) - 1 > site.HOMEPAGE_CENTER_ROWS:
            self.assertIn('portal-row-card__category--ulkomaat',html)
        for clone in jobs:
            self.assertEqual(json.loads(clone['draft'])['category'],'Maailma')
        self.assertEqual(json.loads(job['draft'])['category'],'Maailma')

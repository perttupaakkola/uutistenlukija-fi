"""Pagination counts, story identity and per-page metadata for the public homepage."""
import hashlib,json,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from news_mvp import site
import test_release_v2 as base

SITE="https://uutistenlukija.fi"
ARTICLE_RE=re.compile(r'<article class="([^"]*)">(.*?)</article>',re.S)
H2_RE=re.compile(r'<h2[^>]*>\s*<a href="([^"]+)"')
LD_RE=re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',re.S)
CANON_RE=re.compile(r'<link rel="canonical" href="([^"]+)"')
OG_RE=re.compile(r'<meta property="og:url" content="([^"]+)">')
PREV_RE=re.compile(r'<a [^>]*rel="prev"[^>]*href="([^"]+)"')
NEXT_RE=re.compile(r'<a [^>]*rel="next"[^>]*href="([^"]+)"')

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
                    self.assertEqual(CANON_RE.search(html).group(1),SITE+page_path)
                    self.assertEqual(OG_RE.search(html).group(1),SITE+page_path)
                    item_lists=[json.loads(block) for block in LD_RE.findall(html)]
                    item_lists=[data for data in item_lists if data.get('@type')=='ItemList']
                    self.assertEqual(len(item_lists),1)
                    elements=item_lists[0]['itemListElement']
                    self.assertEqual([e['url'] for e in elements],[SITE+link for link in slice_links])
                    self.assertEqual([e['position'] for e in elements],list(range((page_number-1)*30+1,(page_number-1)*30+len(slice_links)+1)))
                    self.assertEqual(PREV_RE.findall(html),['/'] if page_number==2 else [f'/sivu/{page_number-1}/'] if page_number>2 else [])
                    self.assertEqual(NEXT_RE.findall(html),[f'/sivu/{page_number+1}/'] if page_number<page_count else [])
                    seen+=slice_links
                self.assertEqual(seen,expected_links)
                self.assertEqual(len(seen),len(set(seen)))
                if count<=30:self.assertFalse((output/'sivu/2/index.html').exists())
                for link in expected_links:self.assertTrue((output/link.lstrip('/')/'index.html').is_file())
                self.assertEqual((output/'rss.xml').read_text().count('<item>'),count)

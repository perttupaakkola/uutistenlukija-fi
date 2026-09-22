"""Containment and shrink guarantees for the stale listing-page prune."""
import hashlib,re,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from news_mvp import site
import test_release_v2 as base

NEXT_RE=re.compile(r'<a [^>]*rel="next"[^>]*href="([^"]+)"')
PREV_RE=re.compile(r'<a [^>]*rel="prev"[^>]*href="([^"]+)"')

class FakeStore:
    def __init__(self,jobs):self.jobs=jobs
    def articles(self):return list(self.jobs)
    def mark_rendered(self,ids):pass

def jobs_for(template,count):
    jobs=[]
    for index in range(count):
        job=dict(template)
        job['id']=hashlib.sha256(f'{count}:{index}:{template["id"]}'.encode()).hexdigest()
        job['created_at']=(datetime(2026,1,1,tzinfo=timezone.utc)-timedelta(minutes=index)).isoformat()
        jobs.append(job)
    return jobs

class HomepageCleanup(unittest.TestCase):
    def test_prune_removes_only_stale_pages_and_never_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'output';sivu=output/'sivu';sivu.mkdir(parents=True)
            # Obsolete page 3: only our own page, so the emptied directory goes too.
            (sivu/'3').mkdir();(sivu/'3/index.html').write_text('stale page')
            # Current page 2 (page_count=2) and a non-numeric unrelated directory.
            (sivu/'2').mkdir();(sivu/'2/index.html').write_text('current page')
            (sivu/'custom').mkdir();(sivu/'custom/index.html').write_text('unrelated page')
            # Obsolete page 4 that also holds a foreign file: page goes, directory stays.
            (sivu/'4').mkdir();(sivu/'4/index.html').write_text('stale page')
            (sivu/'4/foreign.txt').write_text('not ours')
            # Numeric name that is a regular file, not a directory.
            (sivu/'98').write_text('numeric regular file')
            # Numeric directory symlink pointing outside the output tree.
            external=root/'external';external.mkdir();(external/'index.html').write_text('linked sentinel')
            (sivu/'99').symlink_to(external,target_is_directory=True)
            # Real numeric directory whose index.html is a symlink to a file sentinel.
            sentinel=root/'sentinel.html';sentinel.write_text('file sentinel')
            (sivu/'5').mkdir();(sivu/'5/index.html').symlink_to(sentinel)
            site.prune_stale_listing_pages(output,2)
            self.assertFalse((sivu/'3').exists())
            self.assertFalse((sivu/'4/index.html').exists())
            self.assertEqual((sivu/'4/foreign.txt').read_text(),'not ours')
            self.assertTrue((sivu/'4').is_dir())
            self.assertEqual((sivu/'2/index.html').read_text(),'current page')
            self.assertEqual((sivu/'custom/index.html').read_text(),'unrelated page')
            self.assertEqual((sivu/'98').read_text(),'numeric regular file')
            self.assertTrue((sivu/'99').is_symlink())
            self.assertEqual((external/'index.html').read_text(),'linked sentinel')
            self.assertTrue((sivu/'5/index.html').is_symlink())
            self.assertTrue((sivu/'5').is_dir() and not (sivu/'5').is_symlink())
            self.assertEqual(sentinel.read_text(),'file sentinel')
            # A symlinked sivu root is not ours to walk, so its real obsolete page survives
            # even though the guard sees a directory with a numeric name inside it.
            linked_root=root/'linked-root';(linked_root/'3').mkdir(parents=True)
            (linked_root/'3/index.html').write_text('page behind a linked root')
            linked_output=root/'linked-output';linked_output.mkdir()
            (linked_output/'sivu').symlink_to(linked_root,target_is_directory=True)
            site.prune_stale_listing_pages(linked_output,2)
            self.assertEqual((linked_root/'3/index.html').read_text(),'page behind a linked root')

    def test_render_shrink_removes_generated_pages_and_keeps_foreign_files(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        template=case.ready()
        output=Path(tempfile.mkdtemp(dir=case.root))
        # Unrelated paths written before the render must survive the shrink untouched.
        (output/'sivu/custom').mkdir(parents=True);(output/'sivu/custom/index.html').write_text('unrelated page')
        (output/'sivu/2').mkdir();(output/'sivu/2/foreign.txt').write_text('not ours')
        self.assertEqual(site.render_site(FakeStore(jobs_for(template,61)),output,case.state,public=False),61)
        self.assertTrue((output/'sivu/2/index.html').is_file())
        self.assertTrue((output/'sivu/3/index.html').is_file())
        # The same output directory shrunk to a single story keeps page 1 only.
        self.assertEqual(site.render_site(FakeStore(jobs_for(template,1)),output,case.state,public=False),1)
        self.assertFalse((output/'sivu/2/index.html').exists())
        self.assertFalse((output/'sivu/3').exists())
        self.assertEqual((output/'sivu/2/foreign.txt').read_text(),'not ours')
        self.assertEqual((output/'sivu/custom/index.html').read_text(),'unrelated page')
        html=(output/'index.html').read_text()
        self.assertEqual(html.count('<article class="'),1)
        self.assertIn('lead-story',html)
        self.assertEqual(NEXT_RE.findall(html),[])
        self.assertEqual(PREV_RE.findall(html),[])
        self.assertNotIn('<nav class="pager"',html)
        self.assertNotIn('/sivu/2/',html)

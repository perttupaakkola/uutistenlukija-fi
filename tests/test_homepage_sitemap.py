"""Sitemap discovery for the paginated homepage: /sivu/N/ is listed exactly while it is live.

Regression: the archive listing pages were rendered and linked from the pager, but the
sitemap never named them, so a crawler (or a reader tool that trusts the sitemap as the
discovery surface) could only reach page 2+ by following the pager. This test drives the
real public_bundle (real renderer, real release check) over a store whose extra jobs are
synthetic layout clones, and asserts the archive URLs, their canonical tags, and their
removal from both the sitemap and the output tree when a smaller release shrinks the
listing again.
"""
import hashlib,json,re,unittest
import xml.etree.ElementTree as ET
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
import test_release_v2 as base
from news_mvp.editorial import digest
from news_mvp.publish import public_bundle
from news_mvp.site import article_path
from news_mvp.store import database

SITE='https://uutistenlukija.fi'
NS='{http://www.sitemaps.org/schemas/sitemap/0.9}'
ARCHIVE_RE=re.compile(r'/sivu/(\d+)/')
CANON_RE=re.compile(r'<link rel="canonical" href="([^"]+)">')


class HomepageSitemap(unittest.TestCase):
    def test_archive_urls_follow_live_listing_pages(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        current=case.ready()
        state=case.state
        site=Path(state)/'live-site'
        # Every extra row below is a synthetic LAYOUT clone of the current job: the columns
        # carrying UNIQUE constraints (id, story_key, source_url) get unique synthetic values
        # and created_at moves progressively further back, while packet/draft/review bytes stay
        # exactly those of the current job. They are pagination filler, NOT independent captures;
        # only the real current job has a captured intake, and only that job is verified against
        # that intake (public_bundle -> verify_intake). The clones render as already-released
        # archive entries bound to their stored bytes, which is why no new ingest/parser fixture
        # (or intake directory) is needed for them.
        def clone(index):
            row=dict(current)
            row['id']=hashlib.sha256(('sitemap-layout-%d'%index).encode()).hexdigest()
            row['story_key']='synthetic:sitemap-layout:%d'%index
            row['source_url']='https://synthetic-layout.invalid/%d'%index
            row['created_at']=(datetime.fromisoformat(current['created_at'])-timedelta(minutes=index+1)).isoformat()
            return row
        eligible=[clone(index) for index in range(60)]
        undeployed=clone(60)
        rows=eligible+[undeployed]
        self.assertEqual(len({row['id'] for row in rows}),61)
        # Article slug identity is the job id prefix, so the clones must not collide there either.
        self.assertEqual(len({row['id'][:12] for row in rows}),61)
        columns=list(current.keys())
        with database(state) as store:
            self.assertEqual(columns,[column[1] for column in store.db.execute('PRAGMA table_info(jobs)')])
        insert_job='INSERT INTO jobs ('+','.join(columns)+') VALUES ('+','.join('?'*len(columns))+')'
        insert_release=("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) "
                        "VALUES(?,?,?,?,?,'deployed')")
        def add_jobs(added):
            # Every dictionary column is inserted by name through bound parameters.
            with database(state) as store:
                store.db.executemany(insert_job,[[row[column] for column in columns] for row in added]);store.db.commit()
        def deploy(released):
            # Digest of the decoded packet/draft, exactly as publish records a release; these
            # text-only releases carry no image (NULL), so their receipt binding is text.
            with database(state) as store:
                store.db.executemany(insert_release,
                    [(row['id'],digest(json.loads(row['packet'])),digest(json.loads(row['draft'])),None,base.COMMIT)
                     for row in released]);store.db.commit()
        def counts():
            with database(state) as store:
                return (store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],
                        store.db.execute('SELECT count(*) FROM publications').fetchone()[0])
        def check(expected_archives,eligible_count):
            with database(state) as store,patch('news_mvp.publish.cmd',return_value=base.COMMIT):
                bundle,receipt=public_bundle(store,current,state)
            self.assertEqual(bundle,site)
            urlset=ET.parse(site/'sitemap.xml').getroot()
            self.assertEqual(urlset.tag,NS+'urlset')
            locs=[url.find(NS+'loc').text for url in urlset.findall(NS+'url')]
            self.assertTrue(all(loc and loc.startswith(SITE+'/') for loc in locs))
            relative=[loc[len(SITE):] for loc in locs]
            archives=[path for path in relative if ARCHIVE_RE.fullmatch(path)]
            self.assertEqual(archives,expected_archives,'live archive pages, each once and in numeric order')
            self.assertEqual(archives,sorted(archives,key=lambda path:int(ARCHIVE_RE.fullmatch(path).group(1))))
            self.assertNotIn('/sivu/1/',relative,'page 1 is the homepage, never an archive')
            self.assertFalse((site/'sivu/1').exists())
            for archive in expected_archives:
                page=site/archive.strip('/')/'index.html'
                self.assertTrue(page.is_file(),archive)
                canonical=CANON_RE.search(page.read_text())
                self.assertIsNotNone(canonical,archive)
                self.assertEqual(canonical.group(1),SITE+archive)
            self.assertIn('/',relative);self.assertIn('/tietosuoja/',relative)
            article_urls=[path for path in relative if path.startswith('/uutiset/')]
            # Eligibility is deployment, not approval: the undeployed clone stays out while
            # every eligible article (and only those) is listed.
            self.assertEqual(len(article_urls),eligible_count)
            self.assertIn('/'+article_path(current),article_urls)
            self.assertNotIn('/'+article_path(undeployed),relative)
            self.assertIn('/'+receipt['new_article_files'][0][:-len('index.html')],article_urls)

        # Step 1: 32 jobs (current, 30 deployed clones, 1 undeployed clone) => 31 eligible, 2 pages.
        add_jobs(eligible[:30]+[undeployed]);deploy(eligible[:30])
        self.assertEqual(counts(),(32,30))
        check(['/sivu/2/'],31)
        # Step 2: add the remaining 30 deployed clones => 61 eligible, 3 pages. All 62 jobs stay.
        add_jobs(eligible[30:]);deploy(eligible[30:])
        self.assertEqual(counts(),(62,60))
        check(['/sivu/2/','/sivu/3/'],61)
        # Step 3: shrink to the current job alone by deleting the cloned publication rows only;
        # all 62 jobs stay, so eligibility - not job presence - drives listing and sitemap.
        with database(state) as store:
            store.db.executemany('DELETE FROM publications WHERE job_id=?',[(row['id'],) for row in eligible]);store.db.commit()
        self.assertEqual(counts(),(62,0))
        check([],1)
        for stale in (2,3):
            self.assertFalse((site/f'sivu/{stale}/index.html').exists())
            self.assertFalse((site/f'sivu/{stale}').exists())

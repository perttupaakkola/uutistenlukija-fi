"""`_redirects`: only eligible jobs, only real canonical targets inside the bundle.

Drives the real public_bundle (real renderer, real release check) over temporary
ReleaseV2 state and reads the actual published `_redirects`, so the assertions cover
the file a reader and a crawler would receive, not a fixture copy.

The bug this pins: the redirect loop walked every job that ever existed in the store,
so an unreviewed or retired job - which has no page in this release - got a 301 to a
missing file, and two blanket wildcards redirected retired monetization surfaces to the
front page instead of leaving them dead. A redirect may only exist when its target is a
real, non-symlink canonical index in this very bundle.
"""
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
import test_release_v2 as base
from cutover.check_release import check
from news_mvp.editorial import digest
from news_mvp.publish import public_bundle
from news_mvp.site import article_path
from news_mvp.store import database

UNREVIEWED='c'*64
RETIRED='d'*64


class BundleAliases(unittest.TestCase):
    def setUp(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        self.case=case
        self.current=case.ready()
        self.state=case.state
        self.site=Path(self.state)/'live-site'

    def bundle(self):
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=base.COMMIT):
            return public_bundle(store,self.current,self.state)

    def legacy_job(self,identifier,draft,status='approved',review=True):
        row=dict(self.current)
        row['id']=identifier
        row['story_key']='synthetic:bundle-aliases:'+identifier[:8]
        row['source_url']='https://synthetic-bundle-aliases.invalid/'+identifier[:8]
        row['draft']=json.dumps(draft,ensure_ascii=False)
        row['status']=status
        row['review']=self.current['review'] if review else None
        return row

    def insert(self,rows,deployed=()):
        columns=list(self.current.keys())
        with database(self.state) as store:
            store.db.executemany('INSERT INTO jobs ('+','.join(columns)+') VALUES ('+','.join('?'*len(columns))+')',
                                 [[row[column] for column in columns] for row in rows])
            store.db.executemany("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,NULL,?,'deployed')",
                                 [(row['id'],digest(json.loads(row['packet'])),digest(json.loads(row['draft'])),base.COMMIT) for row in rows if row['id'] in deployed])
            store.db.commit()

    def parsed(self):
        """id -> slug for every rule; refuses any other rule shape or surface."""
        found={}
        for line in (self.site/'_redirects').read_text().splitlines():
            if not line.strip():
                continue
            parts=line.split()
            self.assertEqual(len(parts),3,'unexpected rule shape: '+line)
            source,target,status=parts
            self.assertEqual(status,'301')
            self.assertTrue(source.startswith('/uutiset/') and source.endswith('/'),line)
            self.assertTrue(target.startswith('/uutiset/') and target.endswith('/'),line)
            self.assertNotIn('*',line)
            found[source.removeprefix('/uutiset/').removesuffix('/')]=target.removeprefix('/uutiset/').removesuffix('/')
        return found

    def assert_real_page(self,target):
        self.assertNotIn('/',target,'a rule target must be a single slug directory')
        index=self.site/Path('uutiset')/target/'index.html'
        ancestors=[self.site/Path(*Path('uutiset').parts[:1])/Path(*Path(target).parts[:n])
                   for n in range(1,len(Path(target).parts)+1)]
        ancestors.append(self.site/Path('uutiset'))
        self.assertTrue(all(not node.is_symlink() for node in ancestors),target)
        self.assertFalse(index.is_symlink())
        self.assertTrue(index.is_file(),'rule target missing from bundle: '+target)
        self.assertIn('rel="canonical"',index.read_text())

    def test_redirects_cover_only_eligible_jobs_with_real_bundle_targets(self):
        # Same reviewed draft as the current job, so the stored review still binds to it.
        legacy=self.legacy_job(RETIRED,self.case.draft)
        # An unreviewed job with a legacy hash id: never published, no page in this bundle.
        unreviewed=self.legacy_job(UNREVIEWED,self.case.draft,status='ready',review=False)
        self.insert([legacy,unreviewed],deployed={RETIRED})
        site,receipt=self.bundle()
        self.assertEqual(site,self.site)
        rules=self.parsed()
        # The unreviewed job is not eligible: its hash URL must not redirect anywhere.
        self.assertNotIn(UNREVIEWED,rules)
        expected=article_path(self.legacy_job(RETIRED,self.case.draft)).strip('/').removeprefix('uutiset/')
        self.assertEqual(rules.get(RETIRED),expected)
        current_slug=article_path(self.current).strip('/').removeprefix('uutiset/')
        self.assertEqual(rules.get(self.current['id']),current_slug)
        self.assertEqual(set(rules),{self.current['id'],RETIRED})
        # Every target must be a real, non-symlink canonical page in this bundle, and no
        # rule may point at another rule (a chain would be a second hop).
        self.assertNotIn(current_slug,rules)
        self.assertNotIn(expected,rules)
        for source,target in rules.items():
            self.assert_real_page(target)
        # Neither the retired monetization surfaces nor any wildcard/homepage fallback.
        text=(site/'_redirects').read_text()
        self.assertNotIn('*',text)
        self.assertNotIn('mainosta',text)
        self.assertNotIn('perustajakumppanuus',text)
        for source,target in rules.items():
            self.assertTrue(target and target!='/',target)
        # Preserved contract: slug redirect format and the hashed receipt both hold.
        self.assertEqual(receipt['files']['_redirects'],
                         hashlib.sha256((site/'_redirects').read_bytes()).hexdigest())
        self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_no_eligible_hash_url_removes_a_stale_redirects_file(self):
        # Every real job id is a digest, so today this release always owns at least the
        # current article's alias; the empty branch keeps a future id scheme (or a release
        # with no alias at all) from inheriting another release's wildcards.
        with patch('news_mvp.publish.slugs.is_legacy_hash_path',return_value=False):
            # A previous release left blanket rules behind; this release owns no rule.
            stale=self.site/'_redirects'
            stale.parent.mkdir(parents=True,exist_ok=True)
            stale.write_text('/mainosta/* / 301\n/perustajakumppanuus/* / 301\n')
            site,receipt=self.bundle()
        self.assertFalse(stale.exists(),'stale _redirects rules survived an empty rule set')
        self.assertNotIn('_redirects',receipt['files'])
        self.assertEqual(check(site,receipt),len(receipt['files']))


if __name__=='__main__':
    unittest.main()

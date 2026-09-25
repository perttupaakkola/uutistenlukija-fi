"""The public_bundle 404 body: real exits, no index claim, and a hashed receipt.

Drives the real public_bundle (real renderer, real release check) over temporary
ReleaseV2 state and reads the actual published 404.html, so the assertions cover
the file a reader would receive, not a fixture copy. The archive link appears only
when the bundle really contains /sivu/2/, judged by the same archive_pages scan the
sitemap uses; a symlinked archive page is not a real page.
"""
import hashlib,json,re,unittest
from pathlib import Path
from unittest.mock import patch
import test_release_v2 as base
from cutover.check_release import check
from news_mvp.editorial import digest
from news_mvp.publish import public_bundle
from news_mvp.store import database

GOOGLE='https://www.google.com/search'


class BundleMissingPage(unittest.TestCase):
    def setUp(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        self.case=case
        self.current=case.ready();case.packet=json.loads(self.current["packet"]);case.draft=json.loads(self.current["draft"])
        self.state=case.state
        self.site=Path(self.state)/'live-site'

    def bundle(self):
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=base.COMMIT):
            return public_bundle(store,self.current,self.state)

    def test_404_body_has_exits_noindex_and_a_hashed_receipt(self):
        site,receipt=self.bundle()
        self.assertEqual(site,self.site)
        body=(site/'404.html').read_text()
        self.assertIn('name="robots" content="noindex',body)
        self.assertNotIn('rel="canonical"',body)
        self.assertIn('action="'+GOOGLE+'"',body)
        self.assertIn('name="sitesearch" value="uutistenlukija.fi"',body)
        self.assertIn('Hae Googlesta',body)
        search_forms=re.findall(r'<form\b[^>]*role="search"[^>]*>(.*?)</form>',body,re.S)
        self.assertEqual(len(search_forms),2)
        form_ids=re.findall(r'<form\b[^>]*\bid="([^"]+)"[^>]*role="search"',body,re.S)
        self.assertEqual(form_ids,['header-search-form','missing-search-form'])
        input_ids=re.findall(r'<input\b(?=[^>]*\btype="search")[^>]*\bid="([^"]+)"',body,re.S)
        self.assertEqual(input_ids,['header-search-input','missing-search-input'])
        self.assertEqual(sorted(re.findall(r'<label\b[^>]*for="([^"]+)"',body)),
                         ['header-search-input','missing-search-input'])
        self.assertEqual(body.count('name="sitesearch" value="uutistenlukija.fi"'),2)
        self.assertIn('aria-describedby="header-search-note"',body)
        self.assertIn('aria-describedby="missing-search-note"',body)
        self.assertIn('Siirry uusimpiin uutisiin',body)
        self.assertIn('Tätä osoitetta ei löytynyt',body)
        # No archive 2 in this bundle, so the 404 falls back to the latest listing.
        self.assertNotIn('/sivu/2/',body)
        self.assertNotIn('Arkiston sivu',body)
        # The receipt covers the real bundle bytes, including the 404 body.
        sha=hashlib.sha256((site/'404.html').read_bytes()).hexdigest()
        self.assertEqual(receipt['files']['404.html'],sha)
        self.assertEqual(check(site,receipt),len(receipt['files']))
        (site/'404.html').write_text(body.replace('Siirry uusimpiin uutisiin','Siirry etusivulle'))
        with self.assertRaises(ValueError):check(site,receipt)

    def test_archive_two_link_only_when_the_bundle_really_has_that_page(self):
        self.bundle()
        self.assertNotIn('/sivu/2/',(self.site/'404.html').read_text())
        # 31 eligible jobs (current + 30 deployed synthetic layout clones) fill page 1 and
        # render the real /sivu/2/ listing, exactly as the paginated homepage does. The
        # clones are layout fillers bound to the current job's bytes; they are not
        # independent captures, so only the current job is verified against the intake.
        def clone(index):
            row=dict(self.current)
            row['id']=hashlib.sha256(('missing-page-layout-%d'%index).encode()).hexdigest()
            row['story_key']='synthetic:missing-page:%d'%index
            row['source_url']='https://synthetic-missing.invalid/%d'%index
            return row
        clones=[clone(index) for index in range(30)]
        columns=list(self.current.keys())
        with database(self.state) as store:
            store.db.executemany('INSERT INTO jobs ('+','.join(columns)+') VALUES ('+','.join('?'*len(columns))+')',
                                 [[row[column] for column in columns] for row in clones])
            store.db.executemany("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,'deployed')",
                                 [(row['id'],digest(json.loads(row['packet'])),digest(json.loads(row['draft'])),None,base.COMMIT) for row in clones])
            store.db.commit()
        site,receipt=self.bundle()
        self.assertTrue((site/'sivu/2/index.html').is_file())
        body=(site/'404.html').read_text()
        self.assertIn('href="/sivu/2/"',body)
        self.assertIn('Arkiston sivu 2',body)
        self.assertIn('Siirry uusimpiin uutisiin',body)
        self.assertIn('name="robots" content="noindex',body)
        self.assertNotIn('rel="canonical"',body)
        self.assertEqual(receipt['files']['404.html'],hashlib.sha256((site/'404.html').read_bytes()).hexdigest())
        self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_symlinked_archive_page_is_not_linked(self):
        self.bundle()
        archive=self.site/'sivu/2'
        archive.mkdir(parents=True)
        (archive/'index.html').symlink_to(self.site/'index.html')
        site,_=self.bundle()
        body=(site/'404.html').read_text()
        self.assertNotIn('/sivu/2/',body)
        self.assertNotIn('Arkiston sivu',body)
        self.assertIn('Siirry uusimpiin uutisiin',body)


if __name__=='__main__':
    unittest.main()

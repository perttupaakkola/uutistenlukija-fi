"""Reviewed legacy redirects reach the published `_redirects`: real bytes, fail closed.

The reviewed demand inventory (`news_mvp/legacy_redirects.json`) records 20 unmatched 404
paths and, today, no equivalence mappings. This suite drives the real public_bundle over
temporary ReleaseV2 state with a synthetic reviewed document injected at the loader
boundary, so it pins what the release path does with reviewed mappings: an exact
source -> canonical 301 inside the receipt-hashed `_redirects`, no rule (and no file) for
an unmatched inventory path, and a refused release - never a silently dropped mapping -
for anything unreviewed, ineligible, mis-canonical or colliding with a public page.

The committed inventory is never modified: unmatched rows must stay unmatched, so the
fixtures only ever add reviewed equivalents the planner has not actually approved.
"""
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
import test_release_v2 as base
from cutover.check_release import check
import news_mvp.publish as publish
from news_mvp.publish import public_bundle
from news_mvp.release_contract import (LEGACY_REDIRECTS,legacy_inventory,legacy_redirect_lines,
                                       load_legacy_redirects)
from news_mvp.site import article_path
from news_mvp.store import database

# A guide path with no page in the bundle. The old fixture used /oppaat/... and the
# renderer now writes a real /oppaat/ index, which makes any path under it public
# content the release refuses to redirect; the intended case here is the opposite (a
# reviewed mapping onto a path the bundle does not serve), so the source moves to a
# top-level guide tree no page occupies.
SOURCE='/aiemmat-oppaat/kauppojen-aukioloajat/'
FOREIGN='/uutiset/foreign-canonical-abcdef123456/'


def mapping(source=SOURCE,target=None,**overrides):
    record={'source':source,'target':target,'reviewed':True,
            'review':{'rationale':'Editorially confirmed equivalent successor.',
                      'evidence':['editorial review 2026-09-22']}}
    record.update(overrides)
    return record


class BundleLegacyRedirects(unittest.TestCase):
    def setUp(self):
        case=base.ReleaseV2('source_fetch');case.setUp();self.addCleanup(case.doCleanups)
        self.case=case
        self.current=case.ready()
        self.state=case.state
        self.root=case.root
        self.site=Path(self.state)/'live-site'

    def bundle(self):
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=base.COMMIT):
            return public_bundle(store,self.current,self.state)

    def canonical(self,row=None):
        return '/'+article_path(row or self.current)

    def document(self,mappings):
        """The committed inventory with synthetic reviewed mappings substituted in."""
        document=json.loads(LEGACY_REDIRECTS.read_text())
        document['mappings']=list(mappings)
        return document

    def reviewed(self,mappings):
        """A synthetic document validated by the real loader, ready to inject."""
        path=self.root/'synthetic-legacy-redirects.json'
        path.write_text(json.dumps(self.document(mappings)))
        return load_legacy_redirects(path)

    def loader(self,document):
        return patch('news_mvp.publish.load_legacy_redirects',return_value=document)

    def insert(self,rows,deployed=()):
        columns=list(self.current.keys())
        with database(self.state) as store:
            store.db.executemany('INSERT INTO jobs ('+','.join(columns)+') VALUES ('+','.join('?'*len(columns))+')',
                                 [[row[column] for column in columns] for row in rows])
            store.db.executemany("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,NULL,?,'deployed')",
                                 [(row['id'],base.digest(json.loads(row['packet'])),base.digest(json.loads(row['draft'])),base.COMMIT)
                                  for row in rows if row['id'] in deployed])
            store.db.commit()

    def clone(self,index):
        row=dict(self.current)
        row['id']=hashlib.sha256(('bundle-legacy-layout-%d'%index).encode()).hexdigest()
        row['story_key']='synthetic:bundle-legacy:%d'%index
        row['source_url']='https://synthetic-bundle-legacy.invalid/%d'%index
        return row

    def lines(self):
        return (self.site/'_redirects').read_text().splitlines()

    def test_reviewed_mapping_emits_exact_301_and_hashed_receipt(self):
        document=self.reviewed([mapping(target=self.canonical())])
        with self.loader(document):
            site,receipt=self.bundle()
        self.assertEqual(site,self.site)
        # The reviewed mapping and the current article's generated hash alias share one
        # deterministic, sorted rule set; nothing else is in the file.
        slug=self.canonical()
        alias='/uutiset/'+self.current['id']+'/'
        expected=sorted([f'{SOURCE} {slug} 301',f'{alias} {slug} 301'])
        self.assertEqual(self.lines(),expected)
        text=(self.site/'_redirects').read_text()
        self.assertEqual(text,'\n'.join(expected)+'\n')
        self.assertNotIn('*',text)
        self.assertNotIn(' / 301',text)
        # The receipt binds the exact published redirect bytes, and the release check agrees.
        self.assertEqual(receipt['files']['_redirects'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(check(site,receipt),len(receipt['files']))
        # The legacy source is a redirect, never a page this bundle serves.
        self.assertFalse((self.site/'aiemmat-oppaat/kauppojen-aukioloajat/index.html').exists())
        self.assertNotIn('aiemmat-oppaat/kauppojen-aukioloajat/index.html',receipt['files'])

    def test_unmatched_reviewed_inventory_stays_dead_with_helpful_404(self):
        # The committed document: 20 measured 404 paths, no reviewed equivalent. No fixture
        # may invent one, so none of them may appear as a rule or as a file.
        inventory=legacy_inventory(load_legacy_redirects())
        self.assertEqual(inventory['rows'],20)
        self.assertEqual(inventory['mapped'],[])
        site,receipt=self.bundle()
        text=(site/'_redirects').read_text()
        for path in inventory['paths']:
            with self.subTest(path=path):
                self.assertNotIn(path,text)
                self.assertNotIn(path.strip('/')+'/index.html',receipt['files'])
        self.assertEqual(self.lines(),[f'/uutiset/{self.current["id"]}/ {self.canonical()} 301'])
        # The dead paths stay dead but a reader still gets exits: noindex, no canonical
        # claim, the newest listing and a site-scoped search.
        body=(site/'404.html').read_text()
        self.assertIn('name="robots" content="noindex',body)
        self.assertNotIn('rel="canonical"',body)
        self.assertIn('href="/"',body)
        self.assertIn('action="https://www.google.com/search"',body)
        self.assertIn('Tätä osoitetta ei löytynyt',body)
        self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_unreviewed_and_unknown_target_mappings_fail_the_release(self):
        unknown=self.reviewed([mapping(target='/uutiset/ei-julkaistu-abcdef123456/')])
        with self.loader(unknown),self.assertRaises(ValueError):
            self.bundle()
        self.assertFalse((self.state/'release.json').exists(),'a refused mapping must not produce a receipt')
        # An unreviewed mapping is refused by the loader boundary and, even if a caller
        # bypassed it, by the union validator the release path itself runs.
        raw=json.loads(LEGACY_REDIRECTS.read_text())
        raw['mappings']=[mapping(target=self.canonical(),reviewed=False)]
        path=self.root/'unreviewed-legacy-redirects.json'
        path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            load_legacy_redirects(path)
        with self.loader(raw),self.assertRaises(ValueError):
            self.bundle()
        self.assertFalse((self.state/'release.json').exists())
        # A homepage/wildcard replacement target can never be a reviewed canonical.
        # These shapes are refused by the real loader already, and the release path
        # refuses them again through the union validator.
        for target in ['/','/uutiset/','https://evil.example/uutiset/x-abcdef123456/']:
            with self.subTest(target=target),self.assertRaises(ValueError):
                self.reviewed([mapping(target=target)])
            with self.subTest(target=target,stage='bundle'),self.loader(self.document([mapping(target=target)])),self.assertRaises(ValueError):
                self.bundle()

    def test_missing_multiple_and_foreign_canonical_exclude_a_target(self):
        # The real renderer writes the page, then the canonical is damaged: a page that
        # does not name exactly its own URL is not a working redirect target and must not
        # be named by any rule, and a reviewed mapping onto it must fail the release.
        link='<link rel="canonical" href="https://uutistenlukija.fi'+self.canonical()+'">'
        variants={
            'missing': lambda html: html.replace(link,''),
            'multiple': lambda html: html.replace(link,link+link),
            'foreign': lambda html: html.replace(link,'<link rel="canonical" href="'+FOREIGN+'">'),
        }
        real=publish.render_site
        for name,damage in variants.items():
            def tampered(store,output_dir,state_dir=None,**kwargs):
                real(store,output_dir,state_dir=state_dir,**kwargs)
                index=Path(output_dir)/article_path(self.current)/'index.html'
                html=index.read_text()
                self.assertIn(link,html)
                index.write_text(damage(html))
            with self.subTest(canonical=name),patch('news_mvp.publish.render_site',side_effect=tampered):
                site,receipt=self.bundle()
                self.assertFalse((site/'_redirects').exists(),name+': a non-canonical page must not get a 301')
                self.assertNotIn('_redirects',receipt['files'])
                self.assertEqual(check(site,receipt),len(receipt['files']))
                with self.loader(self.reviewed([mapping(target=self.canonical())])),self.assertRaises(ValueError):
                    self.bundle()

    def test_duplicate_attribute_canonical_invalidates_the_target(self):
        # The renderer writes a valid page; a second canonical link whose attributes are
        # duplicated then makes the markup ambiguous. Such a link must invalidate the
        # target rather than being discarded behind the first, valid canonical - including
        # when it is `rel` that is duplicated, so a last-value-wins attribute map cannot
        # disguise the canonical claim. An explicit reviewed mapping onto that page fails
        # the release, and the page gets no rule of its own.
        link='<link rel="canonical" href="https://uutistenlukija.fi'+self.canonical()+'">'
        variants={
            'duplicate-href': '<link rel="canonical" href="x" href="y">',
            'duplicate-rel': '<link rel="canonical" rel="alternate" href="x">',
            'duplicate-rel-hidden': '<link rel="alternate" rel="canonical" href="x">',
        }
        real=publish.render_site
        for name,extra in variants.items():
            def tampered(store,output_dir,state_dir=None,**kwargs):
                real(store,output_dir,state_dir=state_dir,**kwargs)
                index=Path(output_dir)/article_path(self.current)/'index.html'
                html=index.read_text()
                self.assertIn(link,html)
                index.write_text(html.replace(link,link+extra))
            with self.subTest(duplicate=name),patch('news_mvp.publish.render_site',side_effect=tampered):
                receipt_path=self.state/'release.json'
                before=receipt_path.read_bytes() if receipt_path.exists() else None
                with self.loader(self.reviewed([mapping(target=self.canonical())])),self.assertRaises(ValueError):
                    self.bundle()
                after=receipt_path.read_bytes() if receipt_path.exists() else None
                self.assertEqual(after,before,name+': a refused mapping must not publish a receipt')
                site,receipt=self.bundle()
                self.assertFalse((site/'_redirects').exists(),name+': an ambiguous canonical must not get a 301')
                self.assertNotIn('_redirects',receipt['files'])
                self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_symlinked_article_target_is_not_eligible(self):
        # A link planted at the article's slug directory makes the page resolve outside the
        # real bundle root. It is not a published page this release wrote, so it gets no
        # rule, and a reviewed mapping onto it fails the release instead of being dropped.
        real=publish.render_site
        outside=self.root/'outside-bundle'
        def linked(store,output_dir,state_dir=None,**kwargs):
            real(store,output_dir,state_dir=state_dir,**kwargs)
            directory=Path(output_dir)/article_path(self.current)
            if directory.is_symlink():
                return  # already tampered by an earlier bundle() in this test
            outside.mkdir(parents=True,exist_ok=True)
            (outside/'index.html').write_bytes((directory/'index.html').read_bytes())
            (directory/'index.html').unlink()
            directory.rmdir()
            directory.symlink_to(outside)
        with patch('news_mvp.publish.render_site',side_effect=linked):
            site,receipt=self.bundle()
            self.assertTrue((site/article_path(self.current)).is_symlink())
            # No eligible page wrote a rule, so no `_redirects` exists at all.
            self.assertFalse((site/'_redirects').exists(),'a symlinked page must not be a redirect target')
            self.assertNotIn('_redirects',receipt['files'])
            self.assertEqual(check(site,receipt),len(receipt['files']))
            with self.loader(self.reviewed([mapping(target=self.canonical())])),self.assertRaises(ValueError):
                self.bundle()

    def test_public_source_collisions_are_refused(self):
        # 31 eligible articles render the real /sivu/2/ listing, so archive paths exist.
        clones=[self.clone(index) for index in range(30)]
        self.insert(clones,deployed={row['id'] for row in clones})
        article=article_path(clones[0])
        self.assertNotEqual('/'+article,self.canonical())
        collisions=['/tietosuoja/','/kuvituskuvat/','/sivu/2/','/sivu/','/uutiset/','/'+article,
                    '/mvp-assets/','/404.html/','/oppaat/','/oppaat/kauppojen-aukioloajat/']
        for source in collisions:
            with self.subTest(source=source),self.loader(self.reviewed([mapping(source=source,target=self.canonical())])),self.assertRaises(ValueError):
                self.bundle()
            self.assertFalse((self.state/'release.json').exists())
        # The same bundle without a colliding mapping publishes normally.
        site,receipt=self.bundle()
        self.assertTrue((site/'sivu/2/index.html').is_file())
        self.assertTrue((site/'tietosuoja/index.html').is_file())
        self.assertTrue((site/'kuvituskuvat/index.html').is_file())
        self.assertTrue((site/article/'index.html').is_file())
        self.assertTrue((site/self.canonical().strip('/')/'index.html').is_file())
        self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_generated_hash_alias_survives_alias_content_at_its_legacy_path(self):
        # render_site may intentionally write content at the legacy hash path itself. The
        # generated alias is this article's own old URL and its target is the canonical page
        # this same render wrote for that same id, so the alias must survive - unlike a
        # reviewed mapping, which would be refused for taking over public content.
        alias='/uutiset/'+self.current['id']+'/'
        real=publish.render_site
        def with_alias_page(store,output_dir,state_dir=None,**kwargs):
            real(store,output_dir,state_dir=state_dir,**kwargs)
            page=Path(output_dir)/article_path(self.current)/'index.html'
            target=Path(output_dir)/alias.strip('/')/'index.html'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(page.read_bytes())
        with patch('news_mvp.publish.render_site',side_effect=with_alias_page):
            site,receipt=self.bundle()
        self.assertTrue((site/alias.strip('/')/'index.html').is_file())
        self.assertIn(alias.strip('/')+'/index.html',receipt['files'])
        self.assertIn(f'{alias} {self.canonical()} 301',self.lines())
        self.assertEqual(check(site,receipt),len(receipt['files']))
        # The same source as a reviewed mapping collides with that alias page and is refused.
        with patch('news_mvp.publish.render_site',side_effect=with_alias_page),\
             self.loader(self.document([mapping(source=alias,target=self.canonical())])),self.assertRaises(ValueError):
            self.bundle()

    def test_empty_combined_rules_removes_a_stale_redirects_file(self):
        # No reviewed mappings and no generated alias in this release: the combination is
        # empty, so the file must be absent rather than inherit another release's rules.
        stale=self.site/'_redirects'
        stale.parent.mkdir(parents=True,exist_ok=True)
        stale.write_text('/mainosta/* / 301\n/perustajakumppanuus/* / 301\n')
        with patch('news_mvp.publish.slugs.is_legacy_hash_path',return_value=False):
            site,receipt=self.bundle()
        self.assertFalse(stale.exists(),'stale wildcard rules survived an empty rule set')
        self.assertNotIn('_redirects',receipt['files'])
        self.assertEqual(check(site,receipt),len(receipt['files']))

    def test_alias_union_refuses_duplicate_chain_and_loop(self):
        slug=self.canonical()
        alias='/uutiset/'+self.current['id']+'/'
        # A reviewed mapping may not reuse the generated hash alias as its source: the
        # union validator refuses the duplicate the generated rule already owns.
        with self.loader(self.document([mapping(source=alias,target=slug)])),self.assertRaises(ValueError):
            self.bundle()
        self.assertFalse((self.state/'release.json').exists())
        # A self-redirect is a one-hop loop and is refused by the release path itself.
        with self.loader(self.document([mapping(source='/oppaat/loop/',target='/oppaat/loop/')])),self.assertRaises(ValueError):
            self.bundle()
        # A reviewed mapping onto the hash path is a chain to the generated alias's target
        # and is refused: the hash path is not a canonical page this render wrote.
        with self.loader(self.reviewed([mapping(source='/oppaat/ketju/',target=alias)])),self.assertRaises(ValueError):
            self.bundle()
        self.assertFalse((self.state/'release.json').exists())
        # The union validator the release path calls refuses duplicate, chain and loop
        # shapes among the exact rule pairs publish builds (generated aliases included).
        eligible=[slug,'/uutiset/muu-juttu-abcdef123456/']
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping(source=alias,target=slug)],eligible,[(alias,slug)])
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping(source='/oppaat/a/',target='/uutiset/muu-juttu-abcdef123456/'),
                                   mapping(source='/oppaat/b/',target='/oppaat/a/')],eligible)
        with self.assertRaises(ValueError):
            legacy_redirect_lines([mapping(source='/uutiset/muu-juttu-abcdef123456/',target=slug)],eligible,
                                  [('/uutiset/'+'e'*64+'/','/uutiset/muu-juttu-abcdef123456/')])
        # A refused release leaves the previous bundle alone; the next valid one still
        # writes exactly the generated alias, and the receipt hash still binds it.
        site,receipt=self.bundle()
        self.assertEqual(self.lines(),[f'{alias} {slug} 301'])
        self.assertEqual(receipt['files']['_redirects'],
                         hashlib.sha256((site/'_redirects').read_bytes()).hexdigest())
        self.assertEqual(check(site,receipt),len(receipt['files']))


if __name__=='__main__':
    unittest.main()

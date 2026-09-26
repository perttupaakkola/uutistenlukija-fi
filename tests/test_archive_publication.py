"""A historical failed dispatch is recoverable only as a proved live article."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from news_mvp import backfill
from news_mvp.editorial import digest, encode
from news_mvp.publish import public_bundle
from news_mvp.store import database
import test_archive_batch as batch


class CanonicalArchiveRecovery(unittest.TestCase):
    def setUp(self):
        self.fixture = batch.ArchiveBatch('test_one_anchor_exact_release_history_and_live_readback')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.entries = copy.deepcopy(f.entries)
        self.failed = self.entries[0]['job_id']
        self.anchor = self.entries[1]['job_id']
        with database(f.c.state) as store:
            for entry in self.entries:
                image = entry['draft']['image']
                target = f.c.state/image['local_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((f.prepared/image['local_path']).read_bytes())
                store.db.execute('UPDATE jobs SET packet=?,draft=?,review=? WHERE id=?',
                    (encode(entry['packet']), encode(entry['draft']), encode(entry['review']), entry['job_id']))
                store.db.execute('UPDATE publications SET packet_sha=?,draft_sha=?,image_sha=? WHERE job_id=?',
                    (digest(entry['packet']),digest(entry['draft']),image['sha256'],entry['job_id']))
                entry['previous_packet_sha'] = digest(entry['packet'])
                entry['previous_draft_sha'] = digest(entry['draft'])
            store.db.execute('UPDATE publications SET source_commit=?,remote_commit=?,run_id=? WHERE job_id=?',
                ('c'*40,'b'*40,201,self.anchor))
            store.db.commit()
            with patch('news_mvp.publish.cmd', return_value='c'*40):
                self.root, release = public_bundle(store,store.get(self.anchor),f.c.state)
            store.db.execute("UPDATE publications SET status='failed',error='Historical deploy failure' WHERE job_id=?",(self.failed,))
            store.db.commit()
            self.before = {r['job_id']:dict(r) for r in store.db.execute('SELECT * FROM publications')}
        raw = encode(release).encode()
        pages = {k:release[k] for k in ('source_commit','job_id','packet_sha256','draft_sha256','image_sha256',
            'text_only','text_provenance','image_backfill_sha256') if k in release}
        pages.update(remote_commit='b'*40,canonical_origin='https://uutistenlukija.fi',deployment_id='exact-pages-id')
        self.evidence = {'release_bytes':raw,'release_sha256':hashlib.sha256(raw).hexdigest(),
            'pages':pages,'workflow':{'status':'completed','conclusion':'success','event':'workflow_dispatch',
                'headSha':'b'*40,'databaseId':201}}
        self.live = lambda url:(self.root/url.removeprefix('https://uutistenlukija.fi/')).joinpath('index.html').read_bytes() if url.endswith('/') else (self.root/url.removeprefix('https://uutistenlukija.fi/')).read_bytes()

    def install(self, store, evidence=None, live=None):
        f = self.fixture
        return backfill.install(store,self.entries,f.prepared,f.c.state,'d'*40,
            archive_evidence=evidence or self.evidence,live_read=live or self.live)

    def test_exact_current_release_recovers_failed_history_without_replaying_it(self):
        with database(self.fixture.c.state) as store:
            anchor = self.install(store)
            records = backfill.members(store,anchor)
            recovered = next(r for r in records if r['job_id']==self.failed)
            self.assertEqual(recovered['previous_publication'],self.before[self.failed])
            self.assertEqual(recovered['previous_publication']['status'],'failed')
            self.assertEqual(recovered['canonical_archive_recovery']['run_id'],201)
            self.assertEqual(len(backfill.pending(store)),1)

    def test_failed_record_without_proof_stays_failed(self):
        f = self.fixture
        with database(f.c.state) as store:
            with self.assertRaisesRegex(ValueError,'current canonical deployment proof'):
                backfill.install(store,self.entries,f.prepared,f.c.state,'d'*40)
            self.assertEqual(dict(store.db.execute('SELECT * FROM publications WHERE job_id=?',(self.failed,)).fetchone()),self.before[self.failed])

    def test_hash_canonical_pages_and_ambiguous_identity_refuse_before_mutation(self):
        for kind in ('live','manifest','pages','run','canonical','ambiguous','missing_asset','text'):
            with self.subTest(kind=kind),database(self.fixture.c.state) as store:
                evidence=copy.deepcopy(self.evidence)
                live=self.live
                if kind=='live':live=lambda url:b'not the deployed bytes'
                if kind=='manifest':evidence['release_sha256']='f'*64
                if kind=='pages':evidence['pages']['draft_sha256']='f'*64
                if kind=='run':evidence['workflow']['conclusion']='failure'
                if kind=='ambiguous':
                    store.db.execute('UPDATE publications SET remote_commit=? WHERE job_id=?',('b'*40,self.failed));store.db.commit()
                if kind in ('canonical','missing_asset','text'):
                    release=json.loads(evidence['release_bytes'])
                    job=store.get(self.failed)
                    from news_mvp.site import article_path
                    path=article_path(job)+'index.html'
                    if kind=='missing_asset':
                        del release['files']['mvp-assets/'+self.entries[0]['draft']['image']['sha256']+'.jpg']
                    else:
                        original=(self.root/path).read_bytes()
                        if kind=='canonical':changed=original.replace(b'rel="canonical"',b'rel="alternate"')
                        else:changed=original.replace(self.entries[0]['draft']['title'].encode(),b'Changed title')
                        release['files'][path]=hashlib.sha256(changed).hexdigest()
                        live=lambda url,changed=changed,path=path:changed if url.endswith(path.removesuffix('index.html')) else self.live(url)
                    raw=encode(release).encode();evidence.update(release_bytes=raw,release_sha256=hashlib.sha256(raw).hexdigest())
                with self.assertRaises(ValueError):self.install(store,evidence,live)
                if kind=='ambiguous':
                    store.db.execute('UPDATE publications SET remote_commit=? WHERE job_id=?',(self.before[self.failed]['remote_commit'],self.failed));store.db.commit()
                self.assertEqual({r['job_id']:dict(r) for r in store.db.execute('SELECT * FROM publications')},self.before)

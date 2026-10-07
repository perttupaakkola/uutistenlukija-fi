"""Synthetic read-only identity checks; all provider boundaries stay uncalled."""
import dataclasses
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from news_mvp.amendments import AmendmentEvidence, CaptureBinding, _digest
from news_mvp.amendment_image_identity import retained_image_identity


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,packet TEXT,draft TEXT,status TEXT,created_at TEXT)')
        self.db.execute('CREATE TABLE publications(job_id TEXT PRIMARY KEY,packet_sha TEXT NOT NULL,draft_sha TEXT NOT NULL,image_sha TEXT,source_commit TEXT NOT NULL,remote_commit TEXT,run_id INTEGER,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT)')
        self.target = '1'*64
        self.image = {'sha256':'2'*64,'local_path':'media/synthetic.jpg','pixel_review':{'image_sha256':'2'*64}}
        self.draft = {'title':'Synthetic original','image':self.image}
        packet = {'story_key':'official:synthetic'}
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(self.target,json.dumps(packet),json.dumps(self.draft),'rendered','2026-09-21T14:00:00Z'))
        self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?)',(self.target,_digest(packet),_digest(self.draft),'2'*64,'synthetic','synthetic',1,'deployed',0,None))
        cur = self.db.execute('SELECT * FROM publications')
        pub = dict(zip([c[0] for c in cur.description],cur.fetchone()))
        self.evidence = AmendmentEvidence('published-amendment-preparation-v1', self.target,_digest(packet),_digest(self.draft),_digest(pub),CaptureBinding('3'*64,'4'*64),CaptureBinding('5'*64,'6'*64),'Synthetic schedule update','2026-10-06T17:00:00Z')
        self.db.commit()
        self.db.execute('BEGIN')

    def check(self, evidence=None, image=None):
        before = list(self.db.iterdump()); changes = self.db.total_changes
        try:
            return retained_image_identity(self.db,evidence or self.evidence,image if image is not None else self.image,self.state)
        finally:
            self.assertEqual(before,list(self.db.iterdump()))
            self.assertEqual(changes,self.db.total_changes)

    def other(self, draft, owner='7'*64):
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(owner,'{}',json.dumps(draft),'rejected','synthetic'))

    def test_same_job_and_all_flags_false(self):
        result = self.check()
        self.assertEqual(result['image_sha256'],'2'*64)
        for key in ('normal_approval','fresh_pixel_approval','activation','release_authorization'):
            self.assertIs(result[key],False)

    def test_other_job_identical_text_is_excluded(self):
        self.other(self.draft)
        with self.assertRaises(ValueError): self.check()

    def test_other_image_retained_in_exclusion_set(self):
        self.other({'image':{'sha256':'8'*64}})
        self.assertEqual(self.check()['excluded_image_sha256'],['8'*64])

    def test_rejected_retained_pixels_refused(self):
        directory=self.state/'image-rejections'/'synthetic';directory.mkdir(parents=True)
        (directory/'reject.json').write_text(json.dumps({'review':{'approved':False,'image_retryable':True},'draft':{'image':self.image}}))
        with self.assertRaises(ValueError): self.check()

    def test_changed_predecessor_and_changed_image_refused(self):
        with self.assertRaises(ValueError): self.check(evidence=dataclasses.replace(self.evidence,predecessor_draft_sha256='9'*64))
        with self.assertRaises(ValueError): self.check(image={**self.image,'local_path':'media/different.jpg'})

    def test_malformed_other_draft_and_hash_conflict_refused(self):
        self.other({'image':{'sha256':'8'*64,'pixel_review':{'image_sha256':'9'*64}}})
        with self.assertRaises(ValueError): self.check()
        self.db.execute("UPDATE jobs SET draft='[]' WHERE id=?",('7'*64,))
        with self.assertRaises(ValueError): self.check()

    def test_unknown_job_schema_refused(self):
        self.db.execute('ALTER TABLE jobs RENAME TO old_jobs')
        self.db.execute('CREATE TABLE jobs(id TEXT,packet TEXT,draft TEXT,status TEXT,created_at TEXT)')
        self.db.execute('INSERT INTO jobs SELECT * FROM old_jobs')
        with self.assertRaises(ValueError): self.check()

    def test_composite_key_null_draft_sibling_refused(self):
        self.db.execute('ALTER TABLE jobs RENAME TO old_jobs')
        self.db.execute('CREATE TABLE jobs(id TEXT,packet TEXT,draft TEXT,status TEXT,created_at TEXT,PRIMARY KEY(id,packet))')
        self.db.execute('INSERT INTO jobs SELECT * FROM old_jobs')
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(self.target,'~sibling',None,'rendered','2026-09-21T14:00:00Z'))
        with self.assertRaises(ValueError): self.check()

    def test_pixel_hash_only_hotlink_excluded(self):
        self.other({'image':{'hotlink':True,'generated':False,'url':'https://example.org/photo','pixel_review':{'image_sha256':'8'*64}}})
        self.assertEqual(self.check()['excluded_image_sha256'],['8'*64])

    def test_unhashed_historical_hotlink_gap_is_explicit(self):
        self.other({'image':{'hotlink':True,'generated':False,'url':'https://example.org/photo'}})
        result=self.check()
        self.assertEqual(result['unhashed_historical_hotlink_count'],1)
        self.assertIs(result['exhaustive_cross_image_byte_comparison'],False)

    def test_unhashed_same_source_and_unknown_local_refused(self):
        self.image['source_url']='https://example.org/retained'
        # Keep predecessor/evidence immutable: test helper image parsing separately.
        from news_mvp.amendment_image_identity import _image_sha
        with self.assertRaises(ValueError): _image_sha({'local_path':'media/nohash.jpg'})
        self.image.pop('source_url')
        self.db.execute('UPDATE jobs SET draft=? WHERE id=?',(json.dumps({**self.draft,'image':{**self.image,'url':'https://example.org/retained'}}),self.target))
        self.draft['image']={**self.image,'url':'https://example.org/retained'}
        self.image=self.draft['image']
        cur=self.db.execute('SELECT * FROM publications');pub=dict(zip([c[0] for c in cur.description],cur.fetchone()))
        pub['draft_sha']=_digest(self.draft)
        self.db.execute('UPDATE publications SET draft_sha=?', (pub['draft_sha'],))
        self.evidence=dataclasses.replace(self.evidence,predecessor_draft_sha256=pub['draft_sha'],predecessor_publication_sha256=_digest(pub))
        self.other({'image':{'hotlink':True,'generated':False,'url':'https://example.org/retained'}})
        with self.assertRaises(ValueError): self.check()

    def test_read_transaction_required(self):
        self.db.rollback()
        with self.assertRaises(ValueError): self.check()


if __name__ == '__main__': unittest.main()

"""Synthetic, secret-free tests for non-activating amendment preflight."""
import dataclasses
import hashlib
import json
import sqlite3
import unittest
from news_mvp.amendments import AmendmentEvidence, CaptureBinding, predecessor_snapshot, _digest


class AmendmentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,packet TEXT,draft TEXT,status TEXT,created_at TEXT)')
        self.db.execute('CREATE TABLE publications(job_id TEXT PRIMARY KEY,packet_sha TEXT NOT NULL,draft_sha TEXT NOT NULL,image_sha TEXT,source_commit TEXT NOT NULL,remote_commit TEXT,run_id INTEGER,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,error TEXT)')
        self.identifier = '1'*64
        packet, draft = {'story_key':'official:synthetic'}, {'title':'Synthetic unchanged title'}
        self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', (self.identifier,json.dumps(packet),json.dumps(draft),'rendered','2026-09-21T14:00:00+00:00'))
        self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?)', (self.identifier,_digest(packet),_digest(draft),'2'*64,'synthetic','synthetic',1,'deployed',0,None))
        publication = dict(zip(('job_id','packet_sha','draft_sha','image_sha','source_commit','remote_commit','run_id','status','attempts','error'),self.db.execute('SELECT * FROM publications').fetchone()))
        self.evidence = AmendmentEvidence('published-amendment-preparation-v1', self.identifier,_digest(packet),_digest(draft),_digest(publication),CaptureBinding('3'*64,'4'*64),CaptureBinding('5'*64,'6'*64),'Synthetic updated schedule','2026-10-06T17:00:00+00:00')
        self.db.commit()

    def refuse_without_writes(self, evidence=None):
        before = list(self.db.iterdump())
        changes = self.db.total_changes
        with self.assertRaises(ValueError):
            predecessor_snapshot(self.db, evidence or self.evidence)
        self.assertEqual(before,list(self.db.iterdump()))
        self.assertEqual(changes,self.db.total_changes)

    def test_correct_predecessor_read_only(self):
        before = list(self.db.iterdump())
        result = predecessor_snapshot(self.db,self.evidence)
        self.assertEqual('deployed',result['publication']['status'])
        self.assertEqual(before,list(self.db.iterdump()))

    def test_typed_immutable_identity(self):
        with self.assertRaises(dataclasses.FrozenInstanceError): self.evidence.reason='changed'
        for mutation in ({'job_id':'A'*64},{'schema':'v3'}, {'updated_at':'2026-10-06T17:00:00'}, {'original_capture':{}}, {'update_capture':self.evidence.original_capture}, {'reason':''}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                dataclasses.replace(self.evidence,**mutation)
        self.refuse_without_writes({'job_id':self.identifier})

    def test_capture_bytes_are_bound_but_not_approval(self):
        binding = CaptureBinding(hashlib.sha256(b'packet').hexdigest(),hashlib.sha256(b'receipt').hexdigest())
        self.assertIsNone(binding.verify_bytes(b'packet',b'receipt'))
        for packet,receipt in ((b'changed',b'receipt'),(b'packet',b'changed'),('packet',b'receipt')):
            with self.assertRaises(ValueError): binding.verify_bytes(packet,receipt)

    def test_unknown_or_missing_schema(self):
        self.db.execute('ALTER TABLE publications ADD COLUMN unexpected TEXT')
        self.refuse_without_writes()
        self.db.execute('DROP TABLE publications')
        self.refuse_without_writes()

    def test_pending_and_active_archive_refusal(self):
        self.db.execute("UPDATE publications SET status='dispatched'")
        self.refuse_without_writes()
        self.db.execute("UPDATE publications SET status='deployed'")
        self.db.execute('CREATE TABLE image_backfill_batches(status TEXT)')
        self.db.execute("INSERT INTO image_backfill_batches VALUES('active')")
        self.refuse_without_writes()

    def test_unknown_archive_schema(self):
        self.db.execute('CREATE TABLE image_backfill_batches(unexpected TEXT)')
        self.refuse_without_writes()

    def test_moved_predecessor_and_undeployed_refusal(self):
        for field in ('predecessor_packet_sha256','predecessor_draft_sha256','predecessor_publication_sha256','job_id'):
            with self.subTest(field=field): self.refuse_without_writes(dataclasses.replace(self.evidence,**{field:'9'*64}))
        self.db.execute("UPDATE jobs SET status='rejected'")
        self.refuse_without_writes()
        self.db.execute("UPDATE jobs SET status='rendered'")
        self.db.execute("UPDATE publications SET status='failed'")
        self.refuse_without_writes()

    def test_schema_constraints_and_ambiguous_rows_refused(self):
        self.db.execute('ALTER TABLE publications RENAME TO old_publications')
        self.db.execute('CREATE TABLE publications(job_id TEXT,packet_sha TEXT,draft_sha TEXT,image_sha TEXT,source_commit TEXT,remote_commit TEXT,run_id INTEGER,status TEXT,attempts INTEGER,error TEXT)')
        self.db.execute('INSERT INTO publications SELECT * FROM old_publications')
        self.db.execute('INSERT INTO publications SELECT * FROM old_publications')
        self.refuse_without_writes()
        self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?)', ('9'*64,'2'*64,'3'*64,None,'synthetic',None,None,None,0,None))
        self.refuse_without_writes()

    def test_canonical_archive_terminal_only(self):
        self.db.execute('CREATE TABLE image_backfill_batches(batch_id TEXT PRIMARY KEY,anchor_job_id TEXT NOT NULL,source_commit TEXT NOT NULL,records TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,remote_commit TEXT,run_id INTEGER)')
        self.db.execute('INSERT INTO image_backfill_batches VALUES(?,?,?,?,?,?,?,?)', ('batch',self.identifier,'synthetic','[]','deployed','synthetic',None,None))
        predecessor_snapshot(self.db,self.evidence)
        for status in ('active','failed','unknown-owner-state'):
            self.db.execute('UPDATE image_backfill_batches SET status=?',(status,))
            self.refuse_without_writes()

    def test_corrupted_null_status_refused(self):
        # In-memory corruption reproduces SQLite's NOT NULL IS NULL optimization.
        self.db.execute('CREATE TABLE image_backfill_batches(batch_id TEXT PRIMARY KEY,anchor_job_id TEXT NOT NULL,source_commit TEXT NOT NULL,records TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,remote_commit TEXT,run_id INTEGER)')
        for table in ('publications', 'image_backfill_batches'):
            original = self.db.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
            self.db.execute('PRAGMA writable_schema=ON')
            self.db.execute('UPDATE sqlite_master SET sql=? WHERE name=?',(original.replace('status TEXT NOT NULL','status TEXT'),table))
            self.db.execute('PRAGMA writable_schema=RESET')
            if table == 'publications':
                self.db.execute('INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?)',('9'*64,'2'*64,'3'*64,None,'synthetic',None,None,None,0,None))
            else:
                self.db.execute('INSERT INTO image_backfill_batches VALUES(?,?,?,?,?,?,?,?)',('bad',self.identifier,'synthetic','[]',None,'synthetic',None,None))
            self.db.execute('PRAGMA writable_schema=ON')
            self.db.execute('UPDATE sqlite_master SET sql=? WHERE name=?',(original,table))
            self.db.execute('PRAGMA writable_schema=RESET')
            self.assertEqual(1,next(r[3] for r in self.db.execute('PRAGMA table_info('+table+')') if r[1]=='status'))
            self.refuse_without_writes()
            self.db.execute('DELETE FROM '+table+" WHERE typeof(status)='null'")

    def test_update_must_follow_publication(self):
        self.refuse_without_writes(dataclasses.replace(self.evidence,updated_at='2026-09-20T14:00:00Z'))


if __name__ == '__main__': unittest.main()

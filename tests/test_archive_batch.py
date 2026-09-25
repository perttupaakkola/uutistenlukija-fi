"""One archive correction release retains history and refuses partial/mismatched evidence."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from news_mvp import backfill, official
from news_mvp.editorial import digest, encode
from news_mvp.publish import public_bundle
from news_mvp.store import database
from image_helpers import approved_pixel_review
import test_generated_integrity as generated


class ArchiveBatch(unittest.TestCase):
    def setUp(self):
        self.c=generated.GeneratedIntegrity('test_generated_binding_keeps_text_provenance_and_not_applicable_marker')
        self.c.setUp();self.addCleanup(self.c.doCleanups)
        c=self.c;self.prepared=c.root/'prepared';self.entries=[];self.old={}
        image=c.generated()[0]['image']
        for n in range(2):
            with patch.object(official,'fetch',side_effect=c.source_fetch):
                packet,_=official.collect({**c.recipe,'url':c.url+'-'+str(n)},c.state,c.now)
            draft=copy.deepcopy(c.draft);draft['title']+=' '+str(n)
            job=c.ready(packet,draft)
            with database(c.state) as store:
                store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,run_id,status) VALUES(?,?,?,NULL,?,?,?,'deployed')",
                    (job['id'],digest(packet),digest(draft),'a'*40,str(n)*40,10+n));store.db.commit()
                self.old[job['id']]={'job':store.get(job['id']),'publication':dict(store.db.execute('SELECT * FROM publications WHERE job_id=?',(job['id'],)).fetchone())}
            raw=b'synthetic-image-'+str(n).encode();sha=hashlib.sha256(raw).hexdigest()
            replacement={**image,'sha256':sha,'local_path':'media/'+sha+'.jpg','url':'https://uutistenlukija.fi/media/'+sha+'.jpg',
                'pixel_review':approved_pixel_review(raw,draft,True)}
            target=self.prepared/replacement['local_path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            newpacket={k:v for k,v in packet.items() if k!='image_note'};newpacket['image']=replacement
            newdraft={**draft,'image':replacement}
            self.entries.append({'job_id':job['id'],'previous_packet_sha':digest(packet),'previous_draft_sha':digest(draft),
                'packet':newpacket,'draft':newdraft,'review':{'approved':True,'draft_sha256':digest(newdraft),'reasons':['Exact synthetic image review']}})

    def install(self,store,entries=None):
        return backfill.install(store,entries or self.entries,self.prepared,self.c.state,'c'*40)

    def unchanged(self,store):
        for identifier,old in self.old.items():
            self.assertEqual(store.get(identifier),old['job'])
            self.assertEqual(dict(store.db.execute('SELECT * FROM publications WHERE job_id=?',(identifier,)).fetchone()),old['publication'])

    def test_one_anchor_exact_release_history_and_live_readback(self):
        c=self.c
        with database(c.state) as store:
            anchor=self.install(store)
            self.assertEqual([r['job_id'] for r in backfill.pending(store)],[anchor])
            records=backfill.members(store,anchor);self.assertEqual(len(records),2)
            for r in records:
                self.assertEqual(r['previous_job'],self.old[r['job_id']]['job'])
                self.assertEqual(r['previous_publication'],self.old[r['job_id']]['publication'])
            with patch('news_mvp.publish.cmd',return_value='c'*40):
                root,receipt=public_bundle(store,store.get(anchor),c.state)
            self.assertEqual(len(receipt['image_backfill']),2)
            self.assertEqual(receipt['image_backfill_sha256'],digest(receipt['image_backfill']))
            read=lambda url:(root/url.removeprefix('https://uutistenlukija.fi/')).read_bytes()
            with self.assertRaisesRegex(ValueError,'live bytes mismatch'):
                backfill.complete(store,anchor,'d'*40,100,lambda url:b'wrong pixels' if url.endswith('.jpg') else read(url))
            self.assertEqual(store.db.execute("SELECT count(*) FROM publications WHERE status='deployed'").fetchone()[0],0)
            backfill.complete(store,anchor,'d'*40,100,read)
            self.assertEqual(backfill.pending(store),[])
            rows=store.db.execute('SELECT status,remote_commit,run_id FROM publications').fetchall()
            self.assertEqual([tuple(r) for r in rows],[('deployed','d'*40,100)]*2)
            self.assertEqual(store.db.execute('SELECT status FROM image_backfill_batches').fetchone()[0],'deployed')

    def test_preparation_mutations_and_duplicate_images_fail_without_job_changes(self):
        for kind in ['text','unapproved','old_hash','pixels','duplicate','reused_image']:
            with self.subTest(kind=kind),database(self.c.state) as store:
                entries=copy.deepcopy(self.entries)
                if kind=='text':entries[1]['draft']['summary']='Changed prose'
                if kind=='unapproved':entries[1]['review']['approved']=False
                if kind=='old_hash':entries[1]['previous_draft_sha']='f'*64
                if kind=='pixels':
                    image=entries[1]['draft']['image'];image['sha256']='f'*64
                if kind=='duplicate':entries.append(copy.deepcopy(entries[0]))
                if kind=='reused_image':
                    image=copy.deepcopy(entries[0]['draft']['image']);raw=(self.prepared/image['local_path']).read_bytes()
                    image['pixel_review']=approved_pixel_review(raw,entries[1]['draft'],True)
                    entries[1]['packet']['image']=image;entries[1]['draft']['image']=image
                    entries[1]['review']['draft_sha256']=digest(entries[1]['draft'])
                with self.assertRaises(ValueError):self.install(store,entries)
                self.unchanged(store)

    def test_pending_writer_blocks_batch_and_child_tamper_blocks_resume(self):
        with database(self.c.state) as store:
            identifier=self.entries[0]['job_id']
            store.db.execute("UPDATE publications SET status='dispatched' WHERE job_id=?",(identifier,));store.db.commit()
            with self.assertRaisesRegex(ValueError,'idle publisher'):self.install(store)
            store.db.execute("UPDATE publications SET status='deployed' WHERE job_id=?",(identifier,));store.db.commit()
            anchor=self.install(store)
            child=next(r['job_id'] for r in self.entries if r['job_id']!=anchor)
            store.db.execute("UPDATE publications SET status='dispatched' WHERE job_id=?",(child,));store.db.commit()
            with self.assertRaisesRegex(ValueError,'child state changed'):backfill.pending(store)

    def test_workflow_refuses_changed_batch_image_even_when_html_names_it(self):
        with database(self.c.state) as store,patch('news_mvp.publish.cmd',return_value='c'*40):
            anchor=self.install(store);root,receipt=public_bundle(store,store.get(anchor),self.c.state)
            record=next(r for r in receipt['image_backfill'] if r['job_id']!=anchor)
            (root/('mvp-assets/'+record['image_sha256']+'.jpg')).write_bytes(b'wrong image')
            with self.assertRaisesRegex(ValueError,'pixels changed'):
                backfill.validate_records(root,receipt['image_backfill'])

    def test_actual_workflow_cli_accepts_batch_and_refuses_changed_child_pixels(self):
        with database(self.c.state) as store,patch('news_mvp.publish.cmd',return_value='c'*40):
            anchor=self.install(store);root,receipt=public_bundle(store,store.get(anchor),self.c.state)
            receipt_path=self.c.root/'batch-release.json';receipt_path.write_text(json.dumps(receipt))
            script=Path(__file__).resolve().parents[1]/'cutover/check_release.py'
            env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
            command=[sys.executable,'-B',str(script),str(root),str(receipt_path)]
            good=subprocess.run(command,cwd=self.c.root,env=env,capture_output=True,text=True)
            self.assertEqual(good.returncode,0,good.stderr)
            child=next(r for r in receipt['image_backfill'] if r['job_id']!=anchor)
            name='mvp-assets/'+child['image_sha256']+'.jpg'
            (root/name).write_bytes(b'changed child image')
            receipt['files'][name]=hashlib.sha256(b'changed child image').hexdigest()
            receipt_path.write_text(json.dumps(receipt))
            bad=subprocess.run(command,cwd=self.c.root,env=env,capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0)
            self.assertIn('pixels changed',bad.stderr)

    def test_failed_batch_anchor_still_blocks_another_publication_writer(self):
        with database(self.c.state) as store:
            anchor=self.install(store)
            store.db.execute("UPDATE publications SET status='failed' WHERE job_id=?",(anchor,));store.db.commit()
            pending=backfill.pending(store)
            self.assertEqual([(r['job_id'],r['status']) for r in pending],[(anchor,'failed')])
            with self.assertRaisesRegex(ValueError,'idle publisher'):self.install(store)

    def test_image_only_approval_is_bound_to_original_editorial_decision(self):
        entries=copy.deepcopy(self.entries)
        for entry in entries:
            old=self.old[entry['job_id']]['job']
            original=json.loads(old['draft'])
            entry['review']['archive_image_only']={
                'original_draft_sha256':digest(original),
                'original_review_sha256':digest(json.loads(old['review'])),
                'original_published_at':old['created_at'],
                'unchanged_text_sha256':digest({k:v for k,v in original.items() if k not in ('image','image_note')})}
        with database(self.c.state) as store:
            bad=copy.deepcopy(entries)
            bad[1]['review']['archive_image_only']['original_review_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'original approval binding changed'):
                self.install(store,bad)
            self.unchanged(store)
            anchor=self.install(store,entries)
            self.assertEqual(len(backfill.members(store,anchor)),2)

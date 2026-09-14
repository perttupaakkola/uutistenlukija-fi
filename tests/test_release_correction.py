"""Revision55: actual bundle, Actions and canonical consumers; outbound transport faked."""
import copy,hashlib,io,json,unittest
from unittest.mock import patch
import test_release_v2 as base
COMMIT,REMOTE=base.COMMIT,base.REMOTE
from news_mvp.editorial import digest
from news_mvp.publish import public_bundle,publish
from news_mvp.store import database
from cutover.check_release import check
class Correction(unittest.TestCase):
    setUp=base.ReleaseV2.setUp
    source_fetch=base.ReleaseV2.source_fetch
    ready=base.ReleaseV2.ready
    image_job=base.ReleaseV2.image_job
    shell=base.ReleaseV2.shell
    workflow=base.ReleaseV2.workflow
    def bundle(self,job):
        with database(self.state) as store,patch('news_mvp.publish.cmd',return_value=COMMIT):return public_bundle(store,job,self.state)
    def test_actual_consumers_schema_first_and_downgrade_matrix(self):
        job=self.ready();site,receipt=self.bundle(job)
        check(site,receipt);self.assertIsNone(self.workflow(receipt)['image_sha256'])
        bad_cases=[]
        for variant in [True,False,'2',2.0,3,None,1]:
            bad=copy.deepcopy(receipt);bad['schema_version']=variant;bad_cases.append((str(variant),bad))
        for field in ['packet','draft','review','packet_sha256','draft_sha256','image_sha256','text_only','schema_version']:
            bad=copy.deepcopy(receipt);bad.pop(field);bad_cases.append(('missing '+field,bad))
        for mutation in ['unchanged','private','fixture','rejected','unauthorized','draft mismatch']:
            bad=copy.deepcopy(receipt)
            if mutation=='private':bad['packet']['private_only']=True
            if mutation=='fixture':bad['packet']['fixture']=True
            if mutation=='rejected':bad['review']['approved']=False
            if mutation=='unauthorized':bad['packet']['publication_basis']['policy']='unapproved'
            bad['packet_sha256']=digest(bad['packet'])
            if mutation=='draft mismatch':bad['draft']['summary']='Unreviewed summary'
            bad.pop('text_only');bad['image_sha256']='f'*64
            bad_cases.append(('downgrade '+mutation,bad))
        for label,bad in bad_cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):check(site,bad)
                with self.assertRaises(ValueError):self.workflow(bad)
    def test_actual_legacy_and_v2_imaged_and_mismatch(self):
        job,sha=self.image_job();site,legacy=self.bundle(job)
        self.assertNotIn('schema_version',legacy);check(site,legacy);self.assertEqual(self.workflow(legacy)['image_sha256'],sha)
        v2={**legacy,'schema_version':2,'packet':json.loads(job['packet']),'draft':json.loads(job['draft']),'review':json.loads(job['review'])}
        check(site,v2);self.assertEqual(self.workflow(v2)['image_sha256'],sha)
        for bad in [{**legacy,'packet':v2['packet']},{**legacy,'schema_version':1},{**v2,'image_sha256':'0'*64},{**v2,'text_only':None}]:
            with self.assertRaises(ValueError):check(site,bad)
            with self.assertRaises(ValueError):self.workflow(bad)
    def test_actual_publish_refuses_summary_and_licence_omissions(self):
        for kind in ['text','image']:
            if kind=='image':self.setUp()
            job=self.ready() if kind=='text' else self.image_job()[0]
            site,receipt=self.bundle(job);record=self.workflow(receipt)
            directory=self.state/'deployments/123';directory.mkdir(parents=True);(directory/'live-deployment.json').write_text(json.dumps(record))
            packet=json.loads(job['packet']);draft=json.loads(job['draft'])
            with database(self.state) as store:
                store.db.execute("INSERT INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,remote_commit,status) VALUES(?,?,?,?,?,?,'dispatched')",(job['id'],digest(packet),digest(draft),receipt['image_sha256'],COMMIT,REMOTE));store.db.commit()
            article=site/f"uutiset/{job['id']}/index.html";original=article.read_text()
            label='CC BY 4.0' if kind=='text' else draft['image']['license']
            for field,replacement in [(draft['summary'],''),(draft['summary'],'Changed summary'),(label,''),(label,'Wrong licence')]:
                html=original.replace(field,replacement);self.assertNotEqual(html,original)
                def response(request,**kwargs):
                    url=request.full_url
                    return io.BytesIO(html.encode()) if url.endswith('/') else io.BytesIO((site/url.removeprefix('https://uutistenlukija.fi/')).read_bytes())
                with self.subTest(kind=kind,field=field,replacement=replacement),database(self.state) as store,patch('news_mvp.publish.cmd',side_effect=self.shell([])),patch('news_mvp.publish.matching_runs',return_value=[{'databaseId':123,'status':'completed','conclusion':'success'}]),patch('news_mvp.publish.api',side_effect=AssertionError('No push during readback')),patch('urllib.request.urlopen',side_effect=response):
                    with self.assertRaises(ValueError):publish(store,job,self.state,self.cfg)
                    self.assertEqual(store.db.execute('SELECT status FROM publications WHERE job_id=?',(job['id'],)).fetchone()[0],'unknown')
                # The same altered body must fail the v2 hosted-bundle content check,
                # even when its file hash is recomputed to match the tampered bytes.
                v2={**receipt,'schema_version':2,'packet':packet,'draft':draft,'review':json.loads(job['review']),'files':dict(receipt['files'])}
                article.write_text(html);name=str(article.relative_to(site));v2['files'][name]=hashlib.sha256(article.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):check(site,v2)
                article.write_text(original)
if __name__=='__main__':unittest.main()

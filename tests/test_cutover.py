import hashlib
import json
import tempfile
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from cutover.prepare import crontab_change, released, approved_cutover, stopped_receipt, restorative
from cutover.continuity import baseline, verify, route_file
from cutover.check_release import check


class Cutover(unittest.TestCase):
    def test_selected_cron_roundtrip_preserves_personal_and_new_lines(self):
        current = '# comment\n*/5 * * * * old-news\n0 8 * * * personal-mail\n'
        stopped = crontab_change(current, ['*/5 * * * * old-news'])
        self.assertIn('0 8 * * * personal-mail\n', stopped)
        added = '0 9 * * * new-personal-job\n'
        self.assertEqual(crontab_change(stopped+added, ['*/5 * * * * old-news'],True),current+added)
        with self.assertRaises(ValueError):
            crontab_change(current,['*/6 * * * * old-news'])
        with self.assertRaises(ValueError):
            crontab_change(stopped,['*/5 * * * * old-news'])

    def git_fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='cutover-git-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        shutil.copytree(Path(__file__).resolve().parents[1]/'cutover',root/'cutover',ignore=shutil.ignore_patterns('__pycache__'))
        self.git(root,'init','-q')
        self.git(root,'add','cutover')
        self.git(root,'-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','-qm','reviewed cutover fixture')
        review={'step':4,'verdict':'approved','candidate_ref':self.git(root,'rev-parse','HEAD')}
        control={'authorized_step':5,'predecessor_review':'reviews/04.json','run_state':'running','stop_requested':False,'deadline_utc':'2026-09-13T00:51:36+00:00'}
        return root,review,control

    def git(self,root,*args):
        return subprocess.check_output(['git',*args],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()

    def test_actual_selected_routes_preserve_exporter(self):
        plan=json.loads((Path(__file__).resolve().parents[1]/'cutover/routes.json').read_text())
        exporter='25 */6 * * * /home/pertt/.openclaw/bin/export-uutistenlukija-analytics-team-snapshot >> /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline/logs/team-analytics-export.log 2>&1'
        self.assertNotIn(exporter,plan['crontab_lines'])
        current='\n'.join(plan['crontab_lines']+[exporter,'0 8 * * * personal-mail'])+'\n'
        stopped=crontab_change(current,plan['crontab_lines'])
        self.assertEqual([x for x in stopped.splitlines(True) if 'export-uutistenlukija' in x],[exporter+'\n'])
        self.assertEqual(crontab_change(stopped,plan['crontab_lines'],True),current)

    def test_reviewed_blobs_allow_descendant_but_reject_dirty_and_committed_edits(self):
        root,review,control=self.git_fixture()
        now=datetime(2026,9,12,22,tzinfo=timezone.utc)
        self.assertTrue(released(control,review,root,now))
        (root/'step5.py').write_text('# committed fresh step5 implementation fixture\n')
        self.git(root,'add','step5.py')
        self.git(root,'-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','-qm','step5 source')
        self.assertNotEqual(self.git(root,'rev-parse','HEAD'),review['candidate_ref'])
        self.assertTrue(released(control,review,root,now))
        file=root/'cutover/repoint.sh';original=file.read_bytes();file.write_bytes(original+b'# modified execution file\n')
        self.assertFalse(released(control,review,root,now))
        self.git(root,'add','cutover/repoint.sh')
        self.git(root,'-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','-qm','unreviewed execution edit')
        file.write_bytes(original)  # clean-looking disk cannot hide changed committed code
        self.assertFalse(approved_cutover(root,review))

    def test_release_gate_keeps_phase_deadline_stop_and_review_requirements(self):
        root,review,control=self.git_fixture()
        now=datetime(2026,9,12,22,tzinfo=timezone.utc)
        for key,value in [('authorized_step',4),('run_state','awaiting_review'),('stop_requested',True),('deadline_utc','2026-09-12T20:00:00+00:00'),('predecessor_review','reviews/03.json')]:
            self.assertFalse(released(dict(control,**{key:value}),review,root,now))
        self.assertFalse(released(control,dict(review,verdict='changes_requested'),root,now))
        self.assertFalse(released(control,dict(review,candidate_ref='0'*40),root,now))

    def test_restoration_after_expiry_stop_requires_exact_stop_and_no_new_publisher(self):
        root,review,control=self.git_fixture();state=root/'state';state.mkdir()
        plan=json.loads((root/'cutover/routes.json').read_text())
        before='\n'.join(plan['crontab_lines'])+'\n'
        (state/'crontab.before').write_text(before)
        (state/'crontab.stopped').write_text(crontab_change(before,plan['crontab_lines']))
        blobs={str(i):'old-blob-'+str(i) for i in plan['disable_workflow_ids']}
        (state/'stop.started').write_text(json.dumps({'approved_candidate':review['candidate_ref'],'legacy_workflow_blobs':blobs}))
        receipt=stopped_receipt(root,state,review)
        (state/'stop.finished').write_text(json.dumps(receipt))
        (root/'config.json').write_text('{"enabled":false}')
        from cutover.prepare import output as real_output
        def fake_output(*command,**kwargs):
            if command[0]=='systemctl':return 'LoadState=not-found\nActiveState=inactive\nUnitFileState='
            if command[0]=='gh':
                if command[-1]=='.sha':
                    return 'old-blob-'+command[2].split('/')[4].split('?')[0]
                return json.dumps({'workflows':[{'id':i,'path':str(i),'state':'disabled_manually'} for i in plan['disable_workflow_ids']]})
            return real_output(*command,**kwargs)
        with patch('cutover.prepare.output',side_effect=fake_output):
            for changed in [dict(control,deadline_utc='2026-09-12T20:00:00+00:00'),dict(control,stop_requested=True)]:
                self.assertFalse(released(changed,review,root,datetime(2026,9,12,22,tzinfo=timezone.utc)))
                self.assertTrue(restorative(root,state,review))
            (state/'repoint.started').touch();self.assertFalse(restorative(root,state,review));(state/'repoint.started').unlink()
            (root/'config.json').write_text('{"enabled":true}');self.assertFalse(restorative(root,state,review));(root/'config.json').write_text('{"enabled":false}')
            (state/'crontab.stopped').write_text('tampered');self.assertFalse(restorative(root,state,review));(state/'crontab.stopped').write_text(crontab_change(before,plan['crontab_lines']))
            (state/'stop.finished').write_text('{}');self.assertFalse(restorative(root,state,review));(state/'stop.finished').write_text(json.dumps(receipt))
            with patch('cutover.prepare.legacy_workflows',return_value={'new':'publisher'}):self.assertFalse(restorative(root,state,review))
            with patch('cutover.prepare.output',side_effect=lambda *a,**kw:'LoadState=loaded\nActiveState=active\nUnitFileState=enabled' if a[0]=='systemctl' else fake_output(*a,**kw)):
                self.assertFalse(restorative(root,state,review))
            (root/'cutover/rollback-before-repoint.sh').write_text('# changed rollback\n');self.assertFalse(restorative(root,state,review))

    def test_history_requires_every_page_and_excludes_image_namespace(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'posts/old').mkdir(parents=True)
            (p/'index.html').write_text('old home');(p/'posts/old/index.html').write_text('old article')
            sitemap=p/'sitemap.xml'
            sitemap.write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"><url><loc>https://uutistenlukija.fi/</loc></url><url><loc>https://uutistenlukija.fi/posts/old/</loc><image:image><image:loc>https://images.example/photo.jpg</image:loc></image:image></url></urlset>')
            m=baseline(sitemap,p);self.assertEqual(len(m['routes']),2)
            (p/'index.html').write_text('fresh home');self.assertEqual(verify(m,p),2)
            (p/'posts/old/index.html').write_text('silently changed article')
            with self.assertRaises(ValueError):verify(m,p)
            (p/'posts/old/index.html').unlink()
            with self.assertRaises(ValueError):baseline(sitemap,p)
        for url in ['https://other.example/a/','https://uutistenlukija.fi/%2e%2e/private/']:
            with self.assertRaises(ValueError):route_file(url)

    def test_exact_public_bundle_and_private_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'index.html').write_text('Public Finnish article')
            r={'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi','ga4_id':'G-35XERS8V6J','new_article_files':[],'files':{'index.html':hashlib.sha256((p/'index.html').read_bytes()).hexdigest()}}
            self.assertEqual(check(p,r),1)
            (p/'index.html').write_text('Yksityinen esikatselu')
            r['files']['index.html']=hashlib.sha256((p/'index.html').read_bytes()).hexdigest()
            with self.assertRaises(ValueError):check(p,r)


if __name__=='__main__':unittest.main()

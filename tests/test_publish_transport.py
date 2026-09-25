import io
import hashlib
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from news_mvp.publish import (api,upload_blob,incremental_tree,make_commit,
                              UncommittedPreparationError)


class GitObjectTransport(unittest.TestCase):
    def test_chunked_nested_tree_matches_real_git_and_preserves_base(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args, data=None):
                return subprocess.check_output(['git','-C',directory,*args],input=data,text=True,stderr=subprocess.DEVNULL).strip()
            git('init','-q')
            blob=git('hash-object','-w','--stdin',data='fixture bytes')
            requests=[]
            def tree_api(path,request):
                self.assertEqual(path,'git/trees');self.assertLessEqual(len(request['tree']),64)
                requests.append(request)
                if 'base_tree' in request:git('read-tree',request['base_tree'])
                else:git('read-tree','--empty')
                for item in request['tree']:
                    git('update-index','--add','--cacheinfo',item['mode'],item['sha'],item['path'])
                return {'sha':git('write-tree')}
            entries=[{'path':f'uutiset/story-{n:04d}/index.html','mode':'100644','type':'blob','sha':blob} for n in range(193)]
            with patch('news_mvp.publish.api',side_effect=tree_api):
                tree=incremental_tree(entries)
                self.assertEqual(len(requests),4)
                self.assertEqual(git('ls-tree','-r','--name-only',tree).splitlines(),sorted(x['path'] for x in entries))
                extra={'path':'existing-source.py','mode':'100644','type':'blob','sha':blob}
                updated=incremental_tree([extra],tree)
                self.assertEqual(len(git('ls-tree','-r','--name-only',updated).splitlines()),194)
            git('read-tree','--empty')
            for item in entries:git('update-index','--add','--cacheinfo',item['mode'],item['sha'],item['path'])
            self.assertEqual(tree,git('write-tree'))

    def test_preparation_failure_is_distinct_from_uncertain_commit(self):
        with patch('news_mvp.publish.prepare_commit_tree',side_effect=RuntimeError('tree timeout')),patch('news_mvp.publish.api') as request:
            with self.assertRaises(UncommittedPreparationError):make_commit(None,{'job_id':'fixture'})
            request.assert_not_called()
        with patch('news_mvp.publish.prepare_commit_tree',return_value=('parent','tree')),patch('news_mvp.publish.api',side_effect=RuntimeError('commit response lost')) as request:
            with self.assertRaises(RuntimeError) as caught:make_commit(None,{'job_id':'fixture'})
            self.assertNotIsInstance(caught.exception,UncommittedPreparationError)
            self.assertEqual(request.call_count,1)

    def call(self, path, responses, method=None):
        credential=subprocess.CompletedProcess([],0,'username=test\npassword=synthetic-only\n','')
        with patch('news_mvp.publish.subprocess.run',return_value=credential), \
             patch('news_mvp.publish.urllib.request.urlopen',side_effect=responses) as opened, \
             patch('news_mvp.publish.time.sleep'):
            result=api(path,{'content':'same exact object'},method=method)
        return result,opened.call_count

    def test_content_addressed_objects_retry_transient_gateway_error(self):
        for path in ('git/blobs','git/trees'):
            error=urllib.error.HTTPError('https://api.github.com/',502,'Gateway',{},None)
            result,count=self.call(path,[error,io.BytesIO(b'{"sha":"exact"}')])
            self.assertEqual(result,{'sha':'exact'});self.assertEqual(count,2)

    def test_commit_ref_and_other_failures_are_never_replayed(self):
        for path,method,status in [('git/commits',None,502),('git/refs/heads/main','PATCH',502),('git/blobs',None,403)]:
            error=urllib.error.HTTPError('https://api.github.com/',status,'Rejected',{},None)
            with self.assertRaisesRegex(RuntimeError,f'HTTP {status}'):
                self.call(path,[error],method)

    def test_object_gateway_retry_is_bounded(self):
        errors=[urllib.error.HTTPError('https://api.github.com/',503,'Gateway',{},None) for _ in range(3)]
        with self.assertRaisesRegex(RuntimeError,'GitHub POST git/blobs: HTTP 503'):
            self.call('git/blobs',errors)

    def test_completed_blob_survives_resume_and_changed_receipt_is_refused(self):
        raw=b'exact image bytes';sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            site=Path(directory)/'live-site'
            with patch('news_mvp.publish.api',return_value={'sha':sha}) as request:
                self.assertEqual(upload_blob(site,raw),sha)
                self.assertEqual(upload_blob(site,raw),sha)
                self.assertEqual(request.call_count,1)
            (Path(directory)/'uploaded-git-blobs'/sha).write_text('changed')
            with patch('news_mvp.publish.api',side_effect=AssertionError('Must not reupload')):
                with self.assertRaisesRegex(ValueError,'checkpoint changed'):upload_blob(site,raw)

    def test_wrong_remote_hash_never_creates_a_success_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory,patch('news_mvp.publish.api',return_value={'sha':'wrong'}):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                upload_blob(Path(directory)/'live-site',b'exact')
            self.assertFalse((Path(directory)/'uploaded-git-blobs').exists())

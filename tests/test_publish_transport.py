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

    def test_rejected_cached_blob_is_reuploaded_once_and_chunk_retried(self):
        sha='a'*40;calls=[];healed=[]
        def tree_api(path,request):
            calls.append(path)
            if len(calls)==1:raise RuntimeError('GitHub POST git/trees: HTTP 422 ValueError: {"message": "tree.sha '+sha+' is not a valid blob"}')
            return {'sha':'b'*40}
        entries=[{'path':'x.html','mode':'100644','type':'blob','sha':sha}]
        with patch('news_mvp.publish.api',side_effect=tree_api):
            self.assertEqual(incremental_tree(entries,reupload=healed.append),'b'*40)
        self.assertEqual(healed,[sha]);self.assertEqual(len(calls),2)
        def always(path,request):raise RuntimeError('tree.sha '+sha+' is not a valid blob')
        with patch('news_mvp.publish.api',side_effect=always),patch('news_mvp.publish.time.sleep'):
            with self.assertRaises(RuntimeError):incremental_tree(entries,reupload=lambda s:None)
            with self.assertRaises(RuntimeError):incremental_tree(entries)

    def test_base_tree_lag_is_retried_then_raised(self):
        calls=[]
        def lag(path,request):
            calls.append(request)
            if len(calls)<3:raise RuntimeError('GitHub POST git/trees: HTTP 422 ValueError: {"message": "base_tree is not a valid tree oid"}')
            return {'sha':'c'*40}
        entries=[{'path':'x.html','mode':'100644','type':'blob','sha':'a'*40}]
        with patch('news_mvp.publish.api',side_effect=lag),patch('news_mvp.publish.time.sleep') as sleep:
            self.assertEqual(incremental_tree(entries,'d'*40),'c'*40)
            self.assertEqual(sleep.call_count,2)
        def never(path,request):raise RuntimeError('base_tree is not a valid tree oid')
        with patch('news_mvp.publish.api',side_effect=never) as request,patch('news_mvp.publish.time.sleep'):
            with self.assertRaises(RuntimeError):incremental_tree(entries,'d'*40)
            self.assertEqual(request.call_count,13)
        def tree_lag(path,request):raise RuntimeError('tree.sha '+'e'*40+' is not a valid tree')
        with patch('news_mvp.publish.api',side_effect=tree_lag) as request,patch('news_mvp.publish.time.sleep'):
            with self.assertRaises(RuntimeError):incremental_tree(entries,'d'*40)
            self.assertEqual(request.call_count,13)

    def test_unpersisted_chained_base_is_rebuilt_by_replaying_chunks(self):
        # 28 Oct: GitHub returned a chunk tree sha, then rejected it as
        # base_tree for minutes. Replaying the earlier chunk must heal it.
        persisted=set();calls=[]
        def flaky(path,request):
            calls.append(request)
            if 'base_tree' in request and request['base_tree'] not in persisted:
                raise RuntimeError('GitHub POST git/trees: HTTP 422 ValueError: {"message": "base_tree is not a valid tree oid"}')
            sha=hashlib.sha1(repr(sorted((e['path'] for e in request['tree']))).encode()+request.get('base_tree','').encode()).hexdigest()
            if len(calls)>1:persisted.add(sha)  # first creation is lost
            return {'sha':sha}
        entries=[{'path':f'p{n:03d}.html','mode':'100644','type':'blob','sha':'a'*40} for n in range(100)]
        with patch('news_mvp.publish.api',side_effect=flaky),patch('news_mvp.publish.time.sleep') as sleep:
            incremental_tree(entries)
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(calls[4],calls[0])

    def test_bursty_422_and_500_on_chained_chunks_are_survived(self):
        # Real pattern seen 28 Oct: "..4..444....4.4..4.." plus HTTP 500.
        import itertools,json as _j
        pattern=itertools.cycle('..4..444....5.4..4..55....4444..');calls=[]
        def bursty(path,request):
            calls.append(1);c=next(pattern)
            if c=='4':raise RuntimeError('GitHub POST git/trees: HTTP 422 ValueError: {"message": "base_tree is not a valid tree oid"}')
            if c=='5':raise RuntimeError('GitHub POST git/trees: HTTP 500 ')
            return {'sha':hashlib.sha1(_j.dumps(request,sort_keys=True).encode()).hexdigest()}
        entries=[{'path':f'p{n:04d}.html','mode':'100644','type':'blob','sha':'a'*40} for n in range(64*12)]
        with patch('news_mvp.publish.api',side_effect=bursty),patch('news_mvp.publish.time.sleep') as sleep:
            incremental_tree(entries)
        self.assertTrue(all(c.args[0]<=20 for c in sleep.call_args_list))

    def test_github_tree_request_timeout_422_is_retried(self):
        # 29 Oct: one tick died on 422 "Sorry, your request timed out" for a
        # normal chunk; the identical request succeeds moments later.
        calls=[]
        msg=('GitHub POST git/trees: HTTP 422 ValueError: {"message": "Sorry, your request timed out.  '
             'It is likely that your input was too large to process."}')
        def slow(path,request):
            calls.append(request)
            if len(calls)<3:raise RuntimeError(msg)
            return {'sha':'f'*40}
        entries=[{'path':'x.html','mode':'100644','type':'blob','sha':'a'*40}]
        with patch('news_mvp.publish.api',side_effect=slow),patch('news_mvp.publish.time.sleep') as sleep:
            self.assertEqual(incremental_tree(entries,'d'*40),'f'*40)
            self.assertEqual(sleep.call_count,2)
        def never(path,request):raise RuntimeError(msg)
        with patch('news_mvp.publish.api',side_effect=never) as request,patch('news_mvp.publish.time.sleep'):
            with self.assertRaises(RuntimeError):incremental_tree(entries,'d'*40)
            self.assertEqual(request.call_count,13)

    def test_forced_upload_bypasses_checkpoint(self):
        raw=b'forced bytes';sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            site=Path(directory)/'live-site'
            with patch('news_mvp.publish.api',return_value={'sha':sha}) as request:
                upload_blob(site,raw);upload_blob(site,raw,force=True)
                self.assertEqual(request.call_count,2)

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

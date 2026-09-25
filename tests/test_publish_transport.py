import io
import hashlib
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from news_mvp.publish import api,upload_blob


class GitObjectTransport(unittest.TestCase):
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

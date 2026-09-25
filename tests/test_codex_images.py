import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from news_mvp import codex_images as provider, imagery
from test_imagery import _structured_png as original_png

def _structured_png():
    return original_png((900, 600))


class CodexImages(unittest.TestCase):
    def test_prose_success_without_actual_image_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            events = '\n'.join(json.dumps(e) for e in [
                {'type': 'thread.started', 'thread_id': 'a' * 36},
                {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Success: image.png'}},
                {'type': 'turn.completed'}])
            with self.assertRaises(imagery.GenerationError):
                provider._image_output(events, root, time.time() - 10, time.time())

    def test_ambiguous_stale_and_failed_outputs_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / ('a' * 36); directory.mkdir()
            first = directory / 'one.png'; first.write_bytes(_structured_png())
            events = '\n'.join(json.dumps(e) for e in [
                {'type': 'thread.started', 'thread_id': 'a' * 36}, {'type': 'turn.completed'}])
            started = time.time() - 10
            provider._image_output(events, root, started, time.time())
            second = directory / 'two.png'; second.write_bytes(first.read_bytes())
            with self.assertRaises(imagery.GenerationError):
                provider._image_output(events, root, started, time.time())
            second.unlink(); os.utime(first, (started - 10, started - 10))
            with self.assertRaises(imagery.GenerationError):
                provider._image_output(events, root, started, time.time())
            with self.assertRaises(imagery.GenerationError):
                provider._image_output(events + '\n' + json.dumps({'type': 'turn.failed'}), root, 0, time.time())

    def test_api_auth_and_secret_environment_are_refused_without_generation(self):
        with tempfile.TemporaryDirectory() as state, patch.object(provider, '_binary', return_value='/fixture/codex'), \
                patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-secret', 'GOOGLE_API_KEY': 'synthetic-google'}), \
                patch.object(provider.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Logged in using API key', '')) as login, \
                patch.object(provider.subprocess, 'Popen') as invoke:
            with self.assertRaisesRegex(imagery.GenerationError, 'ChatGPT login'):
                provider.generate_codex('article', 'drawing', state)
            invoke.assert_not_called()
            self.assertNotIn('OPENAI_API_KEY', login.call_args.kwargs['env'])
            self.assertNotIn('GOOGLE_API_KEY', login.call_args.kwargs['env'])

    def test_exact_cache_survives_review_outage_and_explicit_rejection_gets_new_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); home = root / 'codex'; calls = []
            def invoke(command, **kwargs):
                calls.append(command)
                class Process:
                    returncode = 0
                    pid = os.getpid()
                    def communicate(self, instruction, timeout):
                        tid = f'{len(calls):036x}'
                        output = home / 'generated_images' / tid; output.mkdir(parents=True)
                        (output / 'one.png').write_bytes(_structured_png())
                        for event in [{'type': 'thread.started', 'thread_id': tid}, {'type': 'turn.completed'}]:
                            kwargs['stdout'].write(json.dumps(event) + '\n')
                return Process()
            with patch.dict(os.environ, {'CODEX_HOME': str(home)}), \
                    patch.object(provider, '_binary', return_value='/fixture/codex'), \
                    patch.object(provider.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', 'Logged in using ChatGPT')), \
                    patch.object(provider.subprocess, 'Popen', side_effect=invoke):
                first = provider.generate_codex('article', 'drawing', root / 'state')
                self.assertEqual(first, provider.generate_codex('article', 'drawing', root / 'state'))
                self.assertEqual(len(calls), 1)
                request = provider._request_path('article', 'drawing', root / 'state')
                interrupted = json.loads((request / 'request.json').read_text())
                interrupted.update(state='running', worker_pid=999999999)
                (request / 'request.json').write_text(json.dumps(interrupted))
                self.assertEqual(first, provider.generate_codex('article', 'drawing', root / 'state'))
                self.assertEqual(len(calls), 1)
                self.assertIn('--ephemeral', calls[0]); self.assertIn('gpt-6-astra', calls[0])
                provider.reject_codex('article', 'drawing', root / 'state')
                provider.generate_codex('article', 'drawing', root / 'state')
                self.assertEqual(len(calls), 2)
                request = provider._request_path('article', 'drawing', root / 'state')
                receipt = json.loads((request / 'request.json').read_text())
                (request / receipt['raw_file']).write_bytes(b'changed')
                with self.assertRaisesRegex(imagery.GenerationError, 'bytes changed'):
                    provider.generate_codex('article', 'drawing', root / 'state')
                self.assertEqual(len(calls), 2)

    def test_interrupted_request_never_replays_or_falls_back(self):
        with tempfile.TemporaryDirectory() as state, patch.object(provider.subprocess, 'Popen') as invoke:
            root = provider._request_path('article', 'drawing', state); root.mkdir(parents=True)
            (root / 'request.json').write_text(json.dumps({'state': 'running'}))
            with self.assertRaisesRegex(imagery.GenerationError, 'reconciliation'):
                provider.generate_codex('article', 'drawing', state)
            invoke.assert_not_called()

    def test_editorial_refusal_discards_oauth_cache_and_past_pixels_remain_excluded(self):
        with tempfile.TemporaryDirectory() as state:
            draft = {'title': 'Construction supplies', 'category': 'Talous'}
            decision = {'category': 'Talous', 'depictable_scene': 'Bricks and pipes',
                        'must_show': ['bricks'], 'must_avoid': ['people']}
            prompt = imagery._prompt_for(draft['title'], decision['category'], decision['depictable_scene'],
                                        decision['must_show'], decision['must_avoid'])
            root = provider._request_path(draft['title'], prompt, state); root.mkdir(parents=True)
            (root / 'request.json').write_text(json.dumps({'state': 'success'}))
            image = {'model': provider.IMAGE_MODEL, 'classifier_output': decision, 'sha256': 'a'*64}
            imagery.discard_generated_candidate(image, draft, state)
            self.assertTrue(json.loads((root / 'request.json').read_text())['rejected'])
            history = Path(state) / 'image-rejections/job/refusal.json'; history.parent.mkdir(parents=True)
            history.write_text(json.dumps({'draft': {**draft,'image': image},
                'review': {'approved': False,'image_retryable': True}}))
            self.assertIn(image['sha256'], imagery._rejected_image_hashes(state))

    def test_auth_timeout_and_corrupt_cache_are_retryable_generation_errors(self):
        with tempfile.TemporaryDirectory() as state, patch.object(provider, '_binary', return_value='/fixture/codex'), \
                patch.object(provider.subprocess, 'run', side_effect=subprocess.TimeoutExpired('codex', 15)):
            with self.assertRaises(imagery.GenerationError):
                provider.generate_codex('article', 'drawing', state)
            root = provider._request_path('article', 'drawing', state)
            (root / 'request.json').write_text('invalid json')
            with self.assertRaises(imagery.GenerationError):
                provider.generate_codex('article', 'drawing', state)

    def test_expired_interrupted_request_backs_off_without_text_only_or_immediate_replay(self):
        with tempfile.TemporaryDirectory() as state, patch.object(provider.subprocess, 'Popen') as invoke:
            root = provider._request_path('article', 'drawing', state); (root / '1').mkdir(parents=True)
            (root / 'request.json').write_text(json.dumps({'state': 'running', 'attempt': 1,
                'submitted_epoch': time.time() - 400, 'deadline_epoch': time.time() - 60}))
            with self.assertRaises(imagery.GenerationError):
                provider.generate_codex('article', 'drawing', state)
            saved = json.loads((root / 'request.json').read_text())
            self.assertEqual(saved['state'], 'failed'); self.assertGreater(saved['retry_after'], time.time() + 890)
            with self.assertRaisesRegex(imagery.GenerationError, 'retry later'):
                provider.generate_codex('article', 'drawing', state)
            invoke.assert_not_called()

    def test_provider_unavailable_remains_image_pending_without_paid_fallback(self):
        draft = {'title': 'Rakennuskustannukset', 'summary': 'Rakennusmateriaalit', 'category': 'Talous',
                 'paragraphs': [{'text': 'Tiilet ja putket.'}]}
        decision = {'subject': 'Rakennuskustannukset', 'depictable_scene': 'Bricks and plumbing pipes',
                    'must_show': ['bricks', 'pipes'], 'must_avoid': ['people'], 'category': 'Talous',
                    'search_queries': ['bricks plumbing pipes', 'construction bricks materials', 'plumbing pipe supplies']}
        with tempfile.TemporaryDirectory() as state, patch.dict(os.environ, {'UUTIS_IMAGE_PROVIDER': 'codex-oauth'}), \
                patch.object(imagery, 'fetch_pexels', return_value=None), \
                patch.object(imagery, 'fetch_unsplash', return_value=None), \
                patch.object(provider, 'generate_codex', side_effect=imagery.GenerationError('unavailable')), \
                patch('news_mvp.image_providers.generate_google') as google, \
                patch('news_mvp.image_providers.generate_kie') as kie:
            self.assertIsNone(imagery.build_image(draft, state, attempts=1, decision=decision, allow_open_sources=False))
            google.assert_not_called(); kie.assert_not_called()
            self.assertFalse((Path(state) / 'media').exists())


if __name__ == '__main__':
    unittest.main()

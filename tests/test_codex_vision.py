"""Codex-subscription vision route, Google fallback and the per-article review budget."""
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from news_mvp import imagery, image_providers as providers
from news_mvp.editorial import digest
from test_article_first_image_pipeline import DECISION, DRAFT


def _jpeg(colour=(120, 110, 100)):
    buffer = io.BytesIO()
    Image.new('RGB', (800, 600), colour).save(buffer, format='JPEG')
    return buffer.getvalue()


class FakeCodex:
    """Stands in for ``codex exec``: records argv/env and writes the -o reply file."""

    def __init__(self, reply, returncode=0, events=None, stderr=''):
        self.reply, self.returncode, self.stderr = reply, returncode, stderr
        self.events = events if events is not None else [
            {'type': 'thread.started', 'thread_id': 'x'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message'}}, {'type': 'turn.completed'}]
        self.calls = []

    def __call__(self, command, env=None, **kwargs):
        fake = self
        class Proc:
            pid = 1
            returncode = fake.returncode
            def communicate(self, prompt=None, timeout=None):
                image = Path(command[command.index('-i') + 1])
                fake.calls.append({'command': list(command), 'env': dict(env), 'prompt': prompt,
                                   'image_name': image.name, 'image_bytes': image.read_bytes()})
                if fake.reply is not None:
                    Path(command[command.index('-o') + 1]).write_text(fake.reply)
                return '\n'.join(json.dumps(e) for e in fake.events), fake.stderr
        return Proc()


class CodexVision(unittest.TestCase):
    def setUp(self):
        providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0)

    def _run(self, fake, raw=None, instruction='Return JSON with description (string).'):
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', side_effect=fake), \
                mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'sk-secret', 'GOOGLE_API_KEY': 'g-secret',
                                               'UUTIS_VISION_PROVIDER': 'codex-oauth'}):
            return providers.vision(raw or _jpeg(), instruction)

    def test_codex_route_is_isolated_metadata_free_and_returns_json_contract(self):
        fake = FakeCodex('```json\n{"description": "A red barn."}\n```')
        exif_jpeg = io.BytesIO()
        image = Image.new('RGB', (2400, 1600), (200, 30, 30))
        exif = Image.Exif(); exif[0x010e] = 'secret-filename-hint.jpg'
        image.save(exif_jpeg, format='JPEG', exif=exif)
        value, model = self._run(fake, exif_jpeg.getvalue())
        self.assertEqual(value, {'description': 'A red barn.'})
        self.assertTrue(model.startswith('codex-oauth:'))
        call = fake.calls[0]
        for flag in ('--ephemeral', '--ignore-user-config', '--skip-git-repo-check', '--json'):
            self.assertIn(flag, call['command'])
        self.assertEqual(call['command'][call['command'].index('--sandbox') + 1], 'read-only')
        self.assertIn('shell_tool', call['command']); self.assertIn('apps', call['command'])
        self.assertIn('web_search="disabled"', call['command'])
        self.assertNotIn('OPENAI_API_KEY', call['env']); self.assertNotIn('GOOGLE_API_KEY', call['env'])
        self.assertEqual(call['image_name'], 'image.jpg')
        attached = Image.open(io.BytesIO(call['image_bytes']))
        self.assertLessEqual(max(attached.size), 1024)
        self.assertNotIn(b'secret-filename-hint', call['image_bytes'])
        self.assertNotIn('secret-filename-hint', call['prompt'])

    def test_codex_usage_limit_raises_without_google_and_opens_breaker(self):
        fake = FakeCodex(None, returncode=1, stderr='You have hit your usage limit')
        with tempfile.TemporaryDirectory() as state:
            with providers.image_attempt({'title': 'x'}, state) as receipt, \
                    mock.patch.object(providers, 'google_vision') as google:
                with self.assertRaises(imagery.GenerationError):
                    self._run(fake)
                with self.assertRaises(imagery.GenerationError):
                    self._run(fake)
                events = list(receipt['requests'])
        google.assert_not_called()
        self.assertEqual(len(fake.calls), 1)  # usage limit: no retry, breaker opens
        self.assertEqual([e['error_type'] for e in events], ['UsageLimit', 'BreakerOpen'])
        self.assertTrue(all(e['host'] == providers.CODEX_VISION_HOST for e in events))

    def test_transient_codex_failure_is_retried_on_codex(self):
        good = {'description': 'ok'}
        calls = []
        def flaky(raw, instruction, max_tokens=1200):
            calls.append(1)
            if len(calls) == 1:
                raise imagery.GenerationError('Codex vision unavailable: TimeoutExpired')
            return good
        providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0)
        with mock.patch.object(providers, 'codex_vision', side_effect=flaky), \
                mock.patch.object(providers, 'google_vision') as google:
            value, model = providers.vision(_jpeg(), 'x', provider='codex-oauth')
        self.assertEqual(value, good); self.assertEqual(len(calls), 2)
        self.assertTrue(model.startswith('codex-oauth:'))
        google.assert_not_called()

    def test_timeout_raises_without_google(self):
        class Slow:
            pid = 1; returncode = None
            def communicate(self, prompt=None, timeout=None):
                if prompt is not None:
                    raise subprocess.TimeoutExpired('codex', timeout)
                return '', ''
        providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0)
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', return_value=Slow()), \
                mock.patch.object(providers.os, 'killpg'), \
                mock.patch.object(providers, 'google_vision') as google:
            with self.assertRaises(imagery.GenerationError):
                providers.vision(_jpeg(), 'x', provider='codex-oauth')
        google.assert_not_called()

    def test_malformed_reply_never_uses_google(self):
        for fake in (FakeCodex('not json at all'),
                     FakeCodex('{"description": "x"}', events=[
                         {'type': 'item.completed', 'item': {'type': 'command_execution'}},
                         {'type': 'turn.completed'}])):
            providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0)
            with mock.patch.object(providers, 'google_vision') as google:
                with self.assertRaises(imagery.GenerationError):
                    self._run(fake)
            google.assert_not_called()

    def test_review_pixels_uses_codex_route_and_records_model(self):
        primary = {'approved': True, 'no_people': True, 'fit_score': 9, 'must_show_visible': [True],
                   'description': 'A daycare building.', 'reason': 'Concrete fit.',
                   'alt_fi': 'Päiväkodin matala rakennus ja sisäänkäynti talvisessa pihassa.'}
        fake = FakeCodex(json.dumps(primary))
        concept = imagery.concept_decision(DECISION, DECISION['concepts'][0])
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', side_effect=fake), \
                mock.patch.object(providers, 'google_vision') as google, \
                mock.patch.dict('os.environ', {'UUTIS_VISION_PROVIDER': 'codex-oauth'}):
            review = imagery.review_pixels(_jpeg(), DRAFT, concept=concept)
        self.assertTrue(review['approved']); self.assertEqual(review['fit_score'], 9)
        self.assertTrue(review['model'].startswith('codex-oauth:'))
        google.assert_not_called()

    def test_describe_uses_shared_route_for_codex(self):
        with mock.patch.dict('os.environ', {'UUTIS_VISION_PROVIDER': 'codex-oauth'}), \
                mock.patch.object(providers, 'vision', return_value=({'description': 'A  barn.'}, 'm')):
            self.assertEqual(imagery.describe(_jpeg()), 'A barn.')


class ArticleReviewBudget(unittest.TestCase):
    def _review(self, scores):
        def review(pixels, article, generated=False, concept=None, **kwargs):
            scores.append(concept['rank'] if 'rank' in concept else concept['subject'])
            return {'approved': False, 'fit_score': 5,
                    'must_show_visible': [True] * len(concept['must_show']),
                    'image_sha256': hashlib.sha256(pixels).hexdigest(),
                    'article_text_sha256': imagery._article_text_sha(article),
                    'concept_sha256': digest(concept), 'alt_fi': 'Rakennus näkyy talvisessa pihassa.',
                    'description': 'Unrelated.', 'reason': 'Weak fit.', 'no_people': True}
        return review

    def test_reviews_are_capped_per_article_and_concept_and_describe_is_skipped(self):
        counter = {'n': 0}
        describe_calls = []

        def fetcher(*args, accept=None, **kwargs):
            # Each provider offers many distinct candidates, as a live search can.
            for _ in range(10):
                counter['n'] += 1
                raw = _jpeg((counter['n'] % 250, 10, 10)) + bytes([counter['n'] % 256]) * counter['n']
                describe_calls.append(imagery.describe(raw))
                stock = {'url': 'https://images.example/x.jpg', 'source_url': 'https://example/x',
                         'license': 'free', 'stock_provenance': {'provider': 'pexels',
                                                                'photo_id': str(counter['n'])}}
                with mock.patch.object(imagery, '_get_external_bytes', return_value=raw):
                    try:
                        if accept(stock):
                            return stock
                    except RuntimeError:
                        return None
            return None

        reviewed = []
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.dict('os.environ', {'UUTIS_VISION_PROVIDER': 'codex-oauth'}), \
                mock.patch.object(providers, 'vision') as vision, \
                mock.patch.object(imagery, 'fetch_pexels', side_effect=fetcher), \
                mock.patch.object(imagery, 'fetch_unsplash', side_effect=fetcher), \
                mock.patch.object(imagery, 'fetch_wikimedia', side_effect=fetcher), \
                mock.patch.object(imagery, 'fetch_google', side_effect=fetcher), \
                mock.patch.object(imagery, 'review_pixels', side_effect=self._review(reviewed)), \
                mock.patch.object(imagery, '_build_image', return_value=None):
            result = imagery._build_image_article_first(DRAFT, state, 'Kotimaa', 'fixture', 1,
                                                        DECISION, True, True, None)
        self.assertIsNone(result)
        self.assertEqual(len(reviewed), imagery.MAX_ARTICLE_PIXEL_REVIEWS)
        per_concept = {s: reviewed.count(s) for s in set(reviewed)}
        self.assertTrue(all(n <= imagery.MAX_CONCEPT_PIXEL_REVIEWS for n in per_concept.values()))
        self.assertEqual(len(per_concept), 2)  # concept 2 still gets reviewed
        vision.assert_not_called()  # pre-review describe skipped inside the article tree
        self.assertTrue(describe_calls and all(d is None for d in describe_calls))

    def test_selection_evidence_still_validates_under_the_budget(self):
        def fetcher(*args, accept=None, **kwargs):
            return None
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(imagery, 'fetch_pexels', side_effect=fetcher), \
                mock.patch.object(imagery, 'fetch_unsplash', side_effect=fetcher), \
                mock.patch.object(imagery, '_build_image', return_value=None):
            self.assertIsNone(imagery._build_image_article_first(
                DRAFT, state, 'Kotimaa', 'fixture', 1, DECISION, False, True, None))

    def test_describe_outside_article_tree_still_runs(self):
        with mock.patch.dict('os.environ', {'UUTIS_VISION_PROVIDER': 'google'}), \
                mock.patch.object(providers, 'vision', return_value=({'description': 'x'}, 'm')) as vision:
            self.assertEqual(imagery.describe(_jpeg()), 'x')
        vision.assert_called_once()


if __name__ == '__main__':
    unittest.main()


class GoogleBillingFallback(unittest.TestCase):
    """Real case 4 Nov 2026: every Gemini call answered HTTP 402 'prepayment credits depleted'."""

    def setUp(self):
        providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0)
        providers._GOOGLE_VISION_STATE.update(down_until=0.0)

    def _env(self):
        return mock.patch.dict('os.environ', {'UUTIS_VISION_PROVIDER': 'google'})

    def test_depleted_credits_fall_over_to_codex_and_open_breaker(self):
        from news_mvp.imagery import GenerationError
        refusal = GenerationError('generativelanguage.googleapis.com request unavailable: HTTP 402')
        with self._env(), mock.patch.object(providers, 'google_vision', side_effect=refusal) as google, \
                mock.patch.object(providers, 'codex_vision', return_value={'description': 'c'}) as codex:
            first = providers.vision(_jpeg(), 'x')
            second = providers.vision(_jpeg(), 'x')
        self.assertEqual(first[0], {'description': 'c'})
        self.assertTrue(first[1].startswith('codex-oauth:'))
        self.assertEqual(second[0], {'description': 'c'})
        self.assertEqual(google.call_count, 1)  # breaker: no second paid refusal per tick
        self.assertEqual(codex.call_count, 2)

    def test_non_billing_google_error_is_not_masked(self):
        from news_mvp.imagery import GenerationError
        with self._env(), mock.patch.object(providers, 'google_vision',
                                            side_effect=GenerationError('Google vision returned no valid JSON review')), \
                mock.patch.object(providers, 'codex_vision') as codex:
            with self.assertRaises(GenerationError):
                providers.vision(_jpeg(), 'x')
        codex.assert_not_called()

"""23 Nov 2026: subscription refused the pinned models with HTTP 429 while others answered."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from news_mvp import imagery, image_providers as providers, codex_images as provider
from test_codex_vision import FakeCodex, _jpeg

FIXTURE = Path(__file__).parent / 'fixtures' / 'codex_model_429_events.jsonl'


class VisionModelFallback(unittest.TestCase):
    def setUp(self):
        providers._CODEX_VISION_STATE.update(down_until=0.0, failures=0, model_down={})

    def test_model_429_falls_through_to_next_model(self):
        refused = FixtureCodex()
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', side_effect=refused):
            value, model = providers.vision(_jpeg(), 'Return JSON.', provider='codex-oauth')
        self.assertEqual(value, {'description': 'ok'})
        self.assertEqual(model, 'codex-oauth:gpt-6.1-terra')
        self.assertEqual(refused.models[0], providers.CODEX_VISION_MODEL)
        self.assertEqual(providers._CODEX_VISION_STATE['down_until'], 0.0)
        # The refused model is skipped on the next review in the same tick.
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', side_effect=refused):
            providers.vision(_jpeg(), 'Return JSON.', provider='codex-oauth')
        self.assertEqual(refused.models[-1], 'gpt-6.1-terra')
        self.assertEqual(refused.models.count(providers.CODEX_VISION_MODEL), 1)

    def test_all_models_refused_opens_breaker(self):
        fake = FakeCodex(None, returncode=1, stderr='exceeded retry limit, last status: 429 Too Many Requests')
        with mock.patch('news_mvp.codex_images._binary', return_value='/bin/codex'), \
                mock.patch.object(providers.subprocess, 'Popen', side_effect=fake):
            with self.assertRaises(imagery.GenerationError):
                providers.vision(_jpeg(), 'x', provider='codex-oauth')
        self.assertEqual(len(fake.calls), len(providers.codex_vision_models()))
        self.assertGreater(providers._CODEX_VISION_STATE['down_until'], 0)


class FixtureCodex:
    """Real 23 Nov failure events for the primary model; any other model answers."""
    def __init__(self):
        self.models = []

    def __call__(self, command, env=None, **kwargs):
        fake = self
        model = command[command.index('-m') + 1]
        self.models.append(model)
        class Proc:
            pid = 1
            returncode = 1 if model == providers.CODEX_VISION_MODEL else 0
            def communicate(self, prompt=None, timeout=None):
                if model == providers.CODEX_VISION_MODEL:
                    return FIXTURE.read_text(), ''
                Path(command[command.index('-o') + 1]).write_text('{"description": "ok"}')
                return '\n'.join(json.dumps(e) for e in [
                    {'type': 'thread.started', 'thread_id': 'x'},
                    {'type': 'turn.completed'}]), ''
        return Proc()


class GenerationModelFallback(unittest.TestCase):
    def test_generation_falls_back_after_model_429(self):
        seen = []
        def invoke(command, stdout=None, **kwargs):
            model = command[command.index('-m') + 1]
            seen.append(model)
            class Proc:
                pid = 999999
                returncode = 1 if model == provider.MODEL else 0
                def communicate(self, instruction, timeout):
                    stdout.write(FIXTURE.read_text() if model == provider.MODEL else 'ok')
                    stdout.flush()
                def poll(self):
                    return self.returncode
            return Proc()
        with tempfile.TemporaryDirectory() as state, \
                mock.patch.object(provider, '_binary', return_value='/bin/codex'), \
                mock.patch.object(provider.subprocess, 'run', return_value=mock.Mock(
                    returncode=0, stdout='Logged in using ChatGPT', stderr='')), \
                mock.patch.object(provider.subprocess, 'Popen', side_effect=invoke), \
                mock.patch.object(provider.Path, 'read_text', autospec=True,
                                  side_effect=_stat_aware_read), \
                mock.patch.object(provider, '_image_output', return_value=(b'png', {})), \
                mock.patch.object(provider, '_save_result'):
            raw, _, _ = provider._generate_codex('s', 'p', state)
        self.assertEqual(raw, b'png')
        self.assertEqual(seen, [provider.MODEL, provider.FALLBACK_MODELS[0]])


_real_read_text = Path.read_text


def _stat_aware_read(self, *args, **kwargs):
    if self.name == 'stat' and str(self).startswith('/proc/999999'):
        return '999999 (codex) ' + ' '.join(['0'] * 30)
    return _real_read_text(self, *args, **kwargs)


if __name__ == '__main__':
    unittest.main()

import json, tempfile, time, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from news_mvp.live import live_tick
from news_mvp.store import database


def _ago(seconds):
    return datetime.fromtimestamp(time.time() - seconds, timezone.utc).isoformat()


class ImagePendingYieldsToIntake(unittest.TestCase):
    """29 Oct: a story refused only for its image was due on every tick and blocked intake."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); self.state = root / 'state'
        self.config_path = root / 'config.json'
        self.config_path.write_text(json.dumps({
            'enabled': True, 'backend': 'hermes', 'state_dir': str(self.state),
            'output_dir': str(root / 'private'), 'source_recipes': [],
            'discovery': {'family': 'nasa-modis'}, 'max_attempts': 3, 'retry_seconds': 60,
            'illustrations': False}))

    def admit(self, store, name, created):
        url = 'https://example.invalid/' + name
        return store.admit({'fixture': False, 'story_key': 'url:' + url,
                            'sources': [{'url': url}]}, created)[0]

    def pend(self, store, job_id, error='Image pending: editorial image-only rejection'):
        with store.db:
            store.db.execute("UPDATE jobs SET next_attempt=1, error=? WHERE id=?", (error, job_id))

    def test_new_story_is_advanced_before_due_image_retry(self):
        with database(self.state) as store:
            stuck = self.admit(store, 'stuck-image', _ago(2 * 3600))
            self.pend(store, stuck)
        fresh = {'url': 'https://example.invalid/fresh', 'story_key': 'url:https://example.invalid/fresh'}
        advanced = []
        def fake_advance(store, job, config, config_path, errors=None):
            advanced.append(job['id']); return {'status': 'ready', 'job_id': job['id']}
        def fake_ingest(config, packet):
            with database(self.state) as s:
                return {'admitted': True, 'id': self.admit(s, 'fresh', _ago(60))}
        with patch('news_mvp.live.discover', return_value=[fresh]), \
                patch('news_mvp.live.collect', return_value=({'x': 1}, {})), \
                patch('news_mvp.live.ingest', side_effect=fake_ingest), \
                patch('news_mvp.live._advance_job', side_effect=fake_advance):
            live_tick(self.config_path)
        self.assertEqual(len(advanced), 1)
        self.assertNotEqual(advanced[0], stuck)

    def test_image_retry_runs_when_no_new_story_and_is_skipped_in_discovery(self):
        with database(self.state) as store:
            stuck = self.admit(store, 'stuck-image', _ago(2 * 3600))
            self.pend(store, stuck)
        same = {'url': 'https://example.invalid/stuck-image',
                'story_key': 'url:https://example.invalid/stuck-image'}
        advanced = []
        def fake_advance(store, job, config, config_path, errors=None):
            advanced.append(job['id']); return {'status': 'ready', 'job_id': job['id']}
        with patch('news_mvp.live.discover', return_value=[same]), \
                patch('news_mvp.live.collect', side_effect=AssertionError('no recollection')), \
                patch('news_mvp.live._advance_job', side_effect=fake_advance):
            live_tick(self.config_path)
        self.assertEqual(advanced, [stuck])

    def test_ordinary_due_retry_still_precedes_discovery(self):
        with database(self.state) as store:
            due = self.admit(store, 'interrupted', _ago(2 * 3600))
            self.pend(store, due, 'Interrupted tick; saved draft retained')
        advanced = []
        def fake_advance(store, job, config, config_path, errors=None):
            advanced.append(job['id']); return {'status': 'ready', 'job_id': job['id']}
        with patch('news_mvp.live.discover', side_effect=AssertionError('retry must win')), \
                patch('news_mvp.live._advance_job', side_effect=fake_advance):
            live_tick(self.config_path)
        self.assertEqual(advanced, [due])


if __name__ == '__main__':
    unittest.main()

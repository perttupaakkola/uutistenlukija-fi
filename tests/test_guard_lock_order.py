import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from news_mvp.live import live_tick


class GuardAfterLock(unittest.TestCase):
    """30 Oct 2026: a guarded guide edit held controller.lock with a dirty tree; the tick ran
    the clean-tree guard before the lock and exited 'Commit source changes before publishing'."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state = root / 'state'
        self.state.mkdir()
        self.config = root / 'config.json'
        self.config.write_text(json.dumps({'enabled': True, 'backend': 'hermes',
            'state_dir': str(self.state), 'output_dir': str(root / 'private'),
            'source_recipes': [], 'discovery': {'family': 'news-reviewed-v2'},
            'max_attempts': 3, 'retry_seconds': 60}))

    def test_tick_is_busy_not_crashed_while_guarded_edit_holds_lock(self):
        dirty = ValueError('Commit source changes before publishing')
        with (self.state / 'controller.lock').open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch('news_mvp.live.guard', side_effect=dirty) as g:
                self.assertEqual(live_tick(str(self.config))['status'], 'busy')
            g.assert_not_called()

    def test_guard_still_enforced_when_lock_free(self):
        with patch('news_mvp.live.guard', side_effect=ValueError('Commit source changes before publishing')):
            with self.assertRaisesRegex(ValueError, 'Commit source changes'):
                live_tick(str(self.config))


if __name__ == '__main__':
    unittest.main()

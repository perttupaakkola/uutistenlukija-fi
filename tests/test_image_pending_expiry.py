import sqlite3, time, unittest
from datetime import datetime, timezone
from news_mvp.store import Store, IMAGE_PENDING_MAX_AGE


class ImagePendingExpiry(unittest.TestCase):
    """29 Oct: an image-pending story kept yielding to new stories, never used its
    attempts and sat in the queue for 4.5 h+. It must expire on age alone."""

    def setUp(self):
        self.db = sqlite3.connect(':memory:'); self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE jobs (id TEXT, status TEXT, attempts INTEGER, "
                        "next_attempt REAL, error TEXT, created_at TEXT)")
        self.db.execute("CREATE TABLE publications (job_id TEXT)")
        self.store = Store(self.db); self.now = time.time()

    def add(self, jid, age, error='Image pending: editorial image-only rejection', status='ready'):
        created = datetime.fromtimestamp(self.now - age, timezone.utc).isoformat()
        self.db.execute("INSERT INTO jobs VALUES (?,?,0,0,?,?)", (jid, status, error, created))

    def status(self, jid):
        return self.db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()[0]

    def test_old_image_pending_story_fails_without_using_attempts(self):
        self.add('old', IMAGE_PENDING_MAX_AGE + 600)
        self.add('young', 3600)
        self.add('old_other', IMAGE_PENDING_MAX_AGE + 600, error='Interrupted tick; saved draft retained')
        self.add('old_published', IMAGE_PENDING_MAX_AGE + 600)
        self.db.execute("INSERT INTO publications VALUES ('old_published')")
        self.assertEqual(self.store.expire_image_pending(self.now), 1)
        self.assertEqual(self.status('old'), 'failed')
        self.assertEqual(self.status('young'), 'ready')
        self.assertEqual(self.status('old_other'), 'ready')
        self.assertEqual(self.status('old_published'), 'ready')

    def test_live_tick_calls_expiry(self):
        from pathlib import Path
        import news_mvp.live as live
        self.assertIn('store.expire_image_pending(', Path(live.__file__).read_text())

    def test_expiry_runs_before_publication_reconciliation_returns(self):
        # 29 Oct: story ed879136 (admitted 14:17) stayed queued until 19:27 because
        # the 18:30, 18:57 and 19:12 ticks all returned through upload reconciliation.
        from pathlib import Path
        import news_mvp.live as live
        src = Path(live.__file__).read_text()
        tick = src[src.index('def _live_tick'):]
        self.assertLess(tick.index('store.expire_image_pending('),
                        tick.index('pending=pending_publications(store)'))

    def test_live_tick_expires_while_upload_pending(self):
        import json, tempfile
        from pathlib import Path
        from unittest.mock import patch
        from news_mvp.live import live_tick
        from news_mvp.store import database
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); state = root / 'state'; cfg = root / 'config.json'
            cfg.write_text(json.dumps({'enabled': True, 'backend': 'hermes', 'state_dir': str(state),
                'output_dir': str(root / 'p'), 'source_recipes': [], 'discovery': {'family': 'nasa-modis'},
                'max_attempts': 3, 'retry_seconds': 60, 'illustrations': False}))
            old = datetime.fromtimestamp(self.now - IMAGE_PENDING_MAX_AGE - 3600, timezone.utc).isoformat()
            with database(state) as store:
                url = 'https://www.kuopio.fi/2026/10/29/piispanpuiston-taydennysistutukset-ovat-valmistuneet/'
                jid = store.admit({'fixture': False, 'story_key': 'url:' + url, 'sources': [{'url': url}]}, old)[0]
                with store.db:
                    store.db.execute("UPDATE jobs SET error=? WHERE id=?",
                        ('Image pending: editorial image-only rejection; candidate retained for audit', jid))
            with patch('news_mvp.backfill.pending', return_value=[{'job_id': 'other'}]), \
                    patch('news_mvp.live.publish', return_value={'status': 'dispatched'}), \
                    patch('news_mvp.live.unresolved_site_refreshes', return_value=[]):
                live_tick(cfg)
            with database(state) as store:
                self.assertEqual(store.get(jid)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()

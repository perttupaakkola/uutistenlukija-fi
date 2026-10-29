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


if __name__ == '__main__':
    unittest.main()

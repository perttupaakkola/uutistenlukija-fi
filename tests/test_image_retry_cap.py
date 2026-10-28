import sqlite3, time, unittest
from datetime import datetime, timezone
from news_mvp import store as store_mod


class ImageRetryCap(unittest.TestCase):
    def make(self, age_seconds):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        s = store_mod.Store(db) if hasattr(store_mod, 'Store') else None
        return s

    def test_old_image_pending_job_uses_up_attempts(self):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE jobs (id TEXT, status TEXT, attempts INTEGER, next_attempt REAL, error TEXT, created_at TEXT)")
        now = time.time()
        old = datetime.fromtimestamp(now - 5 * 3600, timezone.utc).isoformat()
        new = datetime.fromtimestamp(now - 600, timezone.utc).isoformat()
        db.execute("INSERT INTO jobs VALUES ('old','running',2,0,NULL,?)", (old,))
        db.execute("INSERT INTO jobs VALUES ('new','running',2,0,NULL,?)", (new,))
        obj = object.__new__([c for c in vars(store_mod).values() if isinstance(c, type) and hasattr(c, 'defer_image')][0])
        obj.db = db
        obj.defer_image('old', now, 900, 'Image pending: x')
        obj.defer_image('new', now, 900, 'Image pending: x')
        att = dict(db.execute("SELECT id, attempts FROM jobs").fetchall())
        self.assertEqual(att['old'], 2)   # counts: the story will exhaust max_attempts
        self.assertEqual(att['new'], 1)   # fresh story: image retry is free


if __name__ == '__main__':
    unittest.main()

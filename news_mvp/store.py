"""One local SQLite job table; saved drafts survive interrupted ticks."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .editorial import digest, encode, web_url


@contextmanager
def database(state_dir):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(Path(state_dir) / "jobs.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE,
        source_url TEXT NOT NULL UNIQUE, packet TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0, draft TEXT, review TEXT,
        adapter TEXT, created_at TEXT NOT NULL, error TEXT
    )""")
    db.commit()
    try:
        yield Store(db)
    finally:
        db.close()


class Store:
    def __init__(self, db):
        self.db = db

    def admit(self, packet, created_at):
        identity = digest(packet["story_key"])
        primary = web_url(packet["sources"][0]["url"])
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO jobs
                (id, story_key, source_url, packet, created_at) VALUES (?, ?, ?, ?, ?)""",
                (identity, packet["story_key"], primary, encode(packet), created_at))
            added = self.db.execute("SELECT changes()").fetchone()[0] == 1
            row = self.db.execute("SELECT id FROM jobs WHERE story_key=? OR source_url=?",
                                  (packet["story_key"], primary)).fetchone()
        return row["id"], added

    def recover(self, max_attempts):
        # Called only after the controller has acquired the process lock.
        with self.db:
            self.db.execute("""UPDATE jobs SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'ready' END,
                error='Interrupted tick; saved draft retained' WHERE status='running'""", (max_attempts,))

    def claim(self, now, max_attempts):
        with self.db:
            row = self.db.execute("""SELECT * FROM jobs WHERE status='ready'
                AND next_attempt<=? AND attempts<? ORDER BY created_at, id LIMIT 1""",
                (now, max_attempts)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (row["id"],))
        return self.get(row["id"])

    def save_draft(self, job_id, draft, adapter):
        with self.db:
            self.db.execute("UPDATE jobs SET draft=?, adapter=? WHERE id=?", (encode(draft), adapter, job_id))

    def finish_review(self, job_id, review):
        with self.db:
            self.db.execute("UPDATE jobs SET review=?, status=?, error=NULL WHERE id=?",
                            (encode(review), "approved" if review["approved"] else "rejected", job_id))

    def fail(self, job_id, now, max_attempts, retry_seconds, error):
        row = self.get(job_id)
        with self.db:
            self.db.execute("UPDATE jobs SET status=?, next_attempt=?, error=? WHERE id=?",
                            ("failed" if row["attempts"] >= max_attempts else "ready",
                             now + retry_seconds * row["attempts"], error, job_id))

    def get(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def articles(self):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM jobs WHERE status IN ('approved','rendered') ORDER BY created_at DESC, id")]

    def mark_rendered(self, ids):
        with self.db:
            self.db.executemany("UPDATE jobs SET status='rendered' WHERE id=?", [(i,) for i in ids])

    def status(self):
        return [dict(r) for r in self.db.execute(
            "SELECT id, status, attempts, created_at, error FROM jobs ORDER BY created_at DESC, id")]

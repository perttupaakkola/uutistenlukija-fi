"""One local SQLite job table; saved drafts survive interrupted ticks."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .editorial import digest, encode, web_url


COLLECTION_BACKOFF_SECONDS = 6 * 60 * 60
COLLECTION_FAILURE_TTL_SECONDS = 7 * 24 * 60 * 60
PERMANENT_COLLECTION_ERRORS = (
    "stale or future-dated",
    "aggregator/hub page",
    "title mismatch",
)

JOBS_SCHEMA = """(
        id TEXT PRIMARY KEY, story_key TEXT NOT NULL UNIQUE,
        source_url TEXT NOT NULL, packet TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ready', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0, draft TEXT, review TEXT,
        adapter TEXT, created_at TEXT NOT NULL, error TEXT
    )"""


def _allow_shared_source_urls(db):
    """Remove the legacy URL uniqueness while preserving story-key deduplication.

    Structured FMI groups intentionally cite the same official warning page.  Existing
    URL-keyed sources remain deduplicated because their story key is ``url:<source>``.
    """
    unique_source = False
    for index in db.execute("PRAGMA index_list('jobs')"):
        if index[2] and [row[2] for row in db.execute(f"PRAGMA index_info('{index[1]}')")] == ['source_url']:
            unique_source = True
            break
    if not unique_source:
        return
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='jobs_shared_url_transition'").fetchone():
        raise ValueError('Unresolved jobs source-URL migration')
    with db:
        db.execute('CREATE TABLE jobs_shared_url_transition '+JOBS_SCHEMA)
        db.execute("INSERT INTO jobs_shared_url_transition "
                   "(id,story_key,source_url,packet,status,attempts,next_attempt,draft,review,adapter,created_at,error) "
                   "SELECT id,story_key,source_url,packet,status,attempts,next_attempt,draft,review,adapter,created_at,error FROM jobs")
        db.execute('DROP TABLE jobs')
        db.execute('ALTER TABLE jobs_shared_url_transition RENAME TO jobs')


@contextmanager
def database(state_dir):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(Path(state_dir) / "jobs.sqlite", timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE IF NOT EXISTS jobs "+JOBS_SCHEMA)
    _allow_shared_source_urls(db)
    db.execute("""CREATE TABLE IF NOT EXISTS collection_failures (
        url TEXT PRIMARY KEY, provider TEXT NOT NULL, error TEXT NOT NULL,
        first_seen REAL NOT NULL, last_seen REAL NOT NULL,
        count INTEGER NOT NULL DEFAULT 1
    )""")
    db.commit()
    try:
        yield Store(db)
    finally:
        db.close()


IMAGE_RETRY_WINDOW = 3 * 3600
# Hard deadline: a story still waiting only for an image this long after admission is
# closed as failed, even if it never got another turn (image retries yield to new stories,
# so attempt counting alone can leave it waiting forever; 29 Oct).
IMAGE_PENDING_MAX_AGE = 4 * 3600

class Store:
    def __init__(self, db):
        self.db = db

    def admit(self, packet, created_at):
        identity = digest(packet["story_key"])
        primary = web_url(packet["sources"][0]["url"])
        shared_fmi_page = (packet["story_key"].startswith('fmi-warning:') and
                           primary == 'https://www.ilmatieteenlaitos.fi/varoitukset')
        with self.db:
            row = self.db.execute(
                "SELECT id FROM jobs WHERE story_key=? OR (?=0 AND source_url=?)",
                (packet["story_key"], int(shared_fmi_page), primary)).fetchone()
            if row is not None:
                return row["id"], False
            self.db.execute("""INSERT INTO jobs
                (id, story_key, source_url, packet, created_at) VALUES (?, ?, ?, ?, ?)""",
                (identity, packet["story_key"], primary, encode(packet), created_at))
            added = True
            row = self.db.execute("SELECT id FROM jobs WHERE story_key=?",
                                  (packet["story_key"],)).fetchone()
        return row["id"], added

    def record_collection_failure(self, url, provider, error, now=None):
        """Remember a bounded collector failure even though no job could be admitted."""
        now = time.time() if now is None else now
        url = web_url(url)
        with self.db:
            self.db.execute(
                """INSERT INTO collection_failures
                   (url,provider,error,first_seen,last_seen,count) VALUES(?,?,?,?,?,1)
                   ON CONFLICT(url) DO UPDATE SET provider=excluded.provider,
                   error=excluded.error,last_seen=excluded.last_seen,count=count+1""",
                (url, provider, error, now, now))

    def clear_collection_failure(self, url):
        with self.db:
            self.db.execute("DELETE FROM collection_failures WHERE url=?", (web_url(url),))

    def collection_failure_urls(self, now=None):
        """URLs still in content quarantine or transient retry backoff.

        Content failures are suppressed for seven days. Other failures retry after six
        hours, but three failures enter the same seven-day quarantine. Expired rows are
        removed so a mistaken classification can never hide a source permanently.
        """
        now = time.time() if now is None else now
        with self.db:
            self.db.execute("DELETE FROM collection_failures WHERE last_seen<=?",
                            (now - COLLECTION_FAILURE_TTL_SECONDS,))
        excluded = set()
        for row in self.db.execute("SELECT url,error,last_seen,count FROM collection_failures"):
            permanent = any(marker in row["error"].casefold()
                            for marker in PERMANENT_COLLECTION_ERRORS)
            if permanent or row["count"] >= 3 or now < row["last_seen"] + COLLECTION_BACKOFF_SECONDS:
                excluded.add(row["url"])
        return excluded

    def recover(self, max_attempts):
        # Called only after the controller has acquired the process lock.
        with self.db:
            self.db.execute("""UPDATE jobs SET status=CASE WHEN attempts>=? THEN 'failed' ELSE 'ready' END,
                error='Interrupted tick; saved draft retained' WHERE status='running'""", (max_attempts,))

    def claim(self, now, max_attempts, job_id=None):
        with self.db:
            row = self.db.execute("""SELECT * FROM jobs WHERE status='ready'
                AND next_attempt<=? AND attempts<? AND (? IS NULL OR id=?)
                ORDER BY next_attempt, created_at, id LIMIT 1""",
                (now, max_attempts, job_id, job_id)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (row["id"],))
        return self.get(row["id"])

    def save_draft(self, job_id, draft, adapter):
        with self.db:
            self.db.execute("UPDATE jobs SET draft=?, adapter=? WHERE id=?", (encode(draft), adapter, job_id))

    def save_packet(self, job_id, packet):
        """Attach reviewed evidence (currently the generated illustration) to a stored packet.

        Only the packet's own identity fields are preserved; story_key and source_url drive
        admission and must not change. Used by the controller after the writer returns, so the
        draft and packet agree on the image record and the reviewer sees the same contract.
        """
        with self.db:
            row = self.db.execute("SELECT story_key, source_url FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Cannot attach a packet to an unknown job")
            if packet.get("story_key") != row["story_key"]:
                raise ValueError("Attached packet must keep the job's story identity")
            if (packet.get("sources") or [{}])[0].get("url") != row["source_url"]:
                raise ValueError("Attached packet must keep the job's primary source")
            self.db.execute("UPDATE jobs SET packet=? WHERE id=?", (encode(packet), job_id))

    def finish_review(self, job_id, review):
        with self.db:
            self.db.execute("UPDATE jobs SET review=?, status=?, error=NULL WHERE id=?",
                            (encode(review), "approved" if review["approved"] else "rejected", job_id))

    def save_reviewed_image(self, job_id, packet, draft, review,
                            previous_packet_sha, previous_draft_sha):
        """Atomically attach a freshly reviewed image, including a deployed correction.

        A backfill is allowed to change only the image-bearing packet/draft pair that the
        publication row already names. If the stored hashes moved underneath the controller,
        or the job has another unresolved publication, the transaction fails closed. A deployed
        row is then put back through the ordinary publication state machine with the new hashes;
        the old public bundle remains live until that release passes its normal checks.
        """
        image = packet.get("image")
        image_sha = (image.get("sha256") if isinstance(image, dict) and image.get("local_path")
                     else None)
        packet_json, draft_json, review_json = encode(packet), encode(draft), encode(review)
        with self.db:
            row = self.db.execute("SELECT packet,draft,status FROM jobs WHERE id=?",
                                  (job_id,)).fetchone()
            if row is None:
                raise ValueError("Cannot attach an image to an unknown job")
            if digest(json.loads(row["packet"])) != previous_packet_sha:
                raise ValueError("Image backfill packet changed during preparation")
            if digest(json.loads(row["draft"])) != previous_draft_sha:
                raise ValueError("Image backfill draft changed during preparation")
            if row["status"] not in ("approved", "rendered"):
                raise ValueError("Image backfill requires a rendered or approved story")

            publication_table = self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'"
            ).fetchone()
            publication = (self.db.execute(
                "SELECT * FROM publications WHERE job_id=?", (job_id,)).fetchone()
                           if publication_table else None)
            if publication is not None and publication["status"] != "deployed":
                raise ValueError("Image backfill cannot change an unresolved publication")
            if publication is not None:
                if (publication["packet_sha"] != previous_packet_sha or
                        publication["draft_sha"] != previous_draft_sha or
                        publication["image_sha"] is not None):
                    raise ValueError("Image backfill publication identity changed")

            self.db.execute("UPDATE jobs SET packet=?,draft=?,review=?,status='approved',error=NULL "
                            "WHERE id=?", (packet_json, draft_json, review_json, job_id))
            if publication is not None:
                self.db.execute(
                    "UPDATE publications SET packet_sha=?,draft_sha=?,image_sha=?,status='preparing',"
                    "attempts=0,remote_commit=NULL,run_id=NULL,error=NULL WHERE job_id=?",
                    (digest(packet), digest(draft), image_sha, job_id))

    def fail(self, job_id, now, max_attempts, retry_seconds, error):
        row = self.get(job_id)
        with self.db:
            self.db.execute("UPDATE jobs SET status=?, next_attempt=?, error=? WHERE id=?",
                            ("failed" if row["attempts"] >= max_attempts else "ready",
                             now + retry_seconds * row["attempts"], error, job_id))

    def expire_image_pending(self, now, max_age=IMAGE_PENDING_MAX_AGE):
        """Fail ready stories that have waited only for an image beyond max_age seconds.

        Jobs with any publication row are never touched."""
        from datetime import datetime, timezone
        cutoff = datetime.fromtimestamp(now - max_age, timezone.utc).isoformat()
        with self.db:
            cur = self.db.execute(
                "UPDATE jobs SET status='failed', error='Image pending expired: ' || error "
                "WHERE status='ready' AND error LIKE 'Image pending%' AND created_at < ? "
                "AND id NOT IN (SELECT job_id FROM publications)", (cutoff,))
        return cur.rowcount

    def defer_image(self, job_id, now, retry_seconds, error):
        """A bounded image attempt is not terminal editorial failure; retain its draft."""
        # Image retries are free only for IMAGE_RETRY_WINDOW seconds after the job was
        # created. After that each deferral counts as an attempt, so a story whose image
        # keeps failing exhausts max_attempts instead of blocking every newer story forever.
        from datetime import datetime, timezone
        cutoff = datetime.fromtimestamp(now - IMAGE_RETRY_WINDOW, timezone.utc).isoformat()
        with self.db:
            self.db.execute("UPDATE jobs SET status='ready', "
                            "attempts=CASE WHEN created_at < ? THEN attempts ELSE MAX(0,attempts-1) END, "
                            "next_attempt=?, error=? WHERE id=?",
                            (cutoff, now + retry_seconds, error, job_id))

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

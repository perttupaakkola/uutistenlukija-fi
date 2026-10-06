"""Non-activating published-amendment preparation boundaries.

No CLI or production caller yet: this module cannot authorize, install or release
an amendment. Reconstruct both captures and obtain fresh full review downstream.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re


PUBLICATION_COLUMNS = ('job_id', 'packet_sha', 'draft_sha', 'image_sha',
                       'source_commit', 'remote_commit', 'run_id', 'status',
                       'attempts', 'error')


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('Amendment requires an exact SHA256 identity')
    return value


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CaptureBinding:
    """Hashes only; no mutable packet dictionaries or untrusted filesystem paths."""
    packet_sha256: str
    receipt_sha256: str

    def __post_init__(self):
        _sha(self.packet_sha256)
        _sha(self.receipt_sha256)

    def verify_bytes(self, packet_bytes, receipt_bytes):
        for raw, expected in ((packet_bytes, self.packet_sha256),
                              (receipt_bytes, self.receipt_sha256)):
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError('Amendment capture bytes changed')
        # Hash integrity is not collect/reconstruction or rights acceptance.


@dataclass(frozen=True)
class AmendmentEvidence:
    schema: str
    job_id: str
    predecessor_packet_sha256: str
    predecessor_draft_sha256: str
    predecessor_publication_sha256: str
    original_capture: CaptureBinding
    update_capture: CaptureBinding
    reason: str
    updated_at: str

    def __post_init__(self):
        if self.schema != 'published-amendment-preparation-v1':
            raise ValueError('Unknown amendment preparation schema')
        for value in (self.job_id, self.predecessor_packet_sha256,
                      self.predecessor_draft_sha256, self.predecessor_publication_sha256):
            _sha(value)
        if type(self.original_capture) is not CaptureBinding or type(self.update_capture) is not CaptureBinding:
            raise ValueError('Amendment captures must be typed immutable bindings')
        if self.original_capture == self.update_capture:
            raise ValueError('Amendment requires distinct captured update evidence')
        if not isinstance(self.reason, str) or not self.reason.strip() or len(self.reason) > 2000:
            raise ValueError('Amendment needs a bounded explicit reason')
        try:
            date = datetime.fromisoformat(self.updated_at)
        except (ValueError, TypeError):
            raise ValueError('Amendment needs an explicit update instant') from None
        if date.tzinfo is None or date.utcoffset() is None:
            raise ValueError('Amendment update instant needs a timezone')


def predecessor_snapshot(db, evidence):
    """Read-only preflight, NOT a CAS activation fence or approval.

    Caller must still hold controller ownership and recheck inside the eventual
    BEGIN IMMEDIATE activation transaction. No database/schema creation here.
    """
    if type(evidence) is not AmendmentEvidence:
        raise ValueError('Typed amendment evidence required')
    expected = tuple(zip(PUBLICATION_COLUMNS,
                         ('TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'INTEGER', 'TEXT', 'INTEGER', 'TEXT'),
                         (0, 1, 1, 0, 1, 0, 0, 1, 1, 0),
                         (1, 0, 0, 0, 0, 0, 0, 0, 0, 0)))
    actual = tuple((r[1], r[2].upper(), r[3], r[5]) for r in db.execute('PRAGMA table_info(publications)'))
    if actual != expected:
        raise ValueError('Unknown publication schema; refuse amendment preparation')
    if db.execute("SELECT 1 FROM publications WHERE typeof(status)='null' OR status NOT IN ('deployed','failed') LIMIT 1").fetchone():
        raise ValueError('Unresolved publication blocks amendment preparation')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='image_backfill_batches'").fetchone():
        expected_batch = tuple(zip(
            ('batch_id', 'anchor_job_id', 'source_commit', 'records', 'status', 'created_at', 'remote_commit', 'run_id'),
            ('TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'TEXT', 'INTEGER'),
            (0, 1, 1, 1, 1, 1, 0, 0), (1, 0, 0, 0, 0, 0, 0, 0)))
        actual_batch = tuple((r[1], r[2].upper(), r[3], r[5]) for r in db.execute('PRAGMA table_info(image_backfill_batches)'))
        if actual_batch != expected_batch or db.execute("SELECT 1 FROM image_backfill_batches WHERE typeof(status)='null' OR status!='deployed' LIMIT 1").fetchone():
            raise ValueError('Unknown or active archive batch blocks amendment preparation')
    job_cursor = db.execute('SELECT * FROM jobs WHERE id=?', (evidence.job_id,))
    row = job_cursor.fetchone()
    if row is None:
        raise ValueError('Unknown amendment target')
    job = dict(zip((d[0] for d in job_cursor.description), row))
    pub_cursor = db.execute('SELECT * FROM publications WHERE job_id=?', (evidence.job_id,))
    row = pub_cursor.fetchone()
    if row is None:
        raise ValueError('Amendment requires a deployed predecessor')
    publication = dict(zip((d[0] for d in pub_cursor.description), row))
    if publication['status'] != 'deployed' or job.get('status') != 'rendered':
        raise ValueError('Amendment requires a rendered deployed predecessor')
    try:
        packet = json.loads(job['packet'])
        draft = json.loads(job['draft'])
        published = datetime.fromisoformat(job['created_at'])
        updated = datetime.fromisoformat(evidence.updated_at)
    except (ValueError, TypeError, KeyError):
        raise ValueError('Invalid amendment predecessor') from None
    if published.tzinfo is None or updated <= published:
        raise ValueError('Amendment must follow original publication instant')
    if (_digest(packet) != evidence.predecessor_packet_sha256 or
            _digest(draft) != evidence.predecessor_draft_sha256 or
            _digest(publication) != evidence.predecessor_publication_sha256 or
            publication['packet_sha'] != evidence.predecessor_packet_sha256 or
            publication['draft_sha'] != evidence.predecessor_draft_sha256):
        raise ValueError('Amendment predecessor moved')
    return {'job': job, 'publication': publication}

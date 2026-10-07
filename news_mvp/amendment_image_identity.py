"""Read-only same-job retained-image identity; never image approval or activation."""
import json

from .amendments import predecessor_snapshot, _sha
from .imagery import _rejected_image_hashes

MAX_IMAGE_OWNERS = 10000
MAX_DRAFT_BYTES = 256 * 1024


def _image_sha(image):
    if image is None:
        return None
    if type(image) is not dict:
        raise ValueError('Invalid stored image identity')
    if not image:
        return None
    review = image.get('pixel_review')
    if review is not None and type(review) is not dict:
        raise ValueError('Invalid stored pixel identity')
    pixel_sha = review.get('image_sha256') if type(review) is dict else None
    declared_sha = image.get('sha256')
    if declared_sha is not None:
        _sha(declared_sha)
    value = declared_sha or pixel_sha
    if value is None and image.get('hotlink') is True and image.get('generated') is False:
        from .editorial import web_url
        web_url(image.get('url'))
        # Ordinary duplicate inventory also has no byte identity for these
        # historical hotlinks. Report the gap; do not fabricate their hashes.
        return None
    sha = _sha(value)
    if review is not None:
        if type(review) is not dict:
            raise ValueError('Invalid stored pixel identity')
        pixel_sha = review.get('image_sha256')
        if pixel_sha is not None and _sha(pixel_sha) != sha:
            raise ValueError('Ambiguous stored image identity')
    return sha


def retained_image_identity(db, evidence, image, state_dir):
    """Preflight the immutable predecessor and every other job, including rejects.

    Caller supplies its read-only SQLite connection and owns a consistent read
    transaction. This does not authenticate local/network bytes or source rights,
    perform fresh concepts/searches/pixel review, authorize release or implement CAS.
    Ordinary publication's text-based duplicate helper remains unchanged.
    """
    if not db.in_transaction:
        raise ValueError('Consistent caller-owned read transaction required')
    snapshot = predecessor_snapshot(db, evidence)
    before = json.loads(snapshot['job']['draft'])
    if type(before) is not dict or image != before.get('image'):
        raise ValueError('Only exact retained predecessor image is eligible')
    sha = _image_sha(image)
    if sha is None or snapshot['publication']['image_sha'] != sha:
        raise ValueError('Retained image does not match deployed identity')
    info = {row[1]: row for row in db.execute('PRAGMA table_info(jobs)')}
    if ([row[1] for row in info.values() if row[5]] != ['id']
            or 'id' not in info or info['id'][2].upper() != 'TEXT' or info['id'][5] != 1
            or 'draft' not in info or info['draft'][2].upper() != 'TEXT'):
        raise ValueError('Unknown job image ownership schema')
    rows = db.execute('SELECT id,draft FROM jobs WHERE draft IS NOT NULL LIMIT ?',
                      (MAX_IMAGE_OWNERS + 1,)).fetchall()
    if len(rows) > MAX_IMAGE_OWNERS:
        raise ValueError('Image ownership inventory exceeds bound')
    excluded = set()
    unhashed_hotlinks = 0
    target_seen = 0
    for owner, raw in rows:
        _sha(owner)
        if type(raw) is not str or len(raw.encode('utf-8')) > MAX_DRAFT_BYTES:
            raise ValueError('Stored draft identity unavailable or oversized')
        other = json.loads(raw)
        if type(other) is not dict:
            raise ValueError('Stored draft identity must be an object')
        other_sha = _image_sha(other.get('image'))
        if owner == evidence.job_id:
            target_seen += 1
            if other != before or other_sha != sha:
                raise ValueError('Retained predecessor image moved')
        elif other_sha:
            # No identical-text exemption: immutable job identity is the boundary.
            excluded.add(other_sha)
        elif other.get('image'):
            other_image = other['image']
            urls = {image.get(key) for key in ('url','source_url') if image.get(key)}
            if urls.intersection(other_image.get(key) for key in ('url','source_url') if other_image.get(key)):
                raise ValueError('Retained source image belongs to another job')
            unhashed_hotlinks += 1
    if target_seen != 1:
        raise ValueError('Ambiguous retained-image owner')
    excluded.update(_rejected_image_hashes(state_dir))
    if sha in excluded:
        raise ValueError('Retained image belongs to another job or was rejected')
    return {'image_sha256': sha, 'predecessor_job_id': evidence.job_id,
            'excluded_image_sha256': sorted(excluded),
            'unhashed_historical_hotlink_count': unhashed_hotlinks,
            'exhaustive_cross_image_byte_comparison': False,
            'scope': 'identity preflight only', 'normal_approval': False,
            'fresh_pixel_approval': False, 'activation': False,
            'release_authorization': False}

"""One guarded archive correction batch through the retained publication writer.

Images/reviews are prepared before activation. Historical records are retained in
the batch, and all corrected articles are committed/deployed as one static release.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from .editorial import digest, encode, validate_draft, validate_review
from .release_contract import media, verify_intake, check_article
from .site import article_path, atomic_write, display_image


def _exists(store):
    return store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='image_backfill_batches'").fetchone() is not None


def active(store, anchor=None):
    if not _exists(store):
        return None
    rows = store.db.execute("SELECT * FROM image_backfill_batches WHERE status='active'").fetchall()
    if len(rows) > 1:
        raise ValueError('More than one archive correction writer')
    if not rows or (anchor is not None and rows[0]['anchor_job_id'] != anchor):
        return None
    return dict(rows[0])


def members(store, anchor):
    batch = active(store, anchor)
    return json.loads(batch['records']) if batch else []


def pending(store):
    """Return unresolved publication anchors; linked children are not extra writers."""
    rows = store.db.execute("SELECT job_id,status FROM publications WHERE status NOT IN ('deployed','failed') ORDER BY rowid").fetchall()
    batch = active(store)
    if not batch:
        return rows
    records = json.loads(batch['records'])
    children = {r['job_id'] for r in records} - {batch['anchor_job_id']}
    anchor = store.db.execute('SELECT job_id,status FROM publications WHERE job_id=?',
                              (batch['anchor_job_id'],)).fetchone()
    if anchor is None or anchor['status']=='deployed':
        raise ValueError('Active archive correction has no unresolved anchor')
    for row in rows:
        if row['job_id'] in children and row['status'] != 'backfill_prepared':
            raise ValueError('Archive correction child state changed')
    anchors = [row for row in rows if row['job_id'] not in children]
    if anchor['status']=='failed':
        # Confirmed failure remains owned by this batch until explicit reconciliation.
        # Never let a failed anchor make its prepared children disappear from the queue.
        anchors.append(anchor)
    return anchors


def install(store, entries, prepared_dir, state, source_commit):
    """Caller owns controller.lock; apply only exact reviewed image-only changes."""
    if not entries or len(entries) > 250 or pending(store):
        raise ValueError('Archive correction needs a bounded batch and an idle publisher')
    records = []
    seen = set()
    images = set()
    for entry in entries:
        identifier = entry['job_id']
        if identifier in seen:
            raise ValueError('Duplicate archive correction job')
        seen.add(identifier)
        job = store.get(identifier)
        publication = store.db.execute('SELECT * FROM publications WHERE job_id=?', (identifier,)).fetchone()
        if not job or not publication or publication['status'] != 'deployed':
            raise ValueError('Only deployed articles can be backfilled')
        before_packet, before_draft = json.loads(job['packet']), json.loads(job['draft'])
        packet, draft, review = entry['packet'], entry['draft'], entry['review']
        if (digest(before_packet) != entry['previous_packet_sha'] or digest(before_draft) != entry['previous_draft_sha'] or
                publication['packet_sha'] != entry['previous_packet_sha'] or publication['draft_sha'] != entry['previous_draft_sha']):
            raise ValueError('Archive correction changed during preparation')
        without_image = lambda value: {k:v for k,v in value.items() if k not in ('image','image_note')}
        if without_image(packet) != without_image(before_packet) or without_image(draft) != without_image(before_draft):
            raise ValueError('Archive correction may change only image fields')
        image = display_image(draft.get('image'))
        if not image:
            raise ValueError('Archive correction must supply a relevant image')
        validate_draft(draft, packet)
        if not validate_review(review, draft)['approved']:
            raise ValueError('Archive correction image is not approved')
        scope = review.get('archive_image_only')
        if scope is not None:
            original_review = json.loads(job['review'])
            if (not validate_review(original_review, before_draft)['approved'] or
                    scope.get('original_draft_sha256') != digest(before_draft) or
                    scope.get('original_review_sha256') != digest(original_review) or
                    scope.get('unchanged_text_sha256') != digest(without_image(before_draft)) or
                    scope.get('original_published_at') != job['created_at']):
                raise ValueError('Archive image review original approval binding changed')
        from .imagery import validate_pixel_review
        pixels = validate_pixel_review(image, draft)
        if pixels['image_sha256'] in images:
            raise ValueError('Archive correction reuses an image across articles')
        images.add(pixels['image_sha256'])
        binding = media(packet, draft, policy_gate=False)
        if packet.get('publication_basis') is not None:
            verify_intake(packet, state, archive_image_only=True)
        if image.get('local_path'):
            path = Path(prepared_dir) / image['local_path']
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != image['sha256']:
                raise ValueError('Prepared image bytes changed')
            atomic_write(Path(state) / image['local_path'], raw)
        records.append({'job_id':identifier, 'packet':packet, 'draft':draft, 'review':review,
            'packet_sha256':digest(packet), 'draft_sha256':digest(draft), **binding,
            'article_file':article_path(job)+'index.html',
            'previous_job':job, 'previous_publication':dict(publication)})
    anchor = max(records, key=lambda r:(r['previous_job']['created_at'], r['job_id']))['job_id']
    batch_id = digest(records)
    with store.db:
        store.db.execute('CREATE TABLE IF NOT EXISTS image_backfill_batches '
            '(batch_id TEXT PRIMARY KEY, anchor_job_id TEXT NOT NULL, source_commit TEXT NOT NULL, '
            'records TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, remote_commit TEXT, run_id INTEGER)')
        store.db.execute('INSERT INTO image_backfill_batches VALUES(?,?,?,?,?,?,NULL,NULL)',
            (batch_id,anchor,source_commit,encode(records),'active',datetime.now(timezone.utc).isoformat()))
        for r in records:
            store.db.execute("UPDATE jobs SET packet=?,draft=?,review=?,status='approved',error=NULL WHERE id=?",
                (encode(r['packet']),encode(r['draft']),encode(r['review']),r['job_id']))
            store.db.execute("UPDATE publications SET packet_sha=?,draft_sha=?,image_sha=?,source_commit=?,"
                "status=?,attempts=0,remote_commit=NULL,run_id=NULL,error=NULL WHERE job_id=?",
                (r['packet_sha256'],r['draft_sha256'],r['image_sha256'],source_commit,
                 'preparing' if r['job_id']==anchor else 'backfill_prepared',r['job_id']))
    return anchor


def release_records(store, anchor):
    return [{k:v for k,v in r.items() if not k.startswith('previous_')} for r in members(store,anchor)]


def validate_records(root, records):
    """Workflow verification of every exact image-bearing reviewed article."""
    seen = set()
    for r in records:
        if r['job_id'] in seen:
            raise ValueError('Duplicate image-backfill release record')
        seen.add(r['job_id'])
        if digest(r['packet']) != r['packet_sha256'] or digest(r['draft']) != r['draft_sha256']:
            raise ValueError('Image-backfill release record changed')
        if not validate_review(r['review'],r['draft'])['approved']:
            raise ValueError('Image-backfill review rejected')
        if not display_image(r['draft'].get('image')):
            raise ValueError('Image-backfill release is text-only')
        binding = media(r['packet'],r['draft'],policy_gate=False)
        if any(r.get(k) != v for k,v in binding.items()):
            raise ValueError('Image-backfill media binding changed')
        path = Path(root) / r['article_file']
        if not path.resolve().is_relative_to(Path(root).resolve()):
            raise ValueError('Invalid image-backfill article path')
        check_article(path.read_text(),r['packet'],r['draft'])
        image = r['draft']['image']
        from .imagery import validate_pixel_review
        validate_pixel_review(image,r['draft'])
        if image.get('local_path'):
            data = (Path(root)/('mvp-assets/'+r['image_sha256']+'.jpg')).read_bytes()
            if hashlib.sha256(data).hexdigest()!=r['image_sha256']:
                raise ValueError('Image-backfill bundle pixels changed')


def complete(store, anchor, remote, run_id, live_read):
    records = members(store,anchor)
    if not records:
        return
    # Read every changed canonical article and exact image before committing completion.
    for r in records:
        html = live_read('https://uutistenlukija.fi/'+r['article_file']).decode()
        check_article(html,r['packet'],r['draft'])
        image = r['draft']['image']
        sha = r['image_sha256'] or image['pixel_review']['image_sha256']
        url = ('https://uutistenlukija.fi/mvp-assets/'+sha+'.jpg') if image.get('local_path') else image['url']
        if hashlib.sha256(live_read(url)).hexdigest()!=sha:
            raise ValueError('Archive image live bytes mismatch')
    with store.db:
        for r in records:
            row = store.db.execute('SELECT * FROM publications WHERE job_id=?',(r['job_id'],)).fetchone()
            if row['packet_sha']!=r['packet_sha256'] or row['draft_sha']!=r['draft_sha256']:
                raise ValueError('Archive correction identity changed before completion')
            store.db.execute("UPDATE publications SET status='deployed',remote_commit=?,run_id=?,error=NULL WHERE job_id=?",
                (remote,run_id,r['job_id']))
        store.db.execute("UPDATE image_backfill_batches SET status='deployed',remote_commit=?,run_id=? WHERE anchor_job_id=? AND status='active'",
            (remote,run_id,anchor))

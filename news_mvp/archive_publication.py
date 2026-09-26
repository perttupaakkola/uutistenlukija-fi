"""Read-only proof for a live archive article with a historical failed job.

An old workflow failure is never retried or erased here. A later successful
release must independently contain the exact canonical article and image, and
the current host must serve those immutable hashes before image-only recovery.
"""
import hashlib
import json
import re
from html import escape

from .editorial import digest, validate_review
from .site import article_path


def verify(store, job, publication, evidence, live_read):
    if publication['status'] != 'failed' or not callable(live_read) or not isinstance(evidence, dict):
        raise ValueError('Historical failed article requires current canonical deployment proof')
    raw = evidence['release_bytes']
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != evidence['release_sha256']:
        raise ValueError('Canonical archive release bytes changed')
    release = json.loads(raw)
    pages, run = evidence['pages'], evidence['workflow']
    if (release.get('public_release_authorized') is not True or
            run.get('status') != 'completed' or run.get('conclusion') != 'success' or
            run.get('event') != 'workflow_dispatch' or
            not re.fullmatch('[a-f0-9]{40}', str(run.get('headSha', ''))) or
            pages.get('remote_commit') != run['headSha'] or
            pages.get('canonical_origin') != 'https://uutistenlukija.fi' or
            release.get('origin') != pages['canonical_origin'] or not pages.get('deployment_id')):
        raise ValueError('Canonical archive deployment is not a bound successful production release')
    for key in ('source_commit', 'job_id', 'packet_sha256', 'draft_sha256', 'image_sha256',
                'text_only', 'text_provenance', 'image_backfill_sha256'):
        if (key in release) != (key in pages) or release.get(key) != pages.get(key):
            raise ValueError('Canonical archive Pages/release identity mismatch')
    records = release.get('image_backfill', [])
    declared = {release['job_id']}
    if records:
        if digest(records) != release.get('image_backfill_sha256'):
            raise ValueError('Canonical archive batch digest mismatch')
        declared.update(r['job_id'] for r in records)
    matches = store.db.execute('SELECT * FROM publications WHERE remote_commit=? OR run_id=? OR job_id=?',
        (run['headSha'], run['databaseId'], release['job_id'])).fetchall()
    anchors = [r for r in matches if r['job_id'] == release['job_id']]
    if len(anchors) != 1 or any(r['job_id'] not in declared for r in matches):
        raise ValueError('Canonical archive deployment publication identity is ambiguous')
    anchor = anchors[0]
    expected = {'status':'deployed', 'remote_commit':run['headSha'], 'run_id':run['databaseId'],
        'source_commit':release['source_commit'], 'packet_sha':release['packet_sha256'],
        'draft_sha':release['draft_sha256'], 'image_sha':release['image_sha256']}
    if any(anchor[k] != value for k, value in expected.items()):
        raise ValueError('Canonical archive deployment is not locally reconciled')
    packet, draft = json.loads(job['packet']), json.loads(job['draft'])
    if (publication['packet_sha'] != digest(packet) or publication['draft_sha'] != digest(draft) or
            not validate_review(json.loads(job['review']), draft)['approved'] or
            packet.get('image') != draft.get('image')):
        raise ValueError('Historical article approval or stored hashes changed')
    image = draft.get('image') or {}
    sha = image.get('sha256')
    if not re.fullmatch('[a-f0-9]{64}', str(sha)) or publication['image_sha'] != sha:
        raise ValueError('Historical article has no exact local image identity')
    # This proves what is already live, not whether the old image meets today's
    # publication policy. Old releases may predate independent pixel review.
    # install() still requires a fresh valid review on every replacement.
    if image.get('pixel_review') is not None:
        from .imagery import validate_pixel_review
        validate_pixel_review(image, draft)
    path = article_path(job) + 'index.html'
    asset = 'mvp-assets/' + sha + '.jpg'
    files = release['files']
    if not re.fullmatch('[a-f0-9]{64}', str(files.get(path))) or files.get(asset) != sha:
        raise ValueError('Historical canonical article/image absent from current release')
    canonical = release['origin'] + '/' + path.removesuffix('index.html')
    html_bytes = live_read(canonical)
    pixels = live_read(release['origin'] + '/' + asset)
    if hashlib.sha256(html_bytes).hexdigest() != files[path] or hashlib.sha256(pixels).hexdigest() != sha:
        raise ValueError('Historical canonical live bytes differ from current release')
    from .publish import _canonical_links
    from .release_contract import _ImageSources, _denormalize_cdn_email_obfuscation
    html = _denormalize_cdn_email_obfuscation(html_bytes.decode('utf-8'))
    if _canonical_links(html) != [canonical]:
        raise ValueError('Historical canonical URL is missing or ambiguous')
    required = [draft['title'], draft['summary']] + [p['text'] for p in draft['paragraphs']]
    required += [s['url'] for s in packet['sources']]
    if any(escape(str(value), quote=True) not in html for value in required):
        raise ValueError('Historical canonical text/source differs from approved article')
    parser = _ImageSources()
    parser.feed(html)
    parser.close()
    heroes = [item for item in parser.images if not item['chrome']]
    if (len(heroes) != 1 or heroes[0]['src'] != '/' + asset or heroes[0]['alt'] != image['alt'] or
            parser.has_alternative or any(i['duplicate'] or i['srcset'] or i['alternative'] for i in parser.images)):
        raise ValueError('Historical canonical image identity/alt is ambiguous')
    return {'operation':'recover_already_live_article_for_image_only_correction',
        'job_id':job['id'], 'previous_publication_sha256':digest(dict(publication)),
        'release_sha256':evidence['release_sha256'], 'remote_commit':run['headSha'],
        'run_id':run['databaseId'], 'deployment_id':pages['deployment_id'],
        'article_file':path, 'article_sha256':files[path], 'image_sha256':sha,
        'packet_sha256':digest(packet), 'draft_sha256':digest(draft)}

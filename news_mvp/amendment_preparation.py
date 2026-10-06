"""Private candidate: two-capture preparation, never approval or activation.

Caller owns the controller lease and provides an existing private output directory.
No schema, job, publication, release or canonical path is written. Production
reconstruction has no override parameter. Tests patch the internal boundary only.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import uuid

from news_mvp.amendments import AmendmentEvidence, CaptureBinding, predecessor_snapshot

MAX_INPUT = 192 * 1024
MAX_ARTIFACT = 256 * 1024
MAX_CAPTURE = 64 * 1024
MAX_HTML = 512 * 1024  # Both unchanged pilot source HTML captures fit; never truncate.


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _object(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('Duplicate JSON key')
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    if type(value) is not dict:
        raise ValueError('Expected JSON object')
    return value


def _directory(path, private=False):
    """Pin directory descriptors; reject symlinks in every path component."""
    if '..' in Path(path).parts:
        raise ValueError('Parent traversal is forbidden')
    path = Path(os.path.abspath(os.fspath(path)))
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        info = os.fstat(fd)
        if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('Artifact directory must be owned and private (0700)')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_at(fd, name, maximum=MAX_CAPTURE):
    leaf = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(leaf)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('Capture file must be bounded and regular')
        with os.fdopen(leaf, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('Capture too large')
        return raw
    finally:
        os.close(leaf)


def _reconstruct(packet, draft, packet_raw, receipt_raw, state):
    """Installed verifier plus policy gate and exact on-disk capture identities.

    Matching receipts/hashes alone are not licensing proof. verify_intake must
    independently reproduce source and rights HTML for EACH capture; neither
    archive_image_only nor policy_gate=False is used here.
    """
    from news_mvp.release_contract import digest, media, verify_intake
    directory = Path(state) / 'intake' / digest(packet)
    fd = _directory(directory)
    try:
        if _read_at(fd, 'packet.json') != packet_raw or _read_at(fd, 'receipt.json') != receipt_raw:
            raise ValueError('Exact intake packet/receipt bytes differ')
        # Refuse capture symlinks before the installed verifier reads these files.
        _read_at(fd, 'source.html', MAX_HTML)
        _read_at(fd, 'rights.html', MAX_HTML)
        media(packet, draft)
        if verify_intake(packet, state) is not None:
            raise ValueError('Installed verifier contract is exception-or-None, not callback licensing proof')
    finally:
        os.close(fd)


def _projection(packet):
    return {key: value for key, value in packet.items() if key not in ('image','image_note')}


def _manuscript(candidate, predecessor, source_ids):
    if type(candidate) is not dict or set(candidate) != {'category','title','summary','paragraphs'}:
        raise ValueError('Candidate has unknown/missing fields')
    for field, maximum in (('category',100),('title',300),('summary',3000)):
        value = candidate[field]
        if type(value) is not str or not value.strip() or len(value) > maximum:
            raise ValueError('Candidate text must be bounded and nonempty')
    if any(candidate[key] != predecessor[key] for key in ('title','category')):
        raise ValueError('Title/category must remain unchanged')
    paragraphs = candidate['paragraphs']
    if type(paragraphs) is not list or not 1 <= len(paragraphs) <= 40:
        raise ValueError('Candidate needs bounded sourced paragraphs')
    for paragraph in paragraphs:
        if type(paragraph) is not dict or set(paragraph) != {'text','source_ids'}:
            raise ValueError('Unknown paragraph fields')
        if type(paragraph['text']) is not str or not paragraph['text'].strip() or len(paragraph['text']) > 6000:
            raise ValueError('Paragraph text must be bounded')
        ids = paragraph['source_ids']
        if type(ids) is not list or not ids or len(ids) > len(source_ids) or any(type(v) is not str or v not in source_ids for v in ids) or len(ids) != len(set(ids)):
            raise ValueError('Paragraph needs distinct amendment-only citation identities')
    if not any('amendment:update:A' in p['source_ids'] for p in paragraphs):
        raise ValueError('Update evidence must be cited')
    return _object(_encode(candidate))


def _append(fd, name, raw):
    # Link an fsynced private temporary inode into an absent final name. Never
    # rename over an existing artifact, reference, or symlink.
    temporary = '.prepare-' + uuid.uuid4().hex
    leaf = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(leaf, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(leaf)
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.fsync(fd)
    finally:
        os.close(leaf)
        os.unlink(temporary, dir_fd=fd)
        os.fsync(fd)


def prepare(*, db, evidence, original_packet_bytes, original_receipt_bytes,
            update_packet_bytes, update_receipt_bytes, original_validation_draft,
            update_validation_draft, candidate, state_root,
            artifact_directory):
    """Freeze a preparation artifact; return content address and private paths.

    This is not CAS, review acceptance, release authorization or an installer.
    No production artifact-directory default and no verifier override exist.
    Validation drafts are capture provenance only, never amendment approval;
    callers must explicitly supply saved-draft projections with image=None.
    """
    if type(evidence) is not AmendmentEvidence or type(evidence.original_capture) is not CaptureBinding or type(evidence.update_capture) is not CaptureBinding:
        raise ValueError('Typed evidence required')
    raws = (original_packet_bytes,original_receipt_bytes,update_packet_bytes,update_receipt_bytes)
    if any(type(raw) is not bytes or len(raw) > MAX_CAPTURE for raw in raws):
        raise ValueError('Capture bytes must be bounded')
    candidate_raw = _encode(candidate)
    validation_raws = []
    for draft in (original_validation_draft, update_validation_draft):
        if type(draft) is not dict or 'image' not in draft or draft['image'] is not None:
            raise ValueError('Validation draft must explicitly have image None')
        draft_raw = _encode(draft)
        if len(draft_raw) > MAX_CAPTURE:
            raise ValueError('Validation draft JSON exceeds bound')
        validation_raws.append(draft_raw)
    original_draft, update_draft = map(_object, validation_raws)
    if sum(map(len,raws)) + len(candidate_raw) + sum(map(len,validation_raws)) > MAX_INPUT:
        raise ValueError('Inputs exceed preparation bound')
    evidence.original_capture.verify_bytes(*raws[:2])
    evidence.update_capture.verify_bytes(*raws[2:])
    original, update = _object(raws[0]), _object(raws[2])
    _object(raws[1]); _object(raws[3])
    snapshot = predecessor_snapshot(db, evidence)
    job = snapshot['job']
    old_packet, old_draft = _object(job['packet']), _object(job['draft'])
    if {key:value for key,value in original_draft.items() if key != 'image'} != {key:value for key,value in old_draft.items() if key != 'image'}:
        raise ValueError('Original validation draft differs from predecessor excluding image')
    if _projection(original) != _projection(old_packet):
        raise ValueError('Original capture differs from predecessor nonimage projection')
    if job.get('story_key') != original.get('story_key') or job.get('source_url') != original['sources'][0]['url']:
        raise ValueError('Original job identity differs')
    citations, rights = [], []
    for role, packet in (('original',original),('update',update)):
        sources = packet.get('sources')
        docs = packet.get('supporting_documents')
        if packet.get('publication_basis',{}).get('provider') != 'vantaa' or type(sources) is not list or len(sources) != 1 or type(docs) is not list or len(docs) != 1:
            raise ValueError('Pilot requires one Vantaa source and rights document per capture')
        source = sources[0]
        if source.get('publisher') != 'Vantaan kaupunki' or source.get('id') != 'A' or source.get('related') or packet.get('story_key') != 'url:'+source['url']:
            raise ValueError('Pilot provider/publisher/source identity mismatch')
        citations.append({'id':f'amendment:{role}:A','role':role,'capture_source':source})
        rights.append({'id':f'amendment:{role}:RIGHTS','role':role,'publication_basis':packet['publication_basis'],'reuse':source.get('reuse'),'document':docs[0]})
    if original['sources'][0]['url'] == update['sources'][0]['url']:
        raise ValueError('Original/update URLs must differ')
    manuscript = _manuscript(_object(candidate_raw), old_draft, {s['id'] for s in citations})
    _reconstruct(original, original_draft, *raws[:2], state_root)
    _reconstruct(update, update_draft, *raws[2:], state_root)
    artifact = {'schema':'published-amendment-artifact-preparation-v1', 'preparation_only':True,'approval':False,'activation':False,
                'acceptance':'frozen-preparation-hash-only; fresh-fulltext-and-image-approval-and-CAS-required',
                'predecessor':snapshot,'evidence':asdict(evidence),
                'identity':{key:job[key] for key in ('id','story_key','source_url','created_at')},
                'captures':{'original':{'packet':original,'receipt':_object(raws[1]),'binding':asdict(evidence.original_capture),'validation_draft':original_draft},'update':{'packet':update,'receipt':_object(raws[3]),'binding':asdict(evidence.update_capture),'validation_draft':update_draft}},
                'validation_drafts_purpose':'capture-validation-provenance-only-not-amendment-approval',
                'candidate_manuscript':manuscript,'citations':citations,'rights':rights,
                'projection_kind':'amendment-only-two-capture-roles-not-ordinary-packet'}
    raw = _encode(artifact)
    if len(raw) > MAX_ARTIFACT:
        raise ValueError('Artifact exceeds bound')
    address = hashlib.sha256(raw).hexdigest()
    name, reference = address+'.json', address+'.ref'
    fd = _directory(artifact_directory, private=True)
    try:
        for target in (name, reference):
            try:
                os.stat(target, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise FileExistsError('Append-only target already exists: '+target)
        _append(fd, name, raw)
        _append(fd, reference, _encode({'artifact_sha256':address,'artifact_filename':name,'preparation_only':True,'approval':False,'activation':False}))
    finally:
        os.close(fd)
    return {'artifact_path':str(Path(artifact_directory)/name),'reference_path':str(Path(artifact_directory)/reference),'artifact_sha256':address}

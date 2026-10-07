"""Bounded owner-supplied independent rejection, not approval or authentication.

One exact previously selected pixel hash is refused only for its selected concept
in the exact preparation/full draft/ranked decision. No signatures, reviewer
identity, semantic correctness, or licensing are authenticated by this receipt.
The installed selection validator checks the actual saved image evidence; an
arbitrary caller-provided exclusion inventory is never accepted.
"""
import hashlib
import json
import re

MAX_REJECTION_BYTES = 32 * 1024
MAX_PRIOR_SELECTION_BYTES = 64 * 1024
FIELDS = frozenset({
    'schema', 'preparation_sha256', 'draft_sha256', 'decision_sha256',
    'prior_selection_bytes_sha256', 'selection_evidence_sha256',
    'image_sha256', 'concept_rank', 'reason', 'independently_reviewed',
    'rejection', 'normal_approval', 'activation', 'release',
})


def _object(raw, limit, *, canonical=False):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError('Missing or oversized rejection/selection bytes')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Nonfinite JSON number')

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=constant)
        if type(value) is not dict:
            raise ValueError('Expected JSON object')
        if canonical:
            from news_mvp.editorial import encode
            if raw != encode(value).encode('utf-8'):
                raise ValueError('Rejection receipt must be canonical JSON')
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid rejection/selection JSON') from exc


def validate_amendment_selection_rejection(*, rejection_bytes,
        prior_selection_bytes, preparation_bytes, draft, decision):
    """Return one (concept rank, exact SHA) pair or raise ValueError, offline.

    Preparation is structurally revalidated, not reconstructed from live sources.
    Prior bytes are the complete saved selection result, not just its selected
    SHA or an exclusion set. Neither this function nor the receipt activates it.
    """
    from news_mvp.amendment_review import build_review_envelope
    from news_mvp.editorial import digest
    from news_mvp.imagery import validate_image_decision, validate_selection_evidence

    receipt = _object(rejection_bytes, MAX_REJECTION_BYTES, canonical=True)
    prior = _object(prior_selection_bytes, MAX_PRIOR_SELECTION_BYTES)
    if set(receipt) != FIELDS or receipt['schema'] != 'amendment-selection-rejection-v1':
        raise ValueError('Unknown rejection schema or fields')
    for name in FIELDS:
        if name.endswith('sha256') and (type(receipt[name]) is not str or
                re.fullmatch(r'[0-9a-f]{64}', receipt[name]) is None):
            raise ValueError('Invalid exact rejection digest')
    if (receipt['independently_reviewed'] is not True or receipt['rejection'] is not True or
            any(receipt[name] is not False for name in ('normal_approval', 'activation', 'release')) or
            type(receipt['reason']) is not str or not receipt['reason'].strip() or
            type(receipt['concept_rank']) is not int):
        raise ValueError('Rejection assessment or nonactivation flags missing')
    if type(preparation_bytes) is not bytes:
        raise ValueError('Exact preparation bytes required')
    envelope = build_review_envelope(preparation_bytes)
    if draft != envelope['final_draft'] or envelope['source_relationship']['same_publisher'] is not True:
        raise ValueError('Rejection requires the exact amendment draft')
    decision = validate_image_decision(decision, draft, require_concepts=True)
    expected = {
        'preparation_sha256': hashlib.sha256(preparation_bytes).hexdigest(),
        'draft_sha256': digest(draft), 'decision_sha256': digest(decision),
        'prior_selection_bytes_sha256': hashlib.sha256(prior_selection_bytes).hexdigest(),
    }
    if any(receipt[key] != value for key, value in expected.items()):
        raise ValueError('Rejection scope changed')
    if (prior.get('status') != 'selection_completed' or
            prior.get('preparation_sha256') != expected['preparation_sha256'] or
            prior.get('draft_sha256') != expected['draft_sha256'] or
            prior.get('normal_approval') is not False or prior.get('activation') is not False or
            prior.get('release_authorization') is not False or type(prior.get('image')) is not dict):
        raise ValueError('Not an exact nonactivating saved selection result')
    image = prior['image']
    if image.get('classifier_output') != decision:
        raise ValueError('Prior ranked decision changed')
    try:
        selection = validate_selection_evidence(image, draft)
    except (KeyError, TypeError, AttributeError, IndexError, StopIteration) as exc:
        raise ValueError('Malformed prior selection evidence') from exc
    selected = selection['selected']
    if (receipt['selection_evidence_sha256'] != digest(selection) or
            receipt['image_sha256'] != selected['image_sha256'] or
            receipt['concept_rank'] != selected['concept_rank'] or
            type(selected['concept_rank']) is not int or
            image.get('pixel_review', {}).get('image_sha256') != receipt['image_sha256'] or
            prior.get('selected_image_sha256') != receipt['image_sha256']):
        raise ValueError('Rejection is not the actual prior selected pixels/concept')
    return frozenset({(receipt['concept_rank'], receipt['image_sha256'])})

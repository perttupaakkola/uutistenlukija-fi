"""Current generated-image accessibility and disclosure contract.

Original records remain in immutable archive-correction history. This contract
applies to current image records and output, not captured third-party source text.
"""
import json
import re
from copy import deepcopy

AI_ALT_PREFIX = 'AI-generoitu kuva: '
AI_CAPTION = 'AI-generoitu kuva. Ei valokuva tapahtumasta.'
AI_CREDIT = 'AI-kuvitus'
AI_TERMS_PATH = '/ai-kuvat/'
AI_TERMS_URL = 'https://uutistenlukija.fi' + AI_TERMS_PATH
# Encode the retired vocabulary solely for rejection/migration compatibility:
# the obsolete reader label itself must not remain in current source/fixtures.
RETIRED_IMAGE_STEM = bytes.fromhex('6b7576697475736b7576').decode('ascii')


def contains_retired_word(value):
    return RETIRED_IMAGE_STEM in json.dumps(value, ensure_ascii=False).casefold()


def validate_generated_wording(image):
    if image.get('generated') is not True:
        return
    if contains_retired_word(image):
        raise ValueError('Generated image metadata contains retired vocabulary')
    alt = image.get('alt')
    if not isinstance(alt, str) or not alt.startswith(AI_ALT_PREFIX):
        raise ValueError('Generated image alt needs the current Finnish AI prefix')
    description = alt[len(AI_ALT_PREFIX):].strip()
    if not 12 <= len(description) <= 300 or sum(c.isalpha() for c in description) < 8:
        raise ValueError('Generated image alt needs a useful concise pixel description')
    if image.get('caption') != AI_CAPTION:
        raise ValueError('Generated image needs the exact article disclosure')
    if image.get('credit') != AI_CREDIT:
        raise ValueError('Generated image credit must use the normalized reader wording')
    if image.get('license_url') != AI_TERMS_URL or image.get('source_url') != AI_TERMS_URL:
        raise ValueError('Generated image must link to current AI image terms')


def migrate_generated_metadata(image, pixel_review, draft):
    """Prepare image-only wording, retaining the original generation/pixel identity.

    The caller must retain the original record through backfill.install(), obtain
    exact-draft archive approval and use that guarded writer for activation.
    This function neither changes bytes nor grants publication approval.
    """
    from .editorial import digest
    from .imagery import validate_pixel_review
    if image.get('generated') is not True:
        raise ValueError('Wording migration requires a generated image')
    if 'wording_migration' in image:
        raise ValueError('Image already has a wording migration; do not replay it')
    reviewed = {**image, 'pixel_review':pixel_review}
    validate_pixel_review(reviewed, draft)
    description = pixel_review.get('alt_fi')
    if not isinstance(description, str) or contains_retired_word(pixel_review):
        raise ValueError('Fresh pixel review must use current wording')
    pattern = re.compile(RETIRED_IMAGE_STEM+r'[a-zåäö]*', re.I)
    def current(value):
        if isinstance(value, str):
            return pattern.sub('AI-generoitu kuva', value)
        if isinstance(value, list):return [current(v) for v in value]
        if isinstance(value, dict):return {k:current(v) for k,v in value.items()}
        return value
    result = current(deepcopy(image))
    result.update(alt=AI_ALT_PREFIX+description.strip(), caption=AI_CAPTION,
        credit=AI_CREDIT, source_url=AI_TERMS_URL, license_url=AI_TERMS_URL,
        pixel_review=deepcopy(pixel_review),
        wording_migration={'version':'ai-wording-20260926','previous_image_record_sha256':digest(image)})
    for key in ('sha256','url','local_path','pixels','model','prompt_sha256','prompt_version'):
        if result.get(key) != image.get(key):
            raise ValueError('Wording migration must preserve pixels and generation provenance')
    validate_generated_wording(result)
    return result

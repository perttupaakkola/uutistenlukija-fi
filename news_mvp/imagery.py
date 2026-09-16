"""Article imagery: generate an illustration from a verified fact, then verify the raster.

Design note - why generated rather than stock.

The previous news system searched stock providers (Pexels/Unsplash) by keyword and then tried
to prove the result was relevant. That approach failed structurally, and the clearest evidence
is commit 9318ea23c: an article about cocaine in Finnish wastewater was illustrated with
"scenic aerial view of snowy Finnish landscape", accepted with the reason
"metadata matches finnish, landscape". The matcher saw "Finland" and picked a pretty landscape
for a hard drug-policy story. Relevance was being retrofitted onto an arbitrary photograph, so
the code had to guess what a random image could plausibly mean - hence a large keyword engine
(concept rules, cue-token groups, name extraction, country suffixes) and a category-fallback
escape hatch that articles leaked onto in bulk.

This module inverts the direction: the image is *constructed* from a fact already verified in
the reviewed draft, so correspondence holds by construction and there is nothing to match.
A generated illustration also cannot mislead the way a real-but-adjacent photograph does, and
it sidesteps image rights entirely - it depicts no real person, event or third-party work,
which matters because the text licence explicitly does not cover images.

The one idea carried over from the old system is the independent pixel check: never trust the
prompt, filename or provider metadata as evidence of what an image actually depicts.
"""
import base64
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request

# gpt-image-1-mini is the cheap tier and is sufficient for a flat editorial illustration.
DEFAULT_MODEL = 'gpt-image-1-mini'
DEFAULT_SIZE = '1536x1024'          # 3:2, a normal editorial lead-image ratio
GENERATION_TIMEOUT = 240
PROMPT_VERSION = 'imagery-v1'
MAX_PROMPT_CHARS = 900

# Words that must never become the subject of a generated photograph: they invite depictions of
# identifiable people, real violence or tragedy. A generic illustration of the story's setting
# or subject is always preferable to a fabricated depiction of an event.
# Stems, not whole words: Finnish inflects heavily, so `kuoli` must also catch `kuolleet`,
# `kuolleita`, `kuoli` and similar. Matching only nominative forms is what let tragedy through
# in the first version of this list.
_FORBIDDEN_SUBJECT = re.compile(
    r'(uhri|kuol|meneht|surma|murha|itsemurh|raiskau|henkirik|'
    r'turmassa|onnettomuudessa|vakava sairaus|sairauskohtaus|'
    r'victim|killed|fatal|murder|suicide)', re.I)

# A photograph of a real, named person is not ours to generate.
_PERSON_RISK = re.compile(r'\b(presidentti|ministeri|pääministeri)\b', re.I)


def _prompt_for(subject, category=''):
    """A constrained illustration prompt: no text, no real people, editorial register."""
    category_hint = {
        'Kotimaa': 'Finnish civic and everyday setting',
        'Talous': 'neutral business and economics setting',
        'Ulkomaat': 'international news setting, generic and non-identifiable',
        'Tiede': 'science and research setting',
        'Kulttuuri': 'culture and arts setting',
        'Urheilu': 'sports setting',
    }.get(category, 'generic Nordic news setting')
    return (
        f"Editorial news illustration, {category_hint}. Subject: {subject[:280]}. "
        "Photorealistic, natural daylight, calm documentary register, wide 3:2 composition "
        "with clear space. Strictly no text, no lettering, no signage, no logos, no watermarks, "
        "no charts, no captions, no borders. No recognisable faces or identifiable real people. "
        "Do not depict violence, victims, or any real named individual. "
        # Invented period- or context-specific props assert facts the article never stated.
        # Observed on the first real generation: a face mask appeared in a school-shelter story,
        # implying a pandemic context that was not in the source.
        "People, if shown at all, are distant, anonymous and facing away; avoid face masks, "
        "uniforms, badges and any era-specific or situation-specific prop that would assert "
        "a fact the subject does not state. Prefer environment, architecture, objects and "
        "atmosphere over staged human activity. "
        "The image must work as a neutral visual summary of the subject."
    )[:MAX_PROMPT_CHARS]


def subject_from_draft(draft):
    """Choose a subject phrase from the draft's own verified text.

    Derived only from the reviewed title and first paragraph, so the subject is by definition
    something the article actually and verifiably says. Returns None when the article's
    substance is unsafe to illustrate, in which case the article ships without an image - a
    text-only article is acceptable, a misleading one is not.
    """
    title = (draft.get('title') or '').strip()
    paragraphs = draft.get('paragraphs') or []
    body = (paragraphs[0].get('text') if paragraphs else '') or ''
    source = f'{title}. {body}'.strip()

    if not title:
        return None
    if _FORBIDDEN_SUBJECT.search(source) or _PERSON_RISK.search(title):
        return None
    # Prefer the title: it is the reviewed statement of what the story is about.
    subject = re.sub(r'\s+', ' ', title).strip(' .–-')
    return subject or None


class GenerationError(RuntimeError):
    """A candidate image could not be produced and verified; the caller ships text-only."""


def _api_key():
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key:
        raise GenerationError('no image-generation credential available')
    return key


def generate(subject, category='', model=DEFAULT_MODEL, size=DEFAULT_SIZE):
    """Generate one image and return (raw_bytes, prompt, model)."""
    prompt = _prompt_for(subject, category)
    body = json.dumps({'model': model, 'prompt': prompt, 'size': size, 'n': 1}).encode()
    request = urllib.request.Request(
        'https://api.openai.com/v1/images/generations', data=body,
        headers={'Authorization': 'Bearer ' + _api_key(), 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=GENERATION_TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise GenerationError(f'generation request failed: HTTP {error.code}') from error
    except Exception as error:
        raise GenerationError(f'generation request failed: {type(error).__name__}') from error

    item = (payload.get('data') or [{}])[0]
    encoded = item.get('b64_json')
    if not encoded:
        raise GenerationError('provider returned no image payload')
    try:
        raw = base64.b64decode(encoded)
    except Exception as error:
        raise GenerationError('provider payload was not valid base64') from error
    if not raw:
        raise GenerationError('provider returned an empty image')
    return raw, prompt, model


def _pixels(raw):
    """Decode to a metadata-free RGB raster. Metadata is discarded, never trusted."""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        return image.convert('RGB')


def _rgb(image, x, y):
    """One pixel as an (r, g, b) triple.

    PIL's stubs type getpixel as `float | tuple | None`; for an RGB raster it is always a tuple,
    so pin that here instead of weakening the call sites.
    """
    pixel = image.getpixel((x, y))
    if not isinstance(pixel, tuple) or len(pixel) < 3:
        raise GenerationError('image is not a usable RGB raster')
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]))


def verify(raw, expect_ratio=None):
    """Verify the raster itself, independently of the prompt or provider metadata.

    Returns a description dict. Raises GenerationError when the raster is unusable, so a bad
    candidate is refused rather than published.
    """
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            width, height = image.size
            mode = image.mode
    except GenerationError:
        raise
    except Exception as error:
        raise GenerationError(f'image did not decode: {type(error).__name__}') from error

    if width < 600 or height < 400:
        raise GenerationError(f'image too small: {width}x{height}')
    ratio = width / height
    if expect_ratio and abs(ratio - expect_ratio) > 0.08:
        raise GenerationError(f'unexpected aspect ratio {ratio:.2f}')

    # Reject a near-uniform raster: a flat or blank image carries no illustration.
    raster = _pixels(raw)
    small = raster.resize((32, 32))
    samples = [_rgb(small, x, y) for y in range(32) for x in range(32)]
    mean = tuple(sum(p[i] for p in samples) / len(samples) for i in range(3))
    variance = sum((p[0] - mean[0]) ** 2 + (p[1] - mean[1]) ** 2 + (p[2] - mean[2]) ** 2
                   for p in samples) / len(samples)
    if variance < 40:
        raise GenerationError('image is effectively blank')

    return {'width': width, 'height': height, 'mode': mode,
            'variance': round(variance, 1)}


def describe(raw):
    """Describe visible content from a metadata-free raster.

    Carried over from the old pipeline's best idea (commit a534a80f4): the analyzer receives no
    filename, URL, prompt or article text, so a candidate cannot inject hints about what it is
    supposed to depict. Best effort - a missing credential returns None rather than failing the
    pipeline, because this is a secondary check.
    """
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key:
        return None
    try:
        raster = _pixels(raw)
        raster.thumbnail((768, 768))
        buffer = io.BytesIO()
        raster.save(buffer, format='JPEG', quality=85)
        encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
        body = json.dumps({
            'model': 'gpt-4o-mini', 'temperature': 0, 'max_tokens': 90,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': (
                    'Describe only the visible depicted content of this image in one short '
                    'sentence. Do not infer a filename, URL, prompt, article, or event. '
                    'State plainly if it contains legible text or an identifiable person.')},
                {'type': 'image_url',
                 'image_url': {'url': f'data:image/jpeg;base64,{encoded}'}}]}],
        }).encode()
        request = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions', data=body,
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        text = (payload['choices'][0]['message'].get('content') or '').strip()
        return re.sub(r'\s+', ' ', text)[:300] or None
    except Exception:
        return None


def _jpg(raw):
    """Re-encode to JPEG so the stored media always matches the renderer's media/<sha>.jpg."""
    raster = _pixels(raw)
    buffer = io.BytesIO()
    raster.save(buffer, format='JPEG', quality=88, optimize=True)
    return buffer.getvalue()


def build_image(draft, state_dir, category='', model=DEFAULT_MODEL):
    """Produce a verifiable image record for a draft, or None to ship text-only.

    Returns a dict matching what the site renderer's <figure> needs, plus the review fields the
    release contract binds. The caller stores the JPEG at media/<sha256>.jpg under state_dir.
    """
    from pathlib import Path
    subject = subject_from_draft(draft)
    if not subject:
        return None
    try:
        raw, prompt, used_model = generate(subject, category, model=model)
        facts = verify(raw)
    except GenerationError:
        return None

    jpeg = _jpg(raw)
    sha = hashlib.sha256(jpeg).hexdigest()
    media = Path(state_dir) / 'media'
    media.mkdir(parents=True, exist_ok=True)
    (media / f'{sha}.jpg').write_bytes(jpeg)

    description = describe(raw)
    return {
        'url': f'/media/{sha}.jpg',
        'local_path': f'media/{sha}.jpg',
        'sha256': sha,
        'alt': f'Kuvituskuva: {draft.get("title", "").strip()[:120]}',
        'caption': 'Kuvituskuva. Kuva on luotu tekoälyllä, ei valokuva tapahtumasta.',
        'credit': f'AI-kuvitus ({used_model})',
        'license': 'AI-generated illustration',
        'license_url': 'https://uutistenlukija.fi/tietosuoja/',
        'source_url': 'https://uutistenlukija.fi/tietosuoja/',
        'generated': True,
        'model': used_model,
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'prompt_version': PROMPT_VERSION,
        'subject': subject,
        'pixels': facts,
        'depicted': description,
        # Context for the independent editorial review; never evidence of correctness.
        'review_note': ('Tekoälyn tuottama kuvitus, joka on rakennettu otsikon ja ensimmäisen '
                        'kappaleen vahvistetusta sisällöstä. Kuva ei esitä todellista '
                        'henkilöä, tapahtumaa eikä tekijänoikeudellista teosta.'),
    }

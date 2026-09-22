"""Article imagery: Unsplash hotlink, then local Pexels, then generated fallback.

Stock metadata is treated as a hint rather than proof: a candidate needs positive overlap with
the reviewed story, its raster is independently checked, and Pexels candidates are copied into
the site's content-addressed media directory. If no safe stock image is available, the existing
generated-illustration path remains the final fallback. The returned record is therefore either
an Unsplash hotlink or a local Pexels/generated JPEG.

The independent pixel check is shared by all three paths: a prompt, filename, or provider
description is never evidence that the raster is usable.

"""
import base64
import hashlib
import io
import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# gpt-image-1-mini is the cheap tier and is sufficient for a flat editorial illustration.
DEFAULT_MODEL = 'gpt-image-1-mini'
DEFAULT_SIZE = '1536x1024'          # 3:2, a normal editorial lead-image ratio
GENERATION_TIMEOUT = 240
PROMPT_VERSION = 'imagery-v1'
MAX_PROMPT_CHARS = 900
# Public origin for the image record's `url`, which the release contract requires to be an
# absolute HTTPS URL. Kept in step with editorial.SITE / the sitemap host.
PUBLIC_BASE = 'https://uutistenlukija.fi'

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
        # Vehicles are the single most reliable source of unwanted lettering: observed
        # "POLIISI" written across an officer's back and "P...SI" on a police car, both of which
        # a vision description then reported as having no legible text. Avoid branded or
        # lettered objects rather than relying on detecting the text afterwards.
        "Do not include vehicles with markings, uniform lettering, signage or branded "
        "equipment; represent institutions through buildings, architecture and settings "
        "instead. Keep all surfaces free of any depicted writing. "
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


def has_legible_text(description):
    """Whether an independent description reports readable text in the raster.

    Text is a genuine defect, not a cosmetic one: observed on a police story, the model wrote
    "POLIISI" across an officer's back, and on another attempt put legible lettering on a police
    car. Published text can be misspelled, can imply a trademark or official marking, and reads
    as a real photograph rather than an illustration. The prompt forbids text and the model still
    produces it, sometimes, so this is checked on the actual output.

    The patterns cover how a vision model actually phrases this, which is more varied than
    "legible text": it also writes `the word "POLIISI" on the back` and `a sign that reads X`.
    An early version matched only the literal phrase and let a real "POLIISI" through.
    """
    if not description:
        return False
    lowered = description.lower()
    # An explicit statement of absence must win, or the negation itself trips the patterns.
    if re.search(r'\bno (legible |visible |readable )?text\b|\bwithout (any )?(visible |legible )?'
                 r'(text|lettering|words)\b|\bno lettering\b|\bno words\b', lowered):
        return False
    return bool(re.search(
        r'legible text|readable text|visible text|text on|text (?:is|are|reads)\b|'
        r'lettering|logo|\bthe word\b|\bwords?\b[^.]{0,20}\bon\b|'
        r'sign (?:that )?reads|writing on|label(?:led|ed)?\b|inscription|'
        r'"[A-ZÅÄÖ][A-ZÅÄÖa-zåäö]{2,}"',      # a quoted token, e.g. the word "POLIISI"
        description))


def build_image(draft, state_dir, category='', model=DEFAULT_MODEL, attempts=3):
    """Select an Unsplash hotlink, local Pexels image, or generated local JPEG for a draft.

    The provider order is Unsplash hotlink, Pexels copied into media/<sha256>.jpg, then the
    existing generated-illustration path. Returns a dict matching what the site renderer's
    <figure> needs, plus the review fields the release contract binds, or None to ship text-only.

    Up to `attempts` generations are tried, because a model sometimes writes text into an
    otherwise good illustration. The first candidate that verifies and carries no legible text
    wins; if none does, the article ships without an image.
    """
    from pathlib import Path
    subject = subject_from_draft(draft)
    if not subject:
        return None

    # Stock is preferred when a provider can prove both relevance and usable pixels. Providers
    # own the English query derivation; the Finnish generation subject is never passed into a
    # stock search. A provider outage or malformed result must leave the next provider available.
    try:
        stock = fetch_unsplash(draft)
    except Exception:
        stock = None
    if stock:
        return stock
    try:
        stock = fetch_pexels(draft, state_dir)
    except Exception:
        stock = None
    if stock:
        return stock

    for attempt in range(max(1, attempts)):
        try:
            raw, prompt, used_model = generate(subject, category, model=model)
            facts = verify(raw)
        except GenerationError:
            continue
        description = describe(raw)
        if has_legible_text(description):
            continue   # retry: text in a published illustration is not acceptable

        jpeg = _jpg(raw)
        sha = hashlib.sha256(jpeg).hexdigest()
        media = Path(state_dir) / 'media'
        media.mkdir(parents=True, exist_ok=True)
        (media / f'{sha}.jpg').write_bytes(jpeg)

        return {
            # `url` must be a full public HTTPS URL: validate_draft requires web_url() for it,
            # and the renderer substitutes the local /media/<sha>.jpg path when local_path is
            # set. A relative path here fails the release contract.
            'url': f'{PUBLIC_BASE}/media/{sha}.jpg',
            'local_path': f'media/{sha}.jpg',
            'sha256': sha,
            'alt': f'Kuvituskuva: {draft.get("title", "").strip()[:120]}',
            'caption': 'Kuvituskuva. Kuva on luotu tekoälyllä, ei valokuva tapahtumasta.',
            'credit': f'AI-kuvitus ({used_model})',
            'license': 'AI-generated illustration',
            # Must point at the terms that explain AI illustrations. Pointing this at the
            # privacy page was rejected by the independent reviewer, correctly: a privacy page
            # evidences no right to the image.
            'license_url': f'{PUBLIC_BASE}/kuvituskuvat/',
            'source_url': f'{PUBLIC_BASE}/kuvituskuvat/',
            'generated': True,
            'model': used_model,
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'prompt_version': PROMPT_VERSION,
            'subject': subject,
            'pixels': facts,
            'depicted': description,
            'attempts': attempt + 1,
            # Context for the independent editorial review; never evidence of correctness.
            'review_note': ('Tekoälyn tuottama kuvitus, joka on rakennettu otsikon ja ensimmäisen '
                            'kappaleen vahvistetusta sisällöstä. Kuva ei esitä todellista '
                            'henkilöä, tapahtumaa eikä tekijänoikeudellista teosta.'),
        }
    return None


# ---------------------------------------------------------------------------
# Stock imagery: Unsplash selection helpers.
#
# Stock is attempted before generation. Unsplash remains a hotlink-only path: its raster is
# fetched once to be verified and described, then discarded; the record carries a hotlink,
# provenance and a digest of that provenance instead. A provider
# credential is read at call time only, is never logged, never placed in a record, and is only
# attached to a request whose URL resolves to the exact provider API host.
# A request that carries that credential is never redirected at all, not even back to the same
# host: urllib copies the Authorization header onto a redirected request, so following a
# redirect is a credential leak waiting to happen. Only the uncredentialed image fetch may
# follow a redirect, and only while it stays on the exact provider image host. Selection likewise
# refuses metadata whose only overlap with the story is a place name, so a country mention can
# never again justify unrelated scenic imagery.
# ---------------------------------------------------------------------------

DEFAULT_CREDENTIAL_ROOT = '/home/pertt/.hermes/credentials'
CREDENTIAL_PROJECT = ('projects', 'uutistenlukija', '.env')
PROVIDER_ENV = {
    'unsplash': ('UNSPLASH_ACCESS_KEY',),
    'pexels': ('PEXELS_API_KEY',),
}

UNSPLASH_API_HOST = 'api.unsplash.com'
UNSPLASH_IMAGE_HOST = 'images.unsplash.com'
UNSPLASH_SITE_HOST = 'unsplash.com'
UNSPLASH_SEARCH_URL = 'https://api.unsplash.com/search/photos'
UNSPLASH_LICENSE_URL = 'https://unsplash.com/license'
UNSPLASH_TIMEOUT = 30
UNSPLASH_PER_PAGE = 10
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_QUERY_TERMS = 6

STOCK_CAPTION = 'Arkistokuva. Kuva ei esitä uutisen tapahtumaa.'
STOCK_LICENSE = 'Unsplash License'
STOCK_UTM = (('utm_source', 'uutistenlukija'), ('utm_medium', 'referral'))
STOCK_USER_AGENT = 'uutistenlukija/1.0 (https://uutistenlukija.fi)'

PEXELS_API_HOST = 'api.pexels.com'
PEXELS_IMAGE_HOST = 'images.pexels.com'
PEXELS_SITE_HOST = 'www.pexels.com'
PEXELS_SEARCH_URL = 'https://api.pexels.com/v1/search'
PEXELS_LICENSE_URL = 'https://www.pexels.com/license/'
PEXELS_TIMEOUT = 30
PEXELS_PER_PAGE = 80
PEXELS_QUOTA_LIMIT = 200
PEXELS_QUOTA_WINDOW = 60 * 60
PEXELS_QUOTA_FILENAME = 'pexels-quota.json'
# Tests may point this at a temporary file. In normal operation the path is derived from XDG's
# cache directory and is deliberately unrelated to the news state directory.
PEXELS_QUOTA_PATH = None

_PHOTO_ID = re.compile(r'[A-Za-z0-9_-]{6,40}')
_PEXELS_ID = re.compile(r'[1-9][0-9]{0,18}')
_UNSPLASH_PROFILE_PATH = re.compile(r'^/@[A-Za-z0-9][A-Za-z0-9._-]{0,49}/?$')
_UNSPLASH_PHOTO_PATH = re.compile(
    r'^/photos/(?:[A-Za-z0-9_-]{6,40}|[A-Za-z0-9][A-Za-z0-9_-]{0,119}-[A-Za-z0-9_-]{6,40})/?$')
_PEXELS_PROFILE_PATH = re.compile(r'^/@[A-Za-z0-9][A-Za-z0-9._-]{0,49}/?$')
_PEXELS_PHOTO_PATH = re.compile(
    r'^/photo/[A-Za-z0-9][A-Za-z0-9_-]{0,159}-[1-9][0-9]{0,18}/?$')
_TOKEN = re.compile(r'[a-zåäö0-9]+')
_ENGLISH_WORD = re.compile(r'[a-z]{3,}')
_KEEP_TOKENS = frozenset({'nato', 'eu', 'usa', 'gaza'})
_STOPWORDS = frozenset({
    'ja', 'tai', 'mutta', 'että', 'joka', 'jossa', 'josta', 'jonka', 'jotka', 'kuin', 'kun',
    'myös', 'mukaan', 'kanssa', 'vuonna', 'viime', 'tänä', 'ensi', 'yli', 'alle', 'jälkeen',
    'ennen', 'aikana', 'kertoo', 'kertoi', 'sanoi', 'uutinen', 'uutiset', 'asia', 'asiat',
    'paljon', 'vain', 'nyt', 'sitten', 'siitä', 'the', 'and', 'for', 'with', 'that', 'this',
    'from', 'about', 'into', 'over', 'after', 'before', 'more', 'than', 'news', 'says', 'said',
    'will', 'have', 'has', 'are', 'was', 'were', 'been', 'its', 'their', 'they', 'them',
})

# A place name is not a subject. The historical failure - a cocaine-in-wastewater story
# illustrated with a snowy Finnish landscape - came from counting "Finland" as a match, so place
# terms are excluded from the overlap score: they may appear in a query, but they can never be
# the only reason a photograph is kept.
_PLACE_TOKENS = frozenset({
    'finland', 'finnish', 'suomi', 'sweden', 'swedish', 'ruotsi', 'norway', 'norwegian',
    'russia', 'russian', 'venäjä', 'ukraine', 'ukrainian', 'ukraina', 'estonia', 'estonian',
    'china', 'chinese', 'kiina', 'europe', 'european', 'eurooppa', 'united', 'states',
    'yhdysvallat', 'gaza', 'helsinki', 'espoo', 'vantaa', 'tampere', 'turku', 'oulu',
})

# The small Finnish-to-English newsroom vocabulary the historical pipeline used: a stem maps to
# the English search term. Stems of five letters or more also match inflected forms
# (`hallituksen`, `talouspäätös`); shorter stems must match exactly, because prefix-matching them
# would translate `automaatio` as "car".
_FI_EN = {
    'hallitus': 'government', 'presidentti': 'president', 'eduskunta': 'parliament',
    'vaali': 'election', 'talous': 'economy', 'työttömyys': 'unemployment',
    'inflaatio': 'inflation', 'verotus': 'taxation', 'yritys': 'company', 'kauppa': 'trade',
    'markkina': 'market', 'koulu': 'school', 'opetus': 'education', 'yliopisto': 'university',
    'tutkimus': 'research', 'tiede': 'science', 'terveys': 'health', 'sairaala': 'hospital',
    'hoito': 'care', 'epidemia': 'epidemic', 'rokote': 'vaccine', 'ilmasto': 'climate',
    'ilmastonmuutos': 'climate change', 'energia': 'energy', 'sähkö': 'electricity',
    'metsä': 'forest', 'vesi': 'water', 'luonto': 'nature', 'saaste': 'pollution',
    'sota': 'war', 'sodan': 'war', 'sodassa': 'war', 'puolustus': 'defence',
    'armeija': 'army', 'ase': 'weapon', 'rauha': 'peace', 'poliisi': 'police',
    'rikos': 'crime', 'oikeus': 'court', 'tuomio': 'sentence', 'vankila': 'prison',
    'liikenne': 'traffic', 'auto': 'car', 'juna': 'train', 'lento': 'flight',
    'satama': 'harbour', 'kaupunki': 'city', 'kunta': 'municipality',
    'maahanmuutto': 'immigration', 'pakolainen': 'refugee', 'työ': 'work', 'palkka': 'wages',
    'asunto': 'housing', 'vuokra': 'rent', 'rakentaminen': 'construction', 'urheilu': 'sports',
    'jalkapallo': 'football', 'jääkiekko': 'ice hockey', 'kulttuuri': 'culture',
    'musiikki': 'music', 'elokuva': 'film', 'taide': 'art', 'kirja': 'book', 'media': 'media',
    'teknologia': 'technology', 'tietoturva': 'cybersecurity',
    'tekoäly': 'artificial intelligence', 'suomi': 'finland', 'ruotsi': 'sweden',
    'venäjä': 'russia', 'ukraina': 'ukraine', 'kiina': 'china', 'eurooppa': 'europe',
    'yhdysvallat': 'united states',
}


def _credential_env_files(credential_root):
    from pathlib import Path
    pattern = os.path.join('*', *CREDENTIAL_PROJECT)
    try:
        return sorted(Path(credential_root).glob(pattern))
    except OSError:
        return []


def _read_env_value(path, wanted):
    """One value from a project .env, or None.

    Deliberately forgiving: a missing file, a broken line or a foreign key is skipped rather
    than raised, and the parsed value is only ever returned to the caller - never logged and
    never embedded in an error message.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith('#'):
            continue
        if entry.lower().startswith('export '):
            entry = entry[len('export '):].strip()
        if '=' not in entry:
            continue
        name, _, value = entry.partition('=')
        if name.strip() != wanted:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1].strip()
        if not value or any(character in value for character in '\r\n\x00'):
            continue
        return value
    return None


def provider_key(name, credential_root=None):
    """Credential for a stock provider: the environment first, then the project .env files.

    Read at call time, never at import time, so a process that starts before the credential is
    installed still works. Returns None when nothing is configured; a missing credential is a
    normal, silent condition, so this neither raises nor logs, and no key value ever appears in
    an error message.
    """
    provider = (name or '').strip().lower()
    if not provider:
        return None
    names = PROVIDER_ENV.get(provider) or (f'{provider.upper()}_ACCESS_KEY',)
    for env_name in names:
        value = os.environ.get(env_name) or ''
        if value.strip():
            return value.strip()
    root = DEFAULT_CREDENTIAL_ROOT if credential_root is None else credential_root
    for path in _credential_env_files(root):
        for env_name in names:
            value = _read_env_value(path, env_name)
            if value:
                return value
    return None


def _english_term(token):
    """The English search term for one Finnish token, or None when nothing usable is there."""
    if token in _KEEP_TOKENS:
        return token
    if token in _STOPWORDS or len(token) < 4 or token.isdigit():
        return None
    for stem in sorted(_FI_EN, key=len, reverse=True):
        if token == stem or (len(stem) >= 5 and token.startswith(stem)):
            return _FI_EN[stem]
    return None


def stock_query(draft):
    """A small, conservative English search query built only from the draft's own words.

    Title first, then the first paragraph, capped at MAX_QUERY_TERMS distinct terms. There is no
    category fallback and no invented subject: a draft whose words do not map to the known news
    vocabulary yields no query at all, and the caller ships without a stock image.
    """
    if not isinstance(draft, dict):
        return ''
    title = draft.get('title') if isinstance(draft.get('title'), str) else ''
    paragraphs = draft.get('paragraphs') or []
    body = ''
    if paragraphs and isinstance(paragraphs[0], dict):
        body = paragraphs[0].get('text') or ''
    if not isinstance(body, str):
        body = ''
    terms = []
    for source in (title, body):
        for token in _TOKEN.findall(source.lower()):
            english = _english_term(token)
            if not english or english in terms:
                continue
            terms.append(english)
            if len(terms) >= MAX_QUERY_TERMS:
                return ' '.join(terms)
    return ' '.join(terms)


def _exact_https(url, host):
    """Parse `url` only when it is HTTPS on exactly `host`; otherwise None."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != 'https' or parts.username or parts.password:
        return None
    if parts.hostname != host or port not in (None, 443):
        return None
    return parts


def _with_utm(url, host):
    """Add the newsroom referral parameters to a validated provider link."""
    parts = _exact_https(url, host)
    if parts is None:
        return None
    pairs = [(key, value) for key, value in
             urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if key not in ('utm_source', 'utm_medium')]
    pairs.extend(STOCK_UTM)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(pairs), ''))


def _site_path(url, host, pattern):
    """A provider site URL whose path matches the provider's public identity shape."""
    parts = _exact_https(url, host)
    if parts is None or not pattern.fullmatch(parts.path):
        return None
    return parts


def _hotlink(url):
    """Normalise an Unsplash CDN URL to the one hotlink size and format the site ships."""
    parts = _exact_https(url, UNSPLASH_IMAGE_HOST)
    if parts is None:
        return None
    preserved = [(key, value) for key, value in
                 urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                 if key == 'ixid']
    normalized = preserved + [('w', '1536'), ('q', '80'), ('fm', 'jpg'), ('fit', 'crop')]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(normalized), ''))


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, including one that stays on the same host.

    urllib copies request headers onto a redirected request, so following a redirect from a
    credentialed request would replay the provider credential at a URL the response chose. Both
    the handler limit and `redirect_request` refuse; whichever path urllib takes, a redirect is
    never followed.
    """

    max_redirections = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _ExactHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only while they stay on the exact host; refuse anything else."""

    max_redirections = 3

    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _exact_https(newurl, self.host) is None:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request, host, timeout=UNSPLASH_TIMEOUT, credentialed=True):
    """Open a request pinned to exactly `host`, with the redirect policy for its credential.

    The default is the strict policy: a call site that forgets the flag must not accidentally
    follow a redirect with the credential attached.
    """
    if _exact_https(request.full_url, host) is None:
        raise urllib.error.URLError('refused non-provider host')
    request.add_header('User-Agent', STOCK_USER_AGENT)
    handler = _NoRedirects() if credentialed else _ExactHostRedirects(host)
    opener = urllib.request.build_opener(handler)
    return opener.open(request, timeout=timeout)


def _get_json(url, host, headers):
    """A JSON GET that must not follow a redirect away from `host`; None on any failure."""
    if _exact_https(url, host) is None:
        return None
    try:
        with _open(urllib.request.Request(url, headers=headers), host,
                   credentialed=True) as response:
            if _exact_https(response.geturl(), host) is None:
                return None
            if not 200 <= getattr(response, 'status', 200) < 300:
                return None
            return json.loads(response.read().decode('utf-8'))
    except Exception:
        return None


def _get_bytes(url, host):
    """Transient bytes for verification only; never returned to a caller and never stored."""
    if _exact_https(url, host) is None:
        return None
    try:
        with _open(urllib.request.Request(url, headers={'Accept': 'image/*'}), host,
                   credentialed=False) as response:
            if _exact_https(response.geturl(), host) is None:
                return None
            if not 200 <= getattr(response, 'status', 200) < 300:
                return None
            raw = response.read(MAX_IMAGE_BYTES + 1)
    except Exception:
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    return raw


def _track_download(url, photo_id, key):
    """The provider-mandated download GET for one selected photo; False on any failure."""
    parts = _exact_https(url, UNSPLASH_API_HOST)
    if parts is None or parts.path.rstrip('/') != f'/photos/{photo_id}/download':
        return False
    headers = {'Authorization': 'Client-ID ' + key}
    try:
        with _open(urllib.request.Request(url, headers=headers), UNSPLASH_API_HOST,
                   credentialed=True) as response:
            if _exact_https(response.geturl(), UNSPLASH_API_HOST) is None:
                return False
            return 200 <= getattr(response, 'status', 200) < 300
    except Exception:
        return False


def _token_set(text):
    return set(_ENGLISH_WORD.findall(text.lower())) if isinstance(text, str) else set()


def _draft_tokens(draft, query):
    """Tokens a provider description must overlap with to count as relevant."""
    tokens = _token_set(query)
    if isinstance(draft, dict):
        title = draft.get('title') or ''
        if isinstance(title, str):
            for token in _TOKEN.findall(title.lower()):
                english = _english_term(token)
                if english:
                    tokens.update(english.split())
                elif len(token) >= 3 and not token.isdigit():
                    tokens.add(token)
    return tokens


def _relevance(description, item, tokens):
    """Overlap between provider metadata and the story's own terms, place names excluded.

    Zero means the metadata says nothing about the subject: the photo is in the results because
    the API returned it, not because anything in it belongs to this story.
    """
    metadata = _token_set(f'{description} {item.get("alt_description") or item.get("alt") or ""}')
    return len((metadata & tokens) - _PLACE_TOKENS)


def _photo_candidate(item, tokens):
    """One complete, safely-addressable candidate, or None when a required field is unusable.

    `relevance` counts overlapping non-place terms; zero means no subject overlap at all.
    """
    if not isinstance(item, dict):
        return None
    photo_id = item.get('id')
    if not isinstance(photo_id, str) or not _PHOTO_ID.fullmatch(photo_id):
        return None
    urls = item.get('urls') if isinstance(item.get('urls'), dict) else {}
    source = urls.get('raw') or urls.get('full') or urls.get('regular')
    hotlink = _hotlink(source) if isinstance(source, str) else None
    if hotlink is None:
        return None
    links = item.get('links') if isinstance(item.get('links'), dict) else {}
    photo_page = _with_utm(links.get('html'), UNSPLASH_SITE_HOST)
    download = links.get('download_location')
    if (photo_page is None or
            _site_path(photo_page, UNSPLASH_SITE_HOST, _UNSPLASH_PHOTO_PATH) is None):
        return None
    download_parts = _exact_https(download, UNSPLASH_API_HOST)
    if download_parts is None or download_parts.path.rstrip('/') != f'/photos/{photo_id}/download':
        return None
    user = item.get('user') if isinstance(item.get('user'), dict) else {}
    name = user.get('name')
    name = re.sub(r'\s+', ' ', name).strip() if isinstance(name, str) else ''
    user_links = user.get('links') if isinstance(user.get('links'), dict) else {}
    profile = _with_utm(user_links.get('html'), UNSPLASH_SITE_HOST)
    if (not name or profile is None or
            _site_path(profile, UNSPLASH_SITE_HOST, _UNSPLASH_PROFILE_PATH) is None):
        return None
    description = item.get('alt_description') or item.get('description')
    description = (re.sub(r'\s+', ' ', description).strip()[:300]
                   if isinstance(description, str) else '')
    relevance = _relevance(description, item, tokens)
    return {'photo_id': photo_id, 'hotlink': hotlink, 'photo_page': photo_page,
            'download': download, 'name': name, 'profile': profile,
            'description': description or None, 'relevance': relevance}


def _digest(value):
    """editorial.digest, imported here so this module never forms an import cycle."""
    try:
        from . import editorial
    except ImportError:
        import editorial
    return editorial.digest(value)


def _stock_record(candidate, query, pixels, depicted, retrieved_at):
    provenance = {
        'provider': 'unsplash',
        'photo_id': candidate['photo_id'],
        'photographer': candidate['name'],
        'photographer_url': candidate['profile'],
        'photo_url': candidate['photo_page'],
        'query': query,
        'retrieved_at': retrieved_at,
        'image_url': candidate['hotlink'],
        'download_tracking': {'url': candidate['download'], 'successful': True},
    }
    alt = f'Arkistokuva: {depicted}' if depicted else f'Arkistokuva aiheesta {query}'
    return {
        'url': candidate['hotlink'],
        'alt': alt[:250],
        'caption': STOCK_CAPTION,
        'credit': f"Photo by {candidate['name']} on Unsplash",
        'license': STOCK_LICENSE,
        'license_url': UNSPLASH_LICENSE_URL,
        'source_url': candidate['photo_page'],
        'generated': False,
        'pixels': pixels,
        'depicted': depicted,
        'hotlink': True,
        'stock_provenance': provenance,
        'stock_provenance_sha256': _digest(provenance),
    }


def fetch_unsplash(draft, subject=None):
    """Select one relevant Unsplash photograph as a hotlink-only record, or None.

    The raster behind the hotlink is fetched once so `verify` can judge the pixels and `describe`
    can name the content, then it is discarded; the record never carries bytes, a local path or
    a file digest. Selection is followed by the required download-tracking GET, on every call,
    including a photo that was already selected before. Any absence, HTTP failure, malformed
    payload or refused redirect returns None so the caller ships text-only.

    `subject` is an optional caller-supplied search subject that replaces the derived keywords;
    it is never a category name and is not a fallback for an empty draft.
    """
    key = provider_key('unsplash')
    if not key:
        return None
    query = re.sub(r'\s+', ' ', subject).strip() if isinstance(subject, str) else ''
    if not query:
        query = stock_query(draft)
    if not query:
        return None
    search_url = UNSPLASH_SEARCH_URL + '?' + urllib.parse.urlencode(
        {'query': query, 'orientation': 'landscape', 'per_page': UNSPLASH_PER_PAGE})
    payload = _get_json(search_url, UNSPLASH_API_HOST,
                        {'Authorization': 'Client-ID ' + key, 'Accept-Version': 'v1'})
    if not isinstance(payload, dict):
        return None
    results = payload.get('results')
    if not isinstance(results, list) or not results:
        return None
    tokens = _draft_tokens(draft, query)
    # Zero-relevance metadata is dropped, not merely sorted last: a photo the provider happened
    # to return is not evidence that it belongs to this story, and a place-name match alone is
    # exactly the failure mode that put a snowy landscape on a drug-policy article.
    candidates = [candidate for candidate in (_photo_candidate(item, tokens) for item in results)
                  if candidate is not None and candidate['relevance'] > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: candidate['relevance'], reverse=True)
    for candidate in candidates:
        try:
            raw = _get_bytes(candidate['hotlink'], UNSPLASH_IMAGE_HOST)
            if raw is None:
                continue
            try:
                pixels = verify(raw)
            except GenerationError:
                continue
            # describe() is best effort: a vision failure must not discard a candidate whose
            # pixels already verified, so the record keeps the candidate and reports no
            # depicted subject.
            try:
                depicted = describe(raw)
            except Exception:
                depicted = None
            if not _track_download(candidate['download'], candidate['photo_id'], key):
                return None
            return _stock_record(candidate, query, pixels, depicted,
                                 datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Pexels stock imagery.

def _pexels_quota_path():
    """Return the secret-free Pexels ledger path, outside the news state directory."""
    from pathlib import Path
    if PEXELS_QUOTA_PATH:
        return Path(PEXELS_QUOTA_PATH)
    cache_root = os.environ.get('PEXELS_CACHE_DIR') or os.environ.get('XDG_CACHE_HOME')
    if not cache_root:
        cache_root = os.path.join(os.path.expanduser('~'), '.cache')
    return Path(cache_root) / 'uutistenlukija' / PEXELS_QUOTA_FILENAME


def _quota_state(value):
    """Validate the small on-disk quota schema; malformed state fails closed."""
    if (not isinstance(value, dict) or type(value.get('version')) is not int or
            value.get('version') != 1):
        return None
    requests = value.get('requests')
    blocked_until = value.get('blocked_until', 0)
    if not isinstance(requests, list) or len(requests) > PEXELS_QUOTA_LIMIT:
        return None
    if isinstance(blocked_until, bool) or not isinstance(blocked_until, (int, float)):
        return None
    try:
        blocked_until = float(blocked_until)
    except (TypeError, ValueError, OverflowError):
        return None
    if blocked_until < 0 or not math.isfinite(blocked_until):
        return None
    clean = []
    for timestamp in requests:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return None
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(timestamp) or timestamp < 0:
            return None
        clean.append(timestamp)
    return {'version': 1, 'requests': clean, 'blocked_until': blocked_until}


def _read_quota(path):
    from pathlib import Path
    try:
        with Path(path).open('r', encoding='utf-8') as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return {'version': 1, 'requests': [], 'blocked_until': 0.0}
    except (OSError, ValueError, TypeError):
        return None
    return _quota_state(value)


def _write_quota(path, value):
    """Atomically write a validated quota state while the sibling lock is held."""
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=str(target.parent),
                prefix=f'.{target.name}.', suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, sort_keys=True, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
        return True
    except OSError:
        return False
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _quota_locked(update):
    """Run one quota update under an inter-process advisory lock."""
    try:
        import fcntl
        path = _pexels_quota_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + '.lock').open('a+', encoding='utf-8') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                return update(path)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    except Exception:
        # A quota that cannot be read or locked must never turn into an unbounded provider call.
        return None


def _reserve_pexels_request():
    """Reserve one Pexels API request, counting the request even when it later fails."""
    now = time.time()

    def update(path):
        state = _read_quota(path)
        if state is None:
            return False
        recent = [timestamp for timestamp in state['requests']
                  if now - timestamp < PEXELS_QUOTA_WINDOW]
        if state['blocked_until'] > now or len(recent) >= PEXELS_QUOTA_LIMIT:
            return False
        recent.append(now)
        state['requests'] = recent
        return _write_quota(path, state)

    return _quota_locked(update) is True


def _header(headers, name):
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        value = None
    if value is not None:
        return str(value).strip()
    try:
        wanted = name.lower()
        for key, value in headers.items():
            if str(key).lower() == wanted:
                return str(value).strip()
    except (AttributeError, TypeError):
        return None
    return None


def _header_time(value, now, relative=False):
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        amount = float(value)
        if amount < 0 or not math.isfinite(amount):
            return None
        timestamp = now + amount if relative else amount
        return timestamp if math.isfinite(timestamp) and timestamp >= 0 else None
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamp = parsed.timestamp()
        return timestamp if timestamp >= 0 and math.isfinite(timestamp) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _pexels_backoff_until(headers):
    """Interpret both common 429 backoff headers without retaining their raw values."""
    now = time.time()
    retry_after = _header(headers, 'Retry-After')
    reset = (_header(headers, 'X-Ratelimit-Reset') or
             _header(headers, 'X-RateLimit-Reset') or
             _header(headers, 'RateLimit-Reset'))
    candidates = []
    retry_time = _header_time(retry_after, now, relative=True)
    reset_time = _header_time(reset, now, relative=False)
    if retry_time is not None:
        candidates.append(retry_time)
    if reset_time is not None:
        candidates.append(reset_time)
    return max(candidates) if candidates else now + PEXELS_QUOTA_WINDOW


def _honor_pexels_429(headers):
    until = _pexels_backoff_until(headers)
    if until is None:
        return

    def update(path):
        state = _read_quota(path)
        if state is None:
            return False
        state['blocked_until'] = max(state['blocked_until'], until)
        return _write_quota(path, state)

    _quota_locked(update)


def _pexels_search(query, key):
    """Search Pexels once; no exception or provider response is exposed to callers."""
    if not _reserve_pexels_request():
        return None
    search_url = PEXELS_SEARCH_URL + '?' + urllib.parse.urlencode({
        'query': query,
        'per_page': PEXELS_PER_PAGE,
        'orientation': 'landscape',
    })
    request = urllib.request.Request(
        search_url, headers={'Authorization': key, 'Accept': 'application/json'})
    try:
        with _open(request, PEXELS_API_HOST, timeout=PEXELS_TIMEOUT,
                   credentialed=True) as response:
            if _exact_https(response.geturl(), PEXELS_API_HOST) is None:
                return None
            status = getattr(response, 'status', None)
            if status is None:
                status = response.getcode()
            if status == 429:
                _honor_pexels_429(getattr(response, 'headers', None))
                return None
            if not 200 <= status < 300:
                return None
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        if error.code == 429:
            _honor_pexels_429(error.headers)
        return None
    except Exception:
        return None


def _pexels_candidate(item, tokens):
    """Validate one Pexels identity and source URL before any image bytes are fetched."""
    if not isinstance(item, dict):
        return None
    raw_id = item.get('id')
    if isinstance(raw_id, bool) or isinstance(raw_id, (int, str)):
        photo_id = str(raw_id)
    else:
        return None
    if not _PEXELS_ID.fullmatch(photo_id):
        return None

    photo_parts = _site_path(item.get('url'), PEXELS_SITE_HOST, _PEXELS_PHOTO_PATH)
    if photo_parts is None or photo_parts.query or photo_parts.fragment:
        return None
    if photo_parts.path.rstrip('/').rsplit('-', 1)[-1] != photo_id:
        return None
    photo_page = urllib.parse.urlunsplit(
        (photo_parts.scheme, PEXELS_SITE_HOST, photo_parts.path, '', ''))

    photographer = item.get('photographer')
    photographer = re.sub(r'\s+', ' ', photographer).strip() if isinstance(photographer, str) else ''
    profile_parts = _site_path(item.get('photographer_url'), PEXELS_SITE_HOST,
                               _PEXELS_PROFILE_PATH)
    if not photographer or profile_parts is None or profile_parts.query or profile_parts.fragment:
        return None
    profile = urllib.parse.urlunsplit(
        (profile_parts.scheme, PEXELS_SITE_HOST, profile_parts.path, '', ''))

    source = item.get('src') if isinstance(item.get('src'), dict) else {}
    image_url = source.get('large') or source.get('large2x')
    if _exact_https(image_url, PEXELS_IMAGE_HOST) is None:
        return None
    description = item.get('alt') or item.get('description')
    description = (re.sub(r'\s+', ' ', description).strip()[:300]
                   if isinstance(description, str) else '')
    relevance = _relevance(description, item, tokens)
    return {'photo_id': photo_id, 'photo_page': photo_page, 'profile': profile,
            'name': photographer, 'image_url': image_url,
            'description': description or None, 'relevance': relevance}


def _pexels_record(candidate, query, sha, local_path, pixels, depicted, retrieved_at):
    provenance = {
        'provider': 'pexels',
        'photo_id': candidate['photo_id'],
        'photographer': candidate['name'],
        'photographer_url': candidate['profile'],
        'photo_url': candidate['photo_page'],
        'query': query,
        'retrieved_at': retrieved_at,
        'image_url': candidate['image_url'],
    }
    alt = f"Arkistokuva: {depicted}" if depicted else f'Arkistokuva aiheesta {query}'
    return {
        'url': f'{PUBLIC_BASE}/{local_path}',
        'local_path': local_path,
        'sha256': sha,
        'alt': alt[:250],
        'caption': STOCK_CAPTION,
        'credit': f"Photo by {candidate['name']} on Pexels",
        'license': 'Pexels License',
        'license_url': PEXELS_LICENSE_URL,
        'source_url': candidate['photo_page'],
        'generated': False,
        'pixels': pixels,
        'depicted': depicted,
        'hotlink': False,
        'stock_provenance': provenance,
        'stock_provenance_sha256': _digest(provenance),
    }


def fetch_pexels(draft, state_dir, subject=None):
    """Fetch, verify, and persist one relevant Pexels photograph, or return None."""
    try:
        key = provider_key('pexels')
        if not key:
            return None
        query = re.sub(r'\s+', ' ', subject).strip() if isinstance(subject, str) else ''
        if not query:
            query = stock_query(draft)
        if not query:
            return None
        payload = _pexels_search(query, key)
        if not isinstance(payload, dict):
            return None
        results = payload.get('photos')
        if not isinstance(results, list) or not results:
            return None
        tokens = _draft_tokens(draft, query)
        candidates = [candidate for candidate in (_pexels_candidate(item, tokens)
                      for item in results)
                      if candidate is not None and candidate['relevance'] > 0]
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate['relevance'], reverse=True)
        from pathlib import Path
        for candidate in candidates:
            raw = _get_bytes(candidate['image_url'], PEXELS_IMAGE_HOST)
            if raw is None:
                continue
            try:
                verify(raw)
            except GenerationError:
                continue
            try:
                depicted = describe(raw)
            except Exception:
                depicted = None
            jpeg = _jpg(raw)
            try:
                pixels = verify(jpeg)
            except GenerationError:
                continue
            sha = hashlib.sha256(jpeg).hexdigest()
            local_path = f'media/{sha}.jpg'
            media = Path(state_dir) / 'media'
            media.mkdir(parents=True, exist_ok=True)
            (media / f'{sha}.jpg').write_bytes(jpeg)
            return _pexels_record(
                candidate, query, sha, local_path, pixels, depicted,
                datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    except Exception:
        return None
    return None

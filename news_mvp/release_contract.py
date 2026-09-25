"""Explicit official-text provenance; legacy imaged releases keep their original meaning."""
import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .editorial import digest, validate_draft, validate_review

TEXT_POLICY = 'official-text-v1'
SHA = r'[0-9a-f]{64}'
# Mirrors validate_packet's hard cap: the official source plus up to 7 related corroborating
# sources. Kept here too so the release contract does not depend on the editor module.
MAX_PACKET_SOURCES = 8

# Reader-visible chrome may carry exactly these site-local assets, and only inside an
# outer header/footer. Anything else on a text-only page is editorial or foreign.
BRANDING_LOGO_SRCS = frozenset({
    '/mvp-assets/images/logo.png',
    '/assets/images/logo.png',
})
BRANDING_LOGO_SRC = '/mvp-assets/images/logo.png'
GENERATED_READER_CREDIT = 'AI-kuvitus'
_BRANDING_SECTIONS = ('header', 'footer')
_HTML_VOID_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
})


class _ImageSources(HTMLParser):
    """Collect <img> src/srcset plus whether the tag sits in header/footer chrome."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._open_elements = []
        self._blocked = 0
        self._picture = 0
        self.has_alternative = False
        self.images = []

    def _record(self, attrs, blocked=False):
        names = [name.lower() for name, _value in attrs]
        values = {name.lower(): value for name, value in attrs}
        self.images.append({
            'src': values.get('src'),
            'srcset': values.get('srcset'),
            'chrome': any(tag in _BRANDING_SECTIONS for tag, _blocks in self._open_elements)
                      and not blocked,
            'duplicate': len(names) != len(set(names)),
            'alternative': self._picture > 0 or self.has_alternative,
        })

    def _start(self, tag, attrs, self_closing=False):
        values = {name.lower(): value for name, value in attrs}
        classes = (values.get('class') or '').split()
        blocks = int(tag in ('main', 'article'))
        if any(token == 'teaser' or 'teaser' in token or token == 'article' or token.startswith('article-')
               or token.endswith('-article') or token.startswith('portal-article') for token in classes):
            blocks += 1
        if tag == 'picture':
            self.has_alternative = True
        elif tag == 'source':
            self.has_alternative = True
        elif tag == 'img':
            self._record(attrs, self._blocked + blocks > 0)

        if tag not in _HTML_VOID_ELEMENTS and not self_closing:
            self._open_elements.append((tag, blocks))
            self._blocked += blocks
            if tag == 'picture':
                self._picture += 1

    def handle_starttag(self, tag, attrs):
        self._start(tag.lower(), attrs)

    def handle_startendtag(self, tag, attrs):
        self._start(tag.lower(), attrs, self_closing=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _HTML_VOID_ELEMENTS or not self._open_elements:
            return
        if self._open_elements[-1][0] != tag:
            return
        _tag, blocks = self._open_elements.pop()
        self._blocked -= blocks
        if tag == 'picture':
            self._picture -= 1


def _only_branding_images(html):
    """True when a page's only images are the exact logo asset inside header/footer.

    A text-only public page must not present any editorial or foreign picture. The
    brand logo is chrome, not content: it is accepted only at its exact site path and
    only while a header/footer element is open, so a look-alike path, an off-site
    source, a srcset alternate, or the same logo dropped into the article body all
    stay rejected.
    """
    parser = _ImageSources()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return False
    if parser.has_alternative:
        return False
    if any(
        image['src'] not in BRANDING_LOGO_SRCS or image['srcset'] is not None
        or not image['chrome'] or image['duplicate'] or image['alternative']
        for image in parser.images
    ):
        return False
    # Commented-out or otherwise unparsed image markup must not pass as branding.
    return html.lower().count('<img') == len(parser.images)

_STOCK_PROVENANCE_COMMON = {
    'provider', 'photo_id', 'photographer', 'photographer_url', 'photo_url',
    'query', 'retrieved_at', 'image_url',
}
_STOCK_IMAGE_COMMON = {
    'generated', 'url', 'source_url', 'stock_provenance',
    'stock_provenance_sha256', 'alt', 'caption', 'credit', 'license',
    'license_url', 'pixels', 'depicted',
}
_STOCK_UTC = re.compile(
    r'\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z'
)


def _stock_nonempty(value, field):
    if not isinstance(value, str) or not value or not value.strip() or value != value.strip():
        raise ValueError(f'Invalid stock {field}')
    return value


def _stock_https(value, host, field, query=False):
    if not isinstance(value, str):
        raise ValueError(f'Invalid stock {field} URL')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError(f'Invalid stock {field} URL') from None
    if (parsed.scheme != 'https' or parsed.hostname != host or
            parsed.username is not None or parsed.password is not None or
            port not in (None, 443) or not parsed.path or parsed.fragment or
            (query and not parsed.query)):
        raise ValueError(f'Invalid stock {field} URL')
    return parsed


def _stock_utm(value, host, field):
    parsed = _stock_https(value, host, field, query=True)
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise ValueError(f'Invalid stock {field} tracking') from None
    if (query.get('utm_source') != ['uutistenlukija'] or
            query.get('utm_medium') != ['referral']):
        raise ValueError(f'Invalid stock {field} tracking')
    return parsed


def _stock_photo_id(value, provider):
    if provider == 'unsplash':
        if (not isinstance(value, str) or
                not re.fullmatch(r'[A-Za-z0-9_-]{6,40}', value)):
            raise ValueError('Invalid stock photo_id')
        return value
    if provider in ('wikimedia', 'google'):
        if (not isinstance(value, str) or not value.strip() or value != value.strip() or
                not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', value)):
            raise ValueError('Invalid open-source photo_id')
        return value
    if isinstance(value, bool) or (not isinstance(value, (int, str))):
        raise ValueError('Invalid stock photo_id')
    if isinstance(value, int):
        if value <= 0:
            raise ValueError('Invalid stock photo_id')
        return str(value)
    if not value.strip() or value != value.strip() or not value.isdigit() or int(value) <= 0:
        raise ValueError('Invalid stock photo_id')
    return value


def _stock_profile_url(value, host, field, provider):
    if provider == 'unsplash':
        parsed = _stock_utm(value, host, field)
        valid = re.fullmatch(r'/@[A-Za-z0-9._-]+/?', parsed.path)
    elif provider in ('wikimedia', 'google'):
        parsed = _stock_https(value, host, field)
        valid = bool(parsed.path and parsed.path != '/')
    else:
        parsed = _stock_https(value, host, field)
        valid = bool(re.fullmatch(r'/@[A-Za-z0-9._-]+/?', parsed.path))
    if not valid:
        raise ValueError(f'Invalid stock {field} identity')
    return parsed


def _stock_photo_url(value, host, photo_id, provider):
    parsed = _stock_utm(value, host, 'photo_url') if provider == 'unsplash' else _stock_https(
        value, host, 'photo_url')
    path = parsed.path.rstrip('/')
    if provider == 'unsplash':
        prefix = '/photos/'
        slug = path[len(prefix):] if path.startswith(prefix) else ''
        valid = bool(slug and '/' not in slug and (slug == photo_id or slug.endswith('-' + photo_id)))
    elif provider == 'pexels':
        prefix = '/photo/'
        slug = path[len(prefix):] if path.startswith(prefix) else ''
        valid = bool(slug and '/' not in slug and (slug == photo_id or slug.endswith('-' + photo_id)))
    elif provider == 'wikimedia':
        valid = path.startswith('/wiki/File:') and len(path) > len('/wiki/File:')
    else:
        # Google Custom Search links are the reviewed source page and may use any public HTTPS
        # path; the separate image URL and licence URL still have to be recorded below.
        valid = bool(path and path != '/')
    if not valid:
        raise ValueError('Invalid stock photo_url identity')
    return parsed


def _stock_image_url(value, host, field):
    parsed = _stock_https(value, host, field)
    if not parsed.path or parsed.path == '/':
        raise ValueError(f'Invalid stock {field} URL')
    return parsed


def _stock_retrieved_at(value):
    if not isinstance(value, str) or not _STOCK_UTC.fullmatch(value):
        raise ValueError('Invalid stock retrieved_at')
    try:
        parsed = datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
    except ValueError:
        raise ValueError('Invalid stock retrieved_at') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Invalid stock retrieved_at')


def _stock_pixels(value):
    if not isinstance(value, dict) or set(value) != {'width', 'height', 'mode', 'variance'}:
        raise ValueError('Malformed stock pixels')
    for field in ('width', 'height'):
        dimension = value[field]
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError(f'Invalid stock pixel {field}')
    if not isinstance(value['mode'], str) or not value['mode'] or value['mode'] != value['mode'].strip():
        raise ValueError('Invalid stock pixel mode')
    variance = value['variance']
    values = variance if isinstance(variance, (list, tuple)) else (variance,)
    if not values or any(
            isinstance(item, bool) or not isinstance(item, (int, float)) or
            not math.isfinite(item) or item < 0
            for item in values):
        raise ValueError('Invalid stock pixel variance')


def _stock_depicted(value):
    if value is not None and not isinstance(value, str):
        raise ValueError('Invalid stock depicted field')


def stock_binding(image):
    """Validate and return the complete reviewed stock-image binding.

    The returned value deliberately retains every reviewed image field, not merely its
    provider and hash, so a receipt cannot silently downgrade rights or identity metadata.
    """
    if not isinstance(image, dict) or not isinstance(image.get('stock_provenance'), dict):
        raise ValueError('Missing stock image provenance')
    provenance = image['stock_provenance']
    provider = provenance.get('provider')
    if provider not in ('unsplash', 'pexels', 'wikimedia', 'google'):
        raise ValueError('Unsupported stock image provider')

    expected_provenance = set(_STOCK_PROVENANCE_COMMON)
    if provider == 'unsplash':
        expected_provenance.add('download_tracking')
    elif provider in ('wikimedia', 'google'):
        expected_provenance.update({'license', 'license_url'})
    if set(provenance) != expected_provenance:
        raise ValueError('Unexpected stock provenance fields')

    photo_id = _stock_photo_id(provenance['photo_id'], provider)
    photographer = _stock_nonempty(provenance['photographer'], 'photographer')
    profile_parts = urlsplit(provenance['photographer_url'])
    profile_host = profile_parts.hostname
    if provider == 'unsplash':
        profile_host = 'unsplash.com'
    elif provider == 'pexels':
        profile_host = 'www.pexels.com'
    elif provider == 'wikimedia':
        profile_host = 'commons.wikimedia.org'
    _stock_profile_url(provenance['photographer_url'], profile_host, 'photographer_url', provider)
    photo_parts = urlsplit(provenance['photo_url'])
    photo_host = photo_parts.hostname
    if provider == 'unsplash':
        photo_host = 'unsplash.com'
    elif provider == 'pexels':
        photo_host = 'www.pexels.com'
    elif provider == 'wikimedia':
        photo_host = 'commons.wikimedia.org'
    _stock_photo_url(
        provenance['photo_url'],
        photo_host,
        photo_id,
        provider,
    )
    _stock_nonempty(provenance['query'], 'query')
    _stock_retrieved_at(provenance['retrieved_at'])
    image_parts = urlsplit(provenance['image_url'])
    image_host = image_parts.hostname
    if provider == 'unsplash':
        image_host = 'images.unsplash.com'
    elif provider == 'pexels':
        image_host = 'images.pexels.com'
    elif provider == 'wikimedia':
        image_host = 'upload.wikimedia.org'
    _stock_image_url(provenance['image_url'], image_host, 'image_url')
    if provider in ('wikimedia', 'google'):
        _stock_nonempty(provenance['license'], 'provenance license')
        _stock_https(provenance['license_url'], urlsplit(provenance['license_url']).hostname,
                     'provenance license_url')

    if provider == 'unsplash':
        tracking = provenance['download_tracking']
        if not isinstance(tracking, dict) or set(tracking) != {'url', 'successful'}:
            raise ValueError('Malformed stock download tracking')
        if tracking['successful'] is not True:
            raise ValueError('Stock download was not tracked successfully')
        tracking_url = _stock_https(
            tracking['url'], 'api.unsplash.com', 'download_tracking.url'
        )
        if tracking_url.path != f'/photos/{photo_id}/download':
            raise ValueError('Stock download identity mismatch')
    if not isinstance(image.get('stock_provenance_sha256'), str) or not re.fullmatch(
            SHA, image['stock_provenance_sha256']):
        raise ValueError('Malformed stock provenance hash')
    if image['stock_provenance_sha256'] != digest(provenance):
        raise ValueError('Stock provenance hash mismatch')

    review_fields = set(image) & {'classifier_output', 'relevance_check'}
    if review_fields and review_fields != {'classifier_output', 'relevance_check'}:
        raise ValueError('Incomplete image classifier provenance')
    if provider in ('wikimedia', 'google') and review_fields != {
            'classifier_output', 'relevance_check'}:
        raise ValueError('Open-source image lacks classifier provenance')
    if review_fields:
        from .imagery import validate_image_decision, validate_relevance_record
        validate_image_decision(image['classifier_output'])
        validate_relevance_record(image['relevance_check'])
    if provider == 'unsplash':
        expected_image = _STOCK_IMAGE_COMMON | {'hotlink'}
    else:
        expected_image = _STOCK_IMAGE_COMMON | {'local_path', 'sha256'}
        if 'hotlink' in image:
            expected_image.add('hotlink')
    expected_image |= review_fields
    if 'pixel_review' in image:
        from .imagery import validate_pixel_review
        validate_pixel_review(image)
        expected_image.add('pixel_review')
    if set(image) != expected_image:
        raise ValueError('Unexpected stock image fields')
    if image['generated'] is not False:
        raise ValueError('Stock image must not be generated')
    _stock_pixels(image['pixels'])
    _stock_depicted(image['depicted'])
    for field in ('alt', 'caption', 'credit', 'license', 'license_url', 'url', 'source_url'):
        _stock_nonempty(image[field], field)
    if image['source_url'] != provenance['photo_url']:
        raise ValueError('Stock source URL mismatch')
    if image['caption'] not in {
            'Arkistokuva artikkelin aiheesta.',
            'Arkistokuva. Kuva ei esitä uutisen tapahtumaa.',
            'Arkistokuva artikkelin aiheesta. Kuva ei esitä uutisen tapahtumapaikkaa.',
    }:
        raise ValueError('Stock image caption is invalid')
    provider_label = {
        'unsplash': 'Unsplash', 'pexels': 'Pexels', 'wikimedia': 'Wikimedia Commons',
        'google': 'Google Custom Search',
    }[provider]
    if image['credit'] != f'Photo by {photographer} on {provider_label}':
        raise ValueError('Stock image credit is invalid')

    if provider == 'unsplash':
        if image['license'] != 'Unsplash License' or image['license_url'] != 'https://unsplash.com/license':
            raise ValueError('Unsplash license is invalid')
        if image['url'] != provenance['image_url'] or image['hotlink'] is not True:
            raise ValueError('Unsplash image URL/hotlink mismatch')
    else:
        if provider == 'pexels' and (
                image['license'] != 'Pexels License' or
                image['license_url'] != 'https://www.pexels.com/license/'):
            raise ValueError('Pexels license is invalid')
        if provider in ('wikimedia', 'google'):
            _stock_nonempty(image['license'], 'open-source license')
            _stock_https(image['license_url'], urlsplit(image['license_url']).hostname,
                         'open-source license_url')
            if (image['license'] != provenance['license'] or
                    image['license_url'] != provenance['license_url']):
                raise ValueError('Open-source licence provenance mismatch')
        if not isinstance(image['sha256'], str) or not re.fullmatch(SHA, image['sha256']):
            raise ValueError('Local open-source image hash is invalid')
        if image['local_path'] != f"media/{image['sha256']}.jpg":
            raise ValueError('Local open-source image path is invalid')
        if image['url'] != f"https://uutistenlukija.fi/media/{image['sha256']}.jpg":
            raise ValueError('Local open-source image URL is invalid')
        if 'hotlink' in image and image['hotlink'] is not False:
            raise ValueError('Pexels image must not be hotlinked')

    return deepcopy(image)


def media(packet, draft, policy_gate=True):
    validate_draft(draft, packet)
    if packet.get('fixture') is not False or packet.get('private_only') is True:
        raise ValueError('Fixture/private-only packet cannot be public')
    # An official release is a packet carrying a text publication_basis. It must satisfy the
    # full text policy/provider/source/reuse/rights contract below whether or not the draft
    # also carries an image, so a generated illustration can never displace text provenance.
    official = packet.get('publication_basis') is not None
    image_sha256 = None
    image = draft.get('image')
    stock = None
    if image is not None:
        if 'stock_provenance' in image or 'stock_provenance_sha256' in image:
            stock = stock_binding(image)
        # An official text source cannot authorise a third-party IMAGE: its reuse terms cover
        # its text, not its photography, so a scraped source image has no licence basis.
        # A GENERATED illustration is different in kind - it depicts no real person, event or
        # copyrighted work, so there is no third-party right to authorise. It is admitted only
        # when it carries the full generation provenance recorded by news_mvp/imagery.py, and
        # it is always labelled as an AI illustration rather than documentary evidence.
        generated = image.get('generated') is True
        if official and not generated and stock is None:
            raise ValueError('Text-only policy cannot authorize a third-party image')
        if stock is not None:
            image_sha256 = stock.get('sha256')
        else:
            sha = image.get('sha256', '')
            if not re.fullmatch(SHA, sha) or image.get('local_path') != f'media/{sha}.jpg':
                raise ValueError('Required reviewed local image is absent')
            if generated:
                for field in ('model', 'prompt_sha256', 'prompt_version', 'subject'):
                    if not image.get(field):
                        raise ValueError(f'Generated image is missing its {field} provenance')
                if not re.fullmatch(SHA, str(image.get('prompt_sha256'))):
                    raise ValueError('Generated image prompt hash is malformed')
                if 'AI' not in str(image.get('credit', '')):
                    raise ValueError('Generated image must be credited as AI-generated')
            image_sha256 = sha
        if not official:
            # The packet claims no text policy, so it has no text provenance to bind; the
            # image-only binding is labelled as such instead of leaving the field absent.
            result = {'image_sha256': image_sha256, 'text_provenance': 'not-applicable'}
            if stock is not None:
                result['stock_image'] = stock
            return result
    from .official import policy, reuse
    spec = policy()
    basis = packet.get('publication_basis', {})
    # policy_gate=False is used when RE-RENDERING an article that was already released: the
    # digest binds a packet to the policy in force at release time, so re-applying today's
    # policy to yesterday's approved article fails every historical page. The structural
    # checks below (provider, article pattern, publisher, reuse terms, rights evidence,
    # source byte hashes) still run in full, so provenance is still enforced.
    if policy_gate and (basis.get('policy') != TEXT_POLICY or basis.get('policy_sha256') != digest(spec)):
        raise ValueError('Missing exact text-only policy')
    if basis.get('policy') != TEXT_POLICY:
        raise ValueError('Missing exact text-only policy')
    provider = spec['providers'].get(basis.get('provider'))
    sources = packet.get('sources', [])
    if provider is None or not sources:
        raise ValueError('Unapproved text-only provider/source count')
    # Source A is the official source itself and carries the provenance that matters: its URL
    # must match the approved article pattern and its reuse record must equal the provider's
    # pinned terms. Related sources (B..H) are corroboration found by search, so they are not
    # required to come from this provider - but each one is still structurally checked below
    # (real HTTPS URL, publisher, title, substantive text, freshness) by validate_packet, and
    # they can never be the basis of the release on their own.
    source = sources[0]
    if (not re.fullmatch(provider['article_pattern'], source['url']) or
        packet['story_key'] != 'url:'+source['url'] or source['publisher'] != provider['publisher']):
        raise ValueError('Source/reuse policy mismatch')
    # The reuse record is policy-coupled: it is generated from the provider's declared licence,
    # so editing a provider's terms (or adding one) changes it for every historical article.
    # policy_gate=False means "this article was already released under the policy in force then",
    # so its captured reuse record must not be re-derived from today's policy - the same reason
    # the digest check is skipped. Structural provenance above still runs, and verify_intake
    # binds the article to its captured bytes. Re-running this gate for the archive is what
    # made every historical page fail to render after a licence edit, blocking all publishing.
    if policy_gate and source.get('reuse') != reuse(provider):
        raise ValueError('Source/reuse policy mismatch')
    if len(sources) > MAX_PACKET_SOURCES:
        raise ValueError('Too many sources for a reviewed release')
    for extra in sources[1:]:
        if not extra.get('related'):
            raise ValueError('Additional sources must be marked as related corroboration')
        if not str(extra.get('url', '')).startswith('https://'):
            raise ValueError('Related source must be a real HTTPS URL')
        if extra.get('publisher') == provider['publisher']:
            raise ValueError('A publisher cannot corroborate itself')
    docs = packet.get('supporting_documents', [])
    if len(docs) != 1:
        raise ValueError('Missing exact rights evidence')
    rights = docs[0]
    if (rights.get('id') != 'RIGHTS' or rights.get('url') != provider['rights_url'] or
        hashlib.sha256(rights.get('text','').encode()).hexdigest() != provider['rights_text_sha256'] or
        not re.fullmatch(SHA, rights.get('sha256','')) or
        not re.fullmatch(SHA, basis.get('source_sha256','')) or
        basis.get('source_fields_sha256') != digest(source)):
        raise ValueError('Rights/source provenance mismatch')
    result = {'image_sha256': image_sha256, 'text_only': {'policy':TEXT_POLICY,'policy_sha256':digest(spec),
            'provenance_sha256':digest({'basis':basis,'sources':sources,'rights':docs})}}
    if stock is not None:
        result['stock_image'] = stock
    return result


def _original_intake(packet, root):
    """Find the unique stored text-only original behind a generated illustration.

    The controller replaces a captured original (``image`` None, ``image_note`` present)
    with the reviewed generated image and drops ``image_note``, so the packet digest no
    longer names the intake directory that holds the captured bytes. Identity is the
    original directory name plus a full projection match: every key/value except ``image``
    and ``image_note`` must be equal, so a changed source/rights/policy/corroboration
    field can never match. Malformed unrelated candidates are skipped, never matched.
    """
    current = {key: value for key, value in packet.items() if key not in ('image', 'image_note')}
    try:
        children = sorted(root.iterdir())
    except OSError:
        children = []
    matches = []
    for child in children:
        if not child.is_dir():
            continue
        try:
            candidate = json.loads((child/'packet.json').read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(candidate, dict) or candidate.get('image') is not None:
            continue
        projected = {key: value for key, value in candidate.items() if key not in ('image', 'image_note')}
        if projected != current or child.name != digest(candidate):
            continue
        matches.append((child, candidate))
    if len(matches) != 1:
        raise ValueError('Generated intake original is missing or ambiguous')
    return matches[0]


def _archived_source_matches(raw, provider, source, parsed):
    """Recognise only the exact pre-51d01695 Valtioneuvosto extraction.

    New intake still requires today's extraction. Image-only archive corrections
    retain the already reviewed text, including historical headings/tag clouds.
    Every character must reproduce from the same hash-bound captured HTML.
    """
    if provider != 'valtioneuvosto' or any(source.get(k) != v for k,v in parsed.items() if k != 'text'):
        return False
    from .official import parse
    from .related import strip_navigation
    historical = parse(raw, lambda t,a:'journal-content-article' in a.get('class','').split()).text()
    return (source.get('text') == historical and
            parsed.get('text') == strip_navigation(historical))


def verify_intake(packet, state, *, archive_image_only=False):
    """Bind the stored, reviewed text to actual captured upstream bytes before release."""
    from .official import rights_text, source_fields, policy, ADDITIONAL_PROVIDERS
    basis = packet['publication_basis'];provider = basis['provider']
    directory = Path(state)/'intake'/digest(packet)
    intake_packet = packet
    stock = None
    if isinstance(packet.get('image'), dict) and (
            'stock_provenance' in packet['image'] or
            'stock_provenance_sha256' in packet['image']):
        # Validate before looking for the captured original: a malformed stock record must
        # never be able to fall through to the text-only intake projection.
        stock = stock_binding(packet['image'])
    if (not directory.is_dir() and isinstance(packet.get('image'), dict) and
            (packet['image'].get('generated') is True or stock is not None)):
        directory, intake_packet = _original_intake(packet, Path(state)/'intake')
    raw = (directory/'source.html').read_bytes();rights = (directory/'rights.html').read_bytes()
    if hashlib.sha256(raw).hexdigest() != basis['source_sha256'] or hashlib.sha256(rights).hexdigest() != packet['supporting_documents'][0]['sha256']:
        raise ValueError('Captured intake bytes changed')
    if rights_text(rights,provider) != packet['supporting_documents'][0]['text']:
        raise ValueError('Captured rights text changed')
    parsed = source_fields(raw,provider,packet['sources'][0]['url'])
    if any(packet['sources'][0].get(k) != v for k,v in parsed.items()):
        if not (archive_image_only and _archived_source_matches(raw, provider, packet['sources'][0], parsed)):
            raise ValueError('Captured source differs from reviewed packet')
    if provider in ADDITIONAL_PROVIDERS:
        receipt = json.loads((directory/'receipt.json').read_text())
        expected = {'fixture':False, 'provider':provider, 'source_url':packet['sources'][0]['url'],
                    'source_sha256':basis['source_sha256'], 'packet_sha256':digest(intake_packet),
                    'rights_url':packet['supporting_documents'][0]['url'],
                    'rights_sha256':packet['supporting_documents'][0]['sha256'],
                    'rights_text_sha256':policy()['providers'][provider]['rights_text_sha256'],
                    'publication_basis':basis, 'image_status':'explicit-text-only',
                    'retrieved_at':packet['supporting_documents'][0]['retrieved_at']}
        if receipt != expected or json.loads((directory/'packet.json').read_text()) != intake_packet:
            raise ValueError('Captured intake receipt/packet identity mismatch')



def receipt_media(receipt):
    # Absence is the original legacy schema; no v2 fields may leak into it.
    if 'schema_version' not in receipt:
        legacy={'public_release_authorized','hermes_step','origin','ga4_id','source_commit',
                'job_id','packet_sha256','draft_sha256','image_sha256','new_article_files','files'}
        sha=receipt.get('image_sha256')
        if set(receipt)!=legacy or not isinstance(sha,str) or not re.fullmatch(SHA,sha):
            raise ValueError('Ambiguous or invalid legacy receipt')
        return {'image_sha256':sha}
    if type(receipt['schema_version']) is not int or receipt['schema_version']!=2:
        raise ValueError('Unknown receipt schema version')
    required={'packet','draft','review','packet_sha256','draft_sha256','image_sha256'}
    if not required <= receipt.keys():
        raise ValueError('Missing v2 receipt fields')
    packet,draft,review=(receipt[k] for k in ('packet','draft','review'))
    if receipt['packet_sha256']!=digest(packet) or receipt['draft_sha256']!=digest(draft):
        raise ValueError('Receipt packet/draft mismatch')
    if not validate_review(review,draft)['approved']:
        raise ValueError('Unapproved receipt')
    expected=media(packet,draft)
    actual={'image_sha256':receipt['image_sha256']}
    if 'stock_image' in receipt:
        actual['stock_image']=receipt['stock_image']
    if 'text_only' in receipt:actual['text_only']=receipt['text_only']
    if 'text_provenance' in receipt:
        if receipt['text_provenance']!='not-applicable':
            raise ValueError('Unexpected text provenance')
        actual['text_provenance']=receipt['text_provenance']
    if 'text_only' not in receipt and 'text_provenance' not in receipt:
        # v2 image-only receipts predate text provenance. They stay admissible only for packets
        # that claim no official publication_basis, whose media binding is exactly the image
        # hash; an official packet missing its text binding is rejected, never inferred.
        if packet.get('publication_basis') is not None:
            raise ValueError('Official receipt is missing its text binding')
        if set(expected)!={'image_sha256','text_provenance'}:
            raise ValueError('Receipt media/provenance mismatch')
        expected={'image_sha256':expected['image_sha256']}
    if expected!=actual:
        raise ValueError('Receipt media/provenance mismatch')
    return expected


def _denormalize_cdn_email_obfuscation(html):
    """Undo a CDN's automatic e-mail obfuscation so reviewed text can be compared.

    Cloudflare rewrites any plain address in served HTML into
    ``<a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="...">[email&#160;protected]</a>``,
    encoding the original with a reversible single-byte XOR (first byte = key).
    The canonical readback fetches the *live* page, so without this the verifier
    compares reviewed prose against proxy-rewritten markup and fails even though
    the published article is byte-correct — which stalled publication on every
    article whose body cites an address.

    Only this well-known, reversible transform is undone. Any other difference
    still fails the content contract.
    """
    import re as _re

    pattern = _re.compile(
        r'<a[^>]*\bdata-cfemail="([0-9a-fA-F]+)"[^>]*>.*?</a>',
        _re.DOTALL,
    )

    def restore(match):
        encoded = match.group(1)
        try:
            raw = bytes.fromhex(encoded)
        except ValueError:
            return match.group(0)
        if len(raw) < 2:
            return match.group(0)
        key = raw[0]
        try:
            return "".join(chr(byte ^ key) for byte in raw[1:])
        except ValueError:
            return match.group(0)

    return pattern.sub(restore, html)


class _RenderedStockMarkup(HTMLParser):
    """Collect visible text, image attributes and attribution anchors from a page."""

    _IGNORED = frozenset({'script', 'style', 'noscript', 'template'})
    _VOID = frozenset({'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self.anchors = []
        self.visible = []
        self.overlays = []
        self._anchor_stack = []
        self._overlay_stack = []
        self._element_stack = []
        self._ignored = 0
        self._hidden = 0
        self._hero_depth = 0
        self._rights_depth = 0
        self.invalid = False

    def _attributes(self, attrs):
        values = {}
        duplicate = False
        for name, value in attrs:
            name = name.lower()
            duplicate = duplicate or name in values
            values[name] = value
        self.invalid = self.invalid or duplicate
        return values, duplicate

    @staticmethod
    def _is_hidden(values, classes):
        if 'hidden' in values or 'visually-hidden' in classes:
            return True
        if (values.get('aria-hidden') or '').strip().lower() == 'true':
            return True
        style = values.get('style') or ''
        for declaration in style.split(';'):
            name, separator, value = declaration.partition(':')
            if not separator:
                continue
            name = name.strip().lower()
            value = value.strip().lower()
            value = re.sub(r'\s*!important\s*$', '', value)
            if name == 'display' and value == 'none':
                return True
            if name == 'visibility' and value in ('hidden', 'collapse'):
                return True
        return False

    def _start(self, tag, attrs):
        values, duplicate = self._attributes(attrs)
        tag = tag.lower()
        if tag in ('picture', 'source'):
            self.invalid = True
        if tag == 'img':
            self.images.append({
                'src': values.get('src'),
                'srcset': values.get('srcset'),
                'alt': values.get('alt'),
                'width': values.get('width'),
                'height': values.get('height'),
                'duplicate': duplicate,
            })
        classes = set((values.get('class') or '').split())
        hidden = bool(self._hidden or self._is_hidden(values, classes))
        if 'article-hero' in classes:
            self._hero_depth += 1
        if 'image-rights' in classes:
            self._rights_depth += 1
        frame = {'tag': tag, 'classes': classes, 'hidden': hidden,
                 'ignored': tag in self._IGNORED,
                 'index': len(self._element_stack)}
        self._element_stack.append(frame)
        if hidden:
            self._hidden += 1
        if tag in self._IGNORED:
            self._ignored += 1
        if tag == 'a':
            record = {
                'href': values.get('href'),
                'text': [],
                'hero': self._hero_depth > 0,
                'rights': self._rights_depth > 0,
                'hidden': hidden or bool(self._ignored),
            }
            self.anchors.append(record)
            self._anchor_stack.append(record)
        for kind, class_name in (('label', 'portal-lead__image-label'),
                                 ('credit', 'portal-lead__credit')):
            if class_name in classes:
                record = {'kind': kind, 'text': [], 'hero': self._hero_depth > 0}
                self.overlays.append(record)
                self._overlay_stack.append((frame['index'], record))

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs)
        if tag.lower() in self._VOID:
            self._end(tag.lower())

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs)
        self._end(tag.lower())

    def _end(self, tag):
        tag = tag.lower()
        if not self._element_stack:
            self.invalid = True
            return
        frame = self._element_stack[-1]
        if frame['tag'] != tag:
            self.invalid = True
            return
        self._element_stack.pop()
        if frame['hidden'] and self._hidden:
            self._hidden -= 1
        if frame['ignored'] and self._ignored:
            self._ignored -= 1
        if tag == 'a':
            if not self._anchor_stack:
                self.invalid = True
            else:
                self._anchor_stack.pop()
        while self._overlay_stack and self._overlay_stack[-1][0] == frame['index']:
            self._overlay_stack.pop()
        if 'article-hero' in frame['classes'] and self._hero_depth:
            self._hero_depth -= 1
        if 'image-rights' in frame['classes'] and self._rights_depth:
            self._rights_depth -= 1

    def handle_endtag(self, tag):
        self._end(tag)

    def handle_data(self, data):
        if self._ignored or self._hidden:
            return
        self.visible.append(data)
        for record in self._anchor_stack:
            record['text'].append(data)
        for _tag, record in self._overlay_stack:
            record['text'].append(data)


def _stock_visible_text(value):
    return ' '.join(str(value).split())


def _stock_anchor_text(anchor):
    return _stock_visible_text(''.join(anchor['text']))


def _stock_has_anchor(anchors, href, text, scope):
    expected = _stock_visible_text(text)
    return any(anchor['href'] == href and not anchor['hidden'] and
               anchor.get(scope) and _stock_anchor_text(anchor) == expected
               for anchor in anchors)


def _check_rendered_stock(html, image):
    """Require the reviewed stock binding and its exact public presentation."""
    sources = _ImageSources()
    rendered = _RenderedStockMarkup()
    try:
        sources.feed(html)
        sources.close()
        rendered.feed(html)
        rendered.close()
    except Exception:
        raise ValueError('Malformed stock article markup') from None
    if (rendered.invalid or rendered._anchor_stack or rendered._overlay_stack or
            rendered._element_stack or sources.has_alternative or
            html.lower().count('<img') != len(sources.images) or
            len(sources.images) != len(rendered.images)):
        raise ValueError('Malformed stock article markup')

    editorial = [index for index, item in enumerate(sources.images) if not item['chrome']]
    if len(editorial) != 1:
        raise ValueError('Stock article must have exactly one editorial image')
    editorial_index = editorial[0]
    for index, item in enumerate(sources.images):
        rendered_image = rendered.images[index]
        if (item['duplicate'] or item['srcset'] is not None or item['alternative'] or
                rendered_image['duplicate'] or rendered_image['srcset'] is not None):
            raise ValueError('Stock article image has duplicate or alternate markup')
        if item['chrome']:
            if item['src'] not in BRANDING_LOGO_SRCS:
                raise ValueError('Stock article has an unapproved branding image')
        elif index != editorial_index:
            raise ValueError('Stock article has an unexpected editorial image')
    if any(item['srcset'] is not None for item in sources.images):
        raise ValueError('Stock article has an alternate image source')

    rendered_image = rendered.images[editorial_index]
    provider = image['stock_provenance']['provider']
    provider_text = {
        'unsplash': 'Unsplash', 'pexels': 'Pexels', 'wikimedia': 'Wikimedia Commons',
        'google': 'Google Custom Search',
    }.get(provider, provider.title())
    expected_src = (image['url'] if provider == 'unsplash'
                    else f'/mvp-assets/{image["sha256"]}.jpg')
    if rendered_image['src'] != expected_src:
        raise ValueError('Stock article image URL mismatch')
    if rendered_image['alt'] != image['alt']:
        raise ValueError('Stock article image alt mismatch')
    pixels = image['pixels']
    if (rendered_image['width'] != str(pixels['width']) or
            rendered_image['height'] != str(pixels['height'])):
        raise ValueError('Stock article image dimensions mismatch')

    visible = _stock_visible_text(''.join(rendered.visible))
    expected_credit = image['credit']
    for required in (image['caption'], image['license'], image['stock_provenance']['photographer'],
                     provider_text, expected_credit):
        if _stock_visible_text(required) not in visible:
            raise ValueError('Missing visible stock attribution')
    hero_labels = [_stock_visible_text(''.join(item['text'])) for item in rendered.overlays
                   if item['kind'] == 'label' and item['hero']]
    hero_credits = [_stock_visible_text(''.join(item['text'])) for item in rendered.overlays
                    if item['kind'] == 'credit' and item['hero']]
    if hero_labels.count('Arkistokuva') != 1 or _stock_visible_text(expected_credit) not in hero_credits:
        raise ValueError('Missing stock hero overlay attribution')

    photographer = image['stock_provenance']['photographer']
    photographer_url = image['stock_provenance']['photographer_url']
    hero_anchors = [anchor for anchor in rendered.anchors if anchor['hero']]
    rights_anchors = [anchor for anchor in rendered.anchors if anchor['rights']]
    required_hero = [(image['source_url'], provider_text)]
    required_rights = [(image['license_url'], image['license']),
                       (image['source_url'], provider_text),
                       (image['source_url'], 'Kuvan lähde')]
    if provider == 'unsplash':
        required_hero.append((photographer_url, photographer))
        required_rights.append((photographer_url, photographer))
    if (any(not _stock_has_anchor(hero_anchors, href, text, 'hero')
            for href, text in required_hero) or
            any(not _stock_has_anchor(rights_anchors, href, text, 'rights')
                for href, text in required_rights)):
        raise ValueError('Stock article attribution link mismatch')


def check_article(html,packet,draft,canonical=None):
    """Same reviewed content contract for bundle validation and canonical readback."""
    from html import escape
    esc=lambda value:escape(str(value),quote=True)
    # Live readback goes through the CDN, which obfuscates plain addresses in
    # served markup. Compare against the de-obfuscated copy so the contract
    # checks reviewed content rather than proxy rewriting.
    html=_denormalize_cdn_email_obfuscation(html)
    required=[draft['title'],draft['summary']]+[p['text'] for p in draft['paragraphs']]
    for source in packet['sources']:
        required.append(source['url'])
        if source.get('reuse'):
            required += [source['reuse']['url'],source['reuse']['license'],source['reuse']['changes']]
            if 'notice' in source['reuse']: required.append(source['reuse']['notice'])
            if 'license_url' in source['reuse'] and ('href="'+esc(source['reuse']['license_url'])+'"') not in html:
                raise ValueError('Missing direct reuse licence link')
    image=draft.get('image')
    if image is None:
        # 'Luonnos' as a bare word is not a marker: a cited source title can legitimately
        # contain it ("Luonnos yritystukien ...", a draft-bill name in the citation JSON-LD,
        # first hit 2026-09-18). The private-preview marker that matters is the banner.
        # A text-only page may still carry the exact brand logo inside header/footer
        # chrome; every editorial or foreign image stays rejected.
        if not _only_branding_images(html) or 'Tämä uutinen julkaistaan ilman kuvaa.' not in html or 'Yksityinen esikatselu' in html:
            raise ValueError('Dishonest text-only public page')
    else:
        stock = None
        stock_candidate = (
            'stock_provenance' in image or 'stock_provenance_sha256' in image or
            image.get('hotlink') is True or image.get('license') in
            ('Unsplash License', 'Pexels License')
        )
        if stock_candidate:
            stock = stock_binding(image)
        required += [image['license_url']]
        if image.get('generated') is True:
            # A generated illustration presents its licence through the /kuvituskuvat/ terms
            # link plus the AI credit and illustration caption. The reader credit is now
            # normalised to 'AI-kuvitus'; the stored legacy credit stays admissible so pages
            # already published against it remain valid. The stored model name is internal
            # and is never required in reader markup. The first generated-image release
            # failed live readback only because this check still demanded an internal label
            # (2026-09-18).
            required += [image['caption']]
            if esc(GENERATED_READER_CREDIT) not in html and esc(image['credit']) not in html:
                raise ValueError('Missing generated illustration credit')
        elif stock is not None:
            _check_rendered_stock(html, stock)
        else:
            required += [image['license']]
    if any(esc(value) not in html for value in required):
        raise ValueError('Public article differs from reviewed content/licence')
    if canonical is not None and ('href="'+esc(canonical)+'"') not in html:
        raise ValueError('Canonical article URL mismatch')


def deployment_record(receipt, deployment, commit):
    """Used by the actual Actions command and isolated tests."""
    binding = receipt_media(receipt)
    if deployment['environment'] != 'production' or deployment['latest_stage']['status'] != 'success' or deployment['deployment_trigger']['metadata']['commit_hash'] != commit:
        raise ValueError('Deployment identity mismatch')
    record = {'deployment_id':deployment['id'],'deployment_url':deployment['url'],
            'canonical_origin':'https://uutistenlukija.fi','remote_commit':commit,
            'source_commit':receipt['source_commit'],'packet_sha256':receipt['packet_sha256'],
            'draft_sha256':receipt['draft_sha256'],'job_id':receipt['job_id'],**binding}
    if receipt.get('image_backfill'):
        if digest(receipt['image_backfill']) != receipt.get('image_backfill_sha256'):
            raise ValueError('Archive correction deployment binding mismatch')
        record['image_backfill_sha256'] = receipt['image_backfill_sha256']
    return record

# --- Deliberate legacy redirect inventory and pure validation -----------------
#
# Item 2 recovery is data-driven: `news_mvp/legacy_redirects.json` records the reviewed
# legacy demand inventory, and only explicitly reviewed equivalence mappings may ever be
# emitted as redirects. Nothing in this block reads live directories, the production
# database, or the network: the eligible canonical article paths are trusted caller input
# supplied by the release path that knows which articles the bundle actually renders.

LEGACY_REDIRECTS = Path(__file__).with_name('legacy_redirects.json')
REDIRECT_STATUS = 301
# Cloudflare Pages limits: 2000 static redirect rules and 1000 characters per rule line.
REDIRECT_MAX_LINES = 2000
REDIRECT_MAX_LINE_CHARS = 1000

_LEGACY_DOCUMENT_KEYS = {'schema_version', 'reviewed_at', 'review', 'window', 'bound',
                         'totals', 'inventory', 'mappings'}
_LEGACY_REVIEW_KEYS = {'rationale', 'evidence', 'report', 'deployed_catalog_size'}
_LEGACY_WINDOW_KEYS = {'source', 'start', 'end', 'timezone', 'final', 'lag_days'}
_LEGACY_BOUND_KEYS = {'source_row_cap', 'cap_reached', 'exhaustive', 'selection', 'note'}
_LEGACY_TOTALS_KEYS = {'rows', 'clicks', 'impressions'}
_LEGACY_ROW_KEYS = {'source', 'clicks', 'impressions', 'http_status', 'equivalence'}
_MAPPING_KEYS = {'source', 'target', 'reviewed', 'review'}
_MAPPING_REVIEW_KEYS = {'rationale', 'evidence'}
# ASCII same-origin paths only. The set deliberately excludes '%' (encoding bypass),
# '*', '<', '>', '{', '}' (wildcards/placeholders), '?', '#' (query/fragment), ':'
# (scheme/host confusion), backslash, whitespace and every control character.
_PATH_CHARS = re.compile(r'[A-Za-z0-9._~/-]+\Z')


def _redirect_path(value, label, article=False):
    """Exact, safe, same-origin absolute path with a trailing slash; fail closed."""
    if not isinstance(value, str) or value.startswith('//') or not value.startswith('/'):
        raise ValueError(f'Unsafe {label}: not an exact same-origin path')
    if len(value) < 2 or not value.endswith('/') or not _PATH_CHARS.match(value):
        raise ValueError(f'Unsafe {label}: forbidden characters or shape')
    segments = value.split('/')[1:-1]
    if any(segment in ('', '.', '..') for segment in segments):
        raise ValueError(f'Unsafe {label}: empty or traversal path segment')
    if article and len(segments) < 2:
        raise ValueError(f'Unsafe {label}: not a canonical article path')
    return value


def _redirect_review(review):
    """Reviewed equivalence needs a stated rationale and cited evidence, not a flag."""
    if not isinstance(review, dict) or set(review) != _MAPPING_REVIEW_KEYS:
        raise ValueError('Malformed legacy mapping review')
    rationale = review['rationale']
    evidence = review['evidence']
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError('Legacy mapping review lacks a rationale')
    if isinstance(evidence, str):
        evidence = [evidence]
    if (not isinstance(evidence, (list, tuple)) or not evidence or
            any(not isinstance(item, str) or not item.strip() for item in evidence)):
        raise ValueError('Legacy mapping review lacks evidence')
    return {'rationale': rationale.strip(), 'evidence': [item.strip() for item in evidence]}


def _eligible_prefixes(eligible):
    """Ancestor path prefixes of eligible canonicals; used to detect source shadowing."""
    prefixes = set()
    for canonical in eligible:
        segments = canonical.split('/')[1:-1]
        for index in range(1, len(segments) + 1):
            prefixes.add('/' + '/'.join(segments[:index]) + '/')
    return prefixes


def _legacy_count(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'Malformed legacy {label}')
    return value


def _legacy_document(document):
    """Fail-closed structural validation of the reviewed inventory data file."""
    if not isinstance(document, dict) or set(document) != _LEGACY_DOCUMENT_KEYS:
        raise ValueError('Malformed legacy redirect document')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('Unknown legacy redirect schema version')
    if not isinstance(document['reviewed_at'], str) or not document['reviewed_at'].strip():
        raise ValueError('Legacy redirect document lacks its review date')
    review = document['review']
    if not isinstance(review, dict) or set(review) - _LEGACY_REVIEW_KEYS:
        raise ValueError('Malformed legacy redirect review')
    _redirect_review({'rationale': review.get('rationale'), 'evidence': review.get('evidence')})
    if 'report' in review and (not isinstance(review['report'], str) or not review['report'].strip()):
        raise ValueError('Malformed legacy redirect review report')
    if 'deployed_catalog_size' in review:
        _legacy_count(review['deployed_catalog_size'], 'review catalog size', minimum=1)
    window = document['window']
    if not isinstance(window, dict) or set(window) - _LEGACY_WINDOW_KEYS:
        raise ValueError('Malformed legacy evidence window')
    from datetime import date
    if not isinstance(window.get('source'), str) or not window['source'].strip():
        raise ValueError('Legacy evidence window lacks its source')
    for key in ('start', 'end'):
        value = window.get(key)
        if not isinstance(value, str):
            raise ValueError('Malformed legacy evidence window date')
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError('Malformed legacy evidence window date') from None
    if window.get('final') is not True:
        raise ValueError('Legacy evidence window is not final data')
    if 'lag_days' in window:
        _legacy_count(window['lag_days'], 'evidence window lag')
    if 'timezone' in window and (not isinstance(window['timezone'], str) or not window['timezone'].strip()):
        raise ValueError('Malformed legacy evidence window timezone')
    bound = document['bound']
    if not isinstance(bound, dict) or set(bound) - _LEGACY_BOUND_KEYS:
        raise ValueError('Malformed legacy evidence bound')
    _legacy_count(bound.get('source_row_cap'), 'source row cap', minimum=1)
    for key in ('cap_reached', 'exhaustive'):
        if type(bound.get(key)) is not bool:
            raise ValueError(f'Malformed legacy evidence bound {key}')
    for key in ('selection', 'note'):
        if key in bound and (not isinstance(bound[key], str) or not bound[key].strip()):
            raise ValueError(f'Malformed legacy evidence bound {key}')
    totals = document['totals']
    if not isinstance(totals, dict) or set(totals) != _LEGACY_TOTALS_KEYS:
        raise ValueError('Malformed legacy inventory totals')
    inventory = document['inventory']
    if not isinstance(inventory, list) or not inventory:
        raise ValueError('Malformed legacy inventory rows')
    seen = set()
    clicks = impressions = 0
    for row in inventory:
        if not isinstance(row, dict) or set(row) != _LEGACY_ROW_KEYS:
            raise ValueError('Malformed legacy inventory row')
        source = _redirect_path(row['source'], 'inventory source')
        if source in seen:
            raise ValueError('Duplicate legacy inventory source')
        seen.add(source)
        if row['http_status'] != 404:
            raise ValueError('Legacy inventory row is not a missing page')
        if not isinstance(row['equivalence'], str) or not row['equivalence'].strip():
            raise ValueError('Legacy inventory row lacks its equivalence review')
        clicks += _legacy_count(row['clicks'], 'inventory clicks')
        impressions += _legacy_count(row['impressions'], 'inventory impressions')
    if (totals['rows'], totals['clicks'], totals['impressions']) != (len(inventory), clicks, impressions):
        raise ValueError('Legacy inventory totals do not match the rows')
    # Mapping entries are validated structurally here (shape, path safety, review evidence,
    # duplicates, chains); eligibility against rendered canonicals needs caller input and is
    # enforced by validate_legacy_mappings on the release path.
    _legacy_mapping_records(document['mappings'])
    return document


def load_legacy_redirects(path=None):
    """Read and fully validate the reviewed inventory; malformed data fails closed."""
    source = Path(path) if path is not None else LEGACY_REDIRECTS
    try:
        document = json.loads(source.read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Legacy redirect inventory is unreadable or malformed') from error
    return _legacy_document(document)


def legacy_inventory(document):
    """Reviewed inventory summary: exact counts, measured totals and the source paths."""
    rows = document['inventory']
    return {'rows': len(rows), 'clicks': document['totals']['clicks'],
            'impressions': document['totals']['impressions'],
            'paths': [row['source'] for row in rows],
            'mapped': [mapping['source'] for mapping in document['mappings']]}


def _legacy_mapping_records(mappings):
    """Per-record structural gate: shape, exact safe paths, review evidence, duplicates, chains."""
    if not isinstance(mappings, (list, tuple)):
        raise ValueError('Malformed legacy mapping list')
    normalized = []
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or set(mapping) != _MAPPING_KEYS:
            raise ValueError(f'Malformed legacy mapping at index {index}')
        source = _redirect_path(mapping['source'], 'mapping source')
        target = _redirect_path(mapping['target'], 'mapping target', article=True)
        if mapping['reviewed'] is not True:
            raise ValueError('Legacy mapping is not reviewed')
        if source == target:
            raise ValueError('Legacy mapping redirects a page to itself')
        normalized.append({'source': source, 'target': target, 'reviewed': True,
                           'review': _redirect_review(mapping['review'])})
    sources = [mapping['source'] for mapping in normalized]
    if len(sources) != len(set(sources)):
        raise ValueError('Duplicate legacy mapping source')
    if {mapping['target'] for mapping in normalized} & set(sources):
        raise ValueError('Legacy mapping chain or loop')
    return normalized


def validate_legacy_mappings(mappings, eligible_targets):
    """Pure review gate for explicit mappings against caller-provided eligible canonicals.

    `eligible_targets` is trusted explicit caller input: the exact canonical article paths
    the bundle renders. Every mapping must be reviewed with a rationale and evidence, must
    point at an eligible canonical, and must not shadow a live canonical, duplicate a
    source, chain or loop.
    """
    normalized = _legacy_mapping_records(mappings)
    eligible = {_redirect_path(path, 'eligible target', article=True) for path in eligible_targets}
    shadowed = _eligible_prefixes(eligible)
    for mapping in normalized:
        if mapping['target'] not in eligible:
            raise ValueError('Legacy mapping target is not an eligible canonical article')
        if mapping['source'] in shadowed:
            raise ValueError('Legacy mapping source shadows an eligible canonical article')
    return normalized


def legacy_redirect_lines(mappings, eligible_targets, extra_rules=()):
    """Deterministic `source target 301` lines for reviewed mappings plus generated aliases.

    `extra_rules` are (source, target) pairs generated by the release path (the existing
    hash-to-slug same-article aliases). They carry no equivalence claim, so they skip the
    editorial review requirement, but they pass every safety, eligibility, duplicate,
    shadowing, chain and loop check, and the union must fit the Cloudflare limits.
    """
    if not isinstance(extra_rules, (list, tuple)):
        raise ValueError('Malformed generated alias list')
    eligible = {_redirect_path(path, 'eligible target', article=True) for path in eligible_targets}
    shadowed = _eligible_prefixes(eligible)
    rules = {mapping['source']: mapping['target']
             for mapping in validate_legacy_mappings(mappings, eligible)}
    for rule in extra_rules:
        if not isinstance(rule, (list, tuple)) or len(rule) != 2:
            raise ValueError('Malformed generated alias rule')
        source, target = rule
        alias_source = _redirect_path(source, 'generated alias source')
        alias_target = _redirect_path(target, 'generated alias target', article=True)
        if alias_target not in eligible:
            raise ValueError('Generated alias target is not an eligible canonical article')
        if alias_source == alias_target:
            raise ValueError('Generated alias redirects a page to itself')
        if alias_source in shadowed:
            raise ValueError('Generated alias source shadows an eligible canonical article')
        if alias_source in rules:
            raise ValueError('Duplicate legacy redirect source')
        rules[alias_source] = alias_target
    if set(rules.values()) & set(rules):
        raise ValueError('Legacy redirect chain or loop')
    lines = [f'{source} {target} {REDIRECT_STATUS}' for source, target in sorted(rules.items())]
    if len(lines) > REDIRECT_MAX_LINES:
        raise ValueError('Too many static redirect lines')
    if any(len(line) > REDIRECT_MAX_LINE_CHARS for line in lines):
        raise ValueError('Static redirect line exceeds the character limit')
    return lines

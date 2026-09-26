"""Exact Pexels/CC0 grants from the identified photo, never related-photo metadata."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

LICENSES = {
    'Pexels': ('Pexels License', 'https://www.pexels.com/license/'),
    'CC0': ('CC0 1.0', 'https://creativecommons.org/publicdomain/zero/1.0/'),
}
MAX_HTML = 2 * 1024 * 1024
FIELDS = {'version', 'photo_id', 'photo_url', 'photographer', 'photographer_url',
          'image_path', 'license_code', 'license', 'license_url', 'retrieved_at',
          'response_sha256', 'transport'}


class _NextData(HTMLParser):
    def __init__(self):
        super().__init__(); self.documents = []; self.active = False

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == '__NEXT_DATA__':
            self.documents.append(''); self.active = True

    def handle_data(self, data):
        if self.active:
            self.documents[-1] += data

    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Ambiguous photo metadata')
        result[key] = value
    return result


def validate(evidence, candidate):
    if (not isinstance(evidence, dict) or set(evidence) != FIELDS or
            type(evidence['version']) is not int or evidence['version'] != 1 or
            any(not isinstance(evidence[key], str) for key in FIELDS - {'version'})):
        raise ValueError('Incomplete Pexels licence evidence')
    wanted = {'photo_id': candidate['photo_id'], 'photo_url': candidate['photo_page'],
              'photographer': candidate['name'], 'photographer_url': candidate['profile'],
              'image_path': urllib.parse.urlsplit(candidate['image_url']).path}
    if any(evidence[key] != value for key, value in wanted.items()):
        raise ValueError('Pexels licence identity mismatch')
    grant = LICENSES.get(evidence['license_code'])
    if grant is None or (evidence['license'], evidence['license_url']) != grant:
        raise ValueError('Unknown or mismatched Pexels grant')
    if not re.fullmatch(r'[0-9a-f]{64}', evidence['response_sha256']):
        raise ValueError('Missing exact photo-page hash')
    when = datetime.fromisoformat(evidence['retrieved_at'].replace('Z', '+00:00'))
    if when.utcoffset() is None or when.utcoffset().total_seconds() != 0:
        raise ValueError('Pexels grant timestamp must be UTC')
    if evidence['transport'] not in ('pexels_https', 'jina_reader', 'independent_browser'):
        raise ValueError('Unknown photo-page transport')
    return evidence


def from_html(raw, candidate, transport, retrieved_at=None):
    if not raw or len(raw) > MAX_HTML:
        raise ValueError('Invalid photo-page size')
    parser = _NextData(); parser.feed(raw.decode('utf-8')); parser.close()
    if len(parser.documents) != 1:
        raise ValueError('Missing or ambiguous main photo data')
    page = json.loads(parser.documents[0], object_pairs_hook=_pairs)['props']['pageProps']
    medium = page['medium']; attrs = medium['attributes']; user = attrs['user']
    identifier = candidate['photo_id']
    if (str(page['id']) != identifier or str(medium['id']) != identifier or
            str(attrs['id']) != identifier or medium['type'] != 'photo' or
            attrs['status'] != 'approved' or attrs['published'] is not True or attrs['pending'] is not False):
        raise ValueError('Main photo is not the expected published identity')
    name = ' '.join((str(user.get('first_name') or '') + ' ' + str(user.get('last_name') or '')).split())
    profile = 'https://www.pexels.com/@' + str(user['slug'])
    image = urllib.parse.urlsplit(attrs['image']['large'])
    if (name != candidate['name'] or profile.rstrip('/') != candidate['profile'].rstrip('/') or
            image.scheme != 'https' or image.hostname != 'images.pexels.com' or
            image.path != urllib.parse.urlsplit(candidate['image_url']).path):
        raise ValueError('Main photo author or pixel source mismatch')
    code = attrs['license']
    if code not in LICENSES:
        raise ValueError('Unrecognized photo-specific licence')
    evidence = dict(version=1, photo_id=identifier, photo_url=candidate['photo_page'],
        photographer=candidate['name'], photographer_url=candidate['profile'], image_path=image.path,
        license_code=code, license=LICENSES[code][0], license_url=LICENSES[code][1],
        retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(),
        response_sha256=hashlib.sha256(raw).hexdigest(), transport=transport)
    return validate(evidence, candidate)


def fetch(candidate, state_dir):
    """Bounded public read with a hash-checked cache; no API key is sent to pages/proxy."""
    from .imagery import _open
    from .site import atomic_write
    if not isinstance(candidate.get('photo_id'), str) or not re.fullmatch(r'[0-9]{1,20}', candidate['photo_id']):
        return None
    folder = Path(state_dir) / 'pexels-rights'
    receipt = folder / (candidate['photo_id'] + '.json')
    if receipt.is_file():
        try:
            previous = validate(json.loads(receipt.read_text()), candidate)
            raw = (folder / (previous['response_sha256'] + '.html')).read_bytes()
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous['retrieved_at'].replace('Z', '+00:00'))).total_seconds()
            if 0 <= age < 86400 and from_html(raw, candidate, previous['transport'], previous['retrieved_at']) == previous:
                return previous
        except (ValueError, KeyError, TypeError, OSError):
            pass
    routes = [('pexels_https', candidate['photo_page'], 'www.pexels.com', {}),
              ('jina_reader', 'https://r.jina.ai/' + candidate['photo_page'], 'r.jina.ai', {'X-Return-Format': 'html'})]
    for transport, url, host, extra in routes:
        try:
            request = urllib.request.Request(url, headers={'Accept': 'text/html', **extra})
            with _open(request, host, timeout=25, credentialed=False) as response:
                if response.status != 200:
                    return None
                raw = response.read(MAX_HTML + 1)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                return None
            continue
        except (OSError, ValueError):
            continue
        try:
            evidence = from_html(raw, candidate, transport)
        except (ValueError, KeyError, TypeError, UnicodeError):
            return None  # A contradictory successful response must never be hidden by another route.
        folder.mkdir(parents=True, exist_ok=True)
        body = folder / (evidence['response_sha256'] + '.html')
        if body.exists() and body.read_bytes() != raw:
            return None
        body.write_bytes(raw)
        atomic_write(receipt, json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return evidence
    return None

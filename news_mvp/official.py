"""Two pinned Finnish public sources, private preparation only; no media inference."""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from .editorial import ROOT, digest, timestamp, validate_packet, web_url
from .intake import fetch

POLICY = Path(__file__).resolve().parents[1] / 'sources/finnish-official.json'
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class Page(HTMLParser):
    """Extract visible text from selected source blocks; never script or navigation text."""
    def __init__(self, select):
        super().__init__()
        self.select, self.stack, self.parts = select, [], []
        self.meta, self.links, self.times = {}, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta':
            self.meta[a.get('property', a.get('name'))] = a.get('content', '')
        if tag == 'a' and a.get('href'):
            self.links.append(a)
        if tag == 'time' and a.get('datetime'):
            self.times.append(a['datetime'])
        inherited = self.stack[-1][1] if self.stack else False
        blocked = tag in ('script', 'style', 'nav', 'svg') or bool(self.stack and self.stack[-1][2])
        if tag not in VOID:
            self.stack.append((tag, inherited or self.select(tag, a), blocked))
        if tag in ('p', 'li', 'h1', 'h2', 'h3', 'br'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ('p', 'li', 'h1', 'h2', 'h3', 'div', 'section'):
            self.parts.append('\n')

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] and not self.stack[-1][2]:
            self.parts.append(data)

    def text(self):
        return '\n'.join(' '.join(line.split()) for line in ''.join(self.parts).splitlines() if line.strip())


def parse(raw, select):
    page = Page(select)
    page.feed(raw.decode('utf-8'))
    return page


def policy():
    data = json.loads(POLICY.read_text())
    if data['mode'] != 'official-text-v1' or data['max_source_age_hours'] != 48:
        raise ValueError('Unreviewed official-source policy')
    return data


def rights_text(raw, provider):
    if provider in ('kuntaliitto', 'ecb'):
        from .official_additional import rights_text as additional_rights
        return additional_rights(raw, provider)
    if provider == 'helsinki':
        page = parse(raw, lambda tag, a: 'notes' in a.get('class', '').split())
        licenses = [a['href'] for a in page.links if a.get('rel') == 'dc:rights']
        if set(licenses) != {'https://creativecommons.org/licenses/by/4.0/', 'https://creativecommons.org/licenses/by/4.0/deed.fi'}:
            raise ValueError('Missing exact dataset reuse licence')
        return page.text() + '\n' + licenses[0]
    page = parse(raw, lambda tag, a: tag == 'main')
    licenses = sorted({a['href'] for a in page.links if 'creativecommons.org/' in a['href']})
    if licenses != ['https://creativecommons.org/licenses/by/4.0/deed.fi']:
        raise ValueError('Missing exact Statistics Finland reuse licence')
    return page.text() + '\n' + licenses[0]


def response(url, hosts):
    raw, mime, final = fetch(url, hosts)
    if final != url or mime not in ('text/html', 'application/rss+xml', 'application/xml', 'text/xml'):
        raise ValueError('Unexpected official source response')
    return raw


def discover(config, now=None, excluded=(), errors=None, provider_only=None):
    """Round-robin bounded discovery; collection still verifies dates and current rights."""
    settings = config['discovery']
    limit = settings.get('max_candidates', 5)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('Discovery limit must be 1–5')
    now = now or datetime.now(timezone.utc)
    pools = []
    for provider, spec in policy()['providers'].items():
        if provider_only is not None and provider != provider_only:continue
        try:
            raw = response(spec['index'], spec['hosts'])
        except (ValueError,OSError) as error:
            if errors is None:raise
            errors.append({'provider':provider,'stage':'discovery','error':type(error).__name__})
            continue
        rows = []
        if provider in ('helsinki', 'ecb'):
            try:
                items = ET.fromstring(raw).findall('./channel/item')
            except ET.ParseError as error:
                raise ValueError('Invalid official RSS') from error
            for item in items[:50]:
                url = item.findtext('link', '')
                try:
                    date = parsedate_to_datetime(item.findtext('pubDate', ''))
                    if date.tzinfo is None:
                        raise ValueError('Missing RSS timezone')
                    age = (now-date).total_seconds()
                except (ValueError, TypeError):
                    continue
                if url not in excluded and 0 <= age <= 48*3600 and re.fullmatch(spec['article_pattern'], url):
                    rows.append({'family': 'finnish-official', 'provider': provider, 'url': url})
        else:
            page = parse(raw, lambda tag, a: tag == 'main')
            for a in [a for a in (page.links[:500] if provider == 'kuntaliitto' else page.links) if re.fullmatch(spec['article_pattern'],urljoin(spec['index'],a['href']))][:50]:
                url = urljoin(spec['index'], a['href'])
                if url not in excluded and re.fullmatch(spec['article_pattern'], url):
                    rows.append({'family': 'finnish-official', 'provider': provider, 'url': url})
        pools.append(list({r['url']: r for r in rows}.values())[:limit])
    result = []
    for i in range(limit):
        for rows in pools:
            if i < len(rows):
                result.append(rows[i])
    return result[:limit]


def source_fields(raw, provider, url=None):
    if provider in ('kuntaliitto', 'ecb'):
        from .official_additional import source_fields as additional_fields
        return additional_fields(raw, provider, url)
    if provider == 'helsinki':
        page = parse(raw, lambda tag, a: 'component--paragraph-text' in a.get('class', '').split() or 'component--lead-in' in a.get('class', '').split())
        published = page.meta.get('article:published_time')
    else:
        page = parse(raw, lambda tag, a: any(c.startswith(('julkaisu_ingressText__', 'julkaisu_publicationContent__')) for c in a.get('class', '').split()))
        # Publication page's native machine timestamp, never the index fetch time.
        times = {value for value in page.times if 'T' in value}
        if len(times) != 1:
            raise ValueError('Missing or ambiguous publication timestamp')
        published = next(iter(times))
        if datetime.strptime(page.meta.get('tk.published', ''), '%d.%m.%Y').date() != timestamp(published).date():
            raise ValueError('Publication date disagreement')
    title = page.meta.get('og:title', '').split(' | ')[0].strip()
    if not title or not published or len(page.text()) < 200:
        raise ValueError('Missing substantive source text, title or date')
    if re.search(r'all rights reserved|kaikki oikeudet pidätetään|tekijänoikeu|copyright|©', page.text(), re.I):
        raise ValueError('Article-specific rights statement requires manual review')
    return {'id': 'A', 'title': title, 'published_at': published, 'text': page.text()}


def collect(recipe, state_dir, now=None):
    now = now or datetime.now(timezone.utc)
    providers = policy()['providers']
    provider = recipe.get('provider')
    if provider not in providers:
        raise ValueError('Unknown official source')
    spec = providers[provider]
    if provider in ('kuntaliitto', 'ecb') and (not isinstance(recipe.get('url'), str) or not re.fullmatch(spec['article_pattern'], recipe['url'])):
        raise ValueError('Unapproved exact article URL token')
    url = web_url(recipe['url'])
    if not re.fullmatch(spec['article_pattern'], url):
        raise ValueError('Not an allowlisted article URL')
    rights = response(spec['rights_url'], spec['hosts'])
    permission = rights_text(rights, provider)
    if hashlib.sha256(permission.encode()).hexdigest() != spec['rights_text_sha256']:
        raise ValueError('Source reuse terms changed; independent review required')
    raw = response(url, spec['hosts'])
    source = {**source_fields(raw, provider, url), 'url': url, 'publisher': spec['publisher'],
              'reuse': reuse(spec)}
    packet = {'story_key': 'url:'+url, 'fixture': False,
              'publication_basis': {'policy': 'official-text-v1', 'policy_sha256': digest(policy()),
                  'provider': provider, 'source_sha256': hashlib.sha256(raw).hexdigest(), 'source_fields_sha256': digest(source)},
              'sources': [source], 'image': None,
              'image_note': 'Ei kuvaa: uutiskohtaista kuvaa ja sen käyttöoikeuksia ei ole varmennettu.',
              'supporting_documents': [{'id': 'RIGHTS', 'purpose': 'text reuse permission; not news or image evidence',
                  'url': spec['rights_url'], 'retrieved_at': now.isoformat(), 'text': permission,
                  'sha256': hashlib.sha256(rights).hexdigest()}]}
    validate_packet(packet, now, 48)
    directory = Path(state_dir)/'intake'/digest(packet)
    directory.mkdir(parents=True, exist_ok=True)
    receipt = {'fixture': False, 'retrieved_at': now.isoformat(), 'provider': provider,
               'source_url': url, 'source_sha256': hashlib.sha256(raw).hexdigest(),
               'rights_url': spec['rights_url'], 'rights_sha256': hashlib.sha256(rights).hexdigest(),
               'rights_text_sha256': spec['rights_text_sha256'], 'packet_sha256': digest(packet),
               'image_status': 'explicit-text-only', 'publication_basis': packet['publication_basis']}
    for name, value in [('source.html', raw), ('rights.html', rights), ('packet.json', json.dumps(packet, ensure_ascii=False, indent=2).encode()), ('receipt.json', json.dumps(receipt, indent=2).encode())]:
        (directory/name).write_bytes(value)
    return packet, receipt


def reuse(spec):
    result = {'license': spec.get('license', 'CC BY 4.0'), 'url': spec['rights_url'],
              'changes': 'Itsenäinen suomenkielinen uutisteksti; lähteen tietoja on tiivistetty.'}
    for field in ('license_url', 'notice'):
        if field in spec: result[field] = spec[field]
    return result

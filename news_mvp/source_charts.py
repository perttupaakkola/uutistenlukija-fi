"""Exact, explicitly licensed Statistics Finland source-chart provenance.

Only actual statistical SVG/PNG exports are admitted. The source's text licence
does not authorize its photographs or other organizations' illustrations.
"""
import hashlib
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from .editorial import digest

RIGHTS_URL = 'https://stat.fi/fi/tietoa-meista/tutustu-tilastokeskukseen/lainsaadanto/kayttoehdot'
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'
GRANT = ('Tilastokeskuksen avoimen datan aineistoja ja verkkopalvelun julkisia sisältöjä koskee '
    'Creative Commons Nimeä 4.0 Kansainvälinen -käyttölupa. Luvan mukaisesti saat kopioida, '
    'muokata ja jakaa näitä aineistojamme edelleen joko alkuperäisessä tai muokatussa muodossa. '
    'Saat myös yhdistää aineistoja muihin aineistoihin ja käyttää aineistoja myös kaupallisiin '
    'tarkoituksiin. Tämä lupa koskee esimerkiksi tekstejä, taulukoita ja tilastokuvioita.')
SOURCE = re.compile(r'https://stat\.fi/fi/julkaisu/[a-z0-9]{20,32}')
SHA = re.compile(r'[0-9a-f]{64}')
CAPTION = 'Tilastokeskuksen tilastokuvio.'
CREDIT = 'Lähde: Tilastokeskus'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def _text(raw):
    parser = _VisibleText(); parser.feed(raw.decode('utf-8')); parser.close()
    return ' '.join(' '.join(parser.parts).split())


def capture_evidence(source_url, source_html, rights_html, svg, png, title):
    """Validate captured source exports before any candidate may be prepared."""
    if not SOURCE.fullmatch(source_url) or not isinstance(title, str) or not 10 <= len(title) <= 300:
        raise ValueError('Invalid Statistics Finland chart identity')
    if len(svg) > 1000000 or len(png) > 25000000:
        raise ValueError('Oversized source chart')
    if GRANT not in _text(rights_html):
        raise ValueError('Missing explicit chart reuse grant')
    if title not in _text(source_html):
        raise ValueError('Chart title is absent from the captured source')
    if b'<!DOCTYPE' in svg.upper() or b'<!ENTITY' in svg.upper():
        raise ValueError('Unsafe source chart XML')
    root = ET.fromstring(svg)
    if root.tag != '{http://www.w3.org/2000/svg}svg' or root.get('class') != 'highcharts-root':
        raise ValueError('Source export is not a statistical chart')
    if any(e.tag.split('}')[-1] in ('image', 'script', 'foreignObject') for e in root.iter()):
        raise ValueError('Chart grant cannot authorize embedded photos or active content')
    text = ' '.join(' '.join(root.itertext()).split())
    if title not in text or 'Lähde: Tilastokeskus,' not in text:
        raise ValueError('Chart source/title identity mismatch')
    from .imagery import verify
    verify(png)
    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Source export is not PNG')
    return {'kind':'statistical_chart', 'source_url':source_url, 'title':title,
        'source_html_sha256':_sha(source_html), 'source_svg_sha256':_sha(svg),
        'source_png_sha256':_sha(png), 'rights_url':RIGHTS_URL,
        'rights_html_sha256':_sha(rights_html), 'rights_grant':GRANT,
        'rights_grant_sha256':_sha(GRANT.encode())}


def photo_id(evidence):
    return 'statfi-' + digest({'source_url':evidence['source_url'],
                            'svg_sha256':evidence['source_svg_sha256']})[:24]


def validate_provenance(provenance):
    e = provenance.get('chart_evidence')
    expected = {'kind','source_url','title','source_html_sha256','source_svg_sha256',
        'source_png_sha256','rights_url','rights_html_sha256','rights_grant','rights_grant_sha256'}
    if not isinstance(e, dict) or set(e) != expected:
        raise ValueError('Incomplete source-chart evidence')
    if (e['kind'] != 'statistical_chart' or not SOURCE.fullmatch(str(e['source_url'])) or
            not isinstance(e['title'], str) or not 10 <= len(e['title']) <= 300 or
            e['rights_url'] != RIGHTS_URL or e['rights_grant'] != GRANT or
            e['rights_grant_sha256'] != _sha(GRANT.encode()) or
            any(not SHA.fullmatch(str(v)) for k,v in e.items() if k.endswith('_sha256'))):
        raise ValueError('Invalid source-chart rights/source evidence')
    if (provenance['photo_id'] != photo_id(e) or provenance['photo_url'] != e['source_url'] or
            provenance['image_url'] != e['source_url'] or
            provenance['photographer'] != 'Tilastokeskus' or
            provenance['photographer_url'] != 'https://stat.fi/fi/tietoa-meista' or
            provenance['license'] != 'CC BY 4.0' or provenance['license_url'] != LICENSE_URL or
            provenance.get('attribution', {}).get('title') != e['title']):
        raise ValueError('Source-chart provenance identity mismatch')

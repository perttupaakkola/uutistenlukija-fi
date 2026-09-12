"""Read-only release admission against the existing public sitemap and static data.

The historical site is public DATA, not the former generator or agent state.
The replacement release must include every baseline URL and exact historical page.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from xml.etree import ElementTree

ORIGIN = 'https://uutistenlukija.fi'


def route_file(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != 'uutistenlukija.fi' or parts.query or parts.fragment:
        raise ValueError('Unexpected canonical URL')
    path = unquote(parts.path)
    if '..' in path.split('/') or '\\' in path:
        raise ValueError('Unsafe route')
    return path.lstrip('/') + ('index.html' if path.endswith('/') else '')


def baseline(sitemap, public_dir):
    xml = ElementTree.fromstring(Path(sitemap).read_bytes())
    if xml.tag.rsplit('}', 1)[-1] != 'urlset':
        raise ValueError('Supply the complete flattened public URL sitemap')
    urls = [n.text for n in xml.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    if not urls:
        raise ValueError('Empty sitemap')
    entries = len(urls)
    urls = sorted(set(urls))
    records=[]
    root=Path(public_dir).resolve()
    for url in urls:
        relative=route_file(url); file=root/relative
        if not file.is_file() or not file.resolve().is_relative_to(root):
            raise ValueError('Historical output missing: '+url)
        records.append({'url':url,'file':relative,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    return {'origin':ORIGIN,'sitemap_entries':entries,'duplicate_entries':entries-len(urls),'sitemap_sha256':hashlib.sha256(Path(sitemap).read_bytes()).hexdigest(),'routes':records}


def verify(manifest, release):
    root=Path(release).resolve()
    for row in manifest['routes']:
        file=root/route_file(row['url'])
        if not file.is_file() or not file.resolve().is_relative_to(root):
            raise ValueError('Missing historical route: '+row['url'])
        # The new homepage may replace the old one. Historical pages remain exact.
        if row['url'] != ORIGIN+'/' and hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Historical page changed: '+row['url'])
    return len(manifest['routes'])


if __name__ == '__main__':
    import sys
    if sys.argv[1]=='baseline':
        print(json.dumps(baseline(sys.argv[2],sys.argv[3]),ensure_ascii=False,indent=2))
    elif sys.argv[1]=='verify':
        print(verify(json.loads(Path(sys.argv[2]).read_text()),sys.argv[3]))
    else:
        raise SystemExit('baseline SITEMAP PUBLIC_DIR | verify MANIFEST RELEASE_DIR')

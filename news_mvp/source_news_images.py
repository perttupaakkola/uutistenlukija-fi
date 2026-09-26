"""Helsinki's explicit related-news image grant, separate from its text licence."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit
import urllib.request

from .editorial import digest

RIGHTS_URL = 'https://hri.fi/data/fi/dataset/helsingin-hel-fi-sivuston-avoin-rajapinta-uutisille'
LICENSE = 'Helsingin kaupungin uutiskuvan käyttöoikeus'
GRANT = ('Helsingin kaupungilla on uutisissa käytettyihin kuviin kaikki oikeudet. '
    'Kuvaa / kuvia saa käyttää ainoastaan siihen liittyvän uutisen yhteydessä. '
    'Kuvien käyttäminen tähän tarkoitukseen on käyttäjälle ilmaista. '
    'Kuvan käyttö tai siirto muihin tarkoituksiin on kielletty. '
    'Kuvia käytettäessä on ehdottomasti mainittava kuvien lähde ja kuvaaja.')
SOURCE = re.compile(r'https://www\.hel\.fi/fi/uutiset/[a-z0-9%-]+')
SHA = re.compile(r'[0-9a-f]{64}')
MAX_HTML = 2_000_000
FIELDS = {'kind','source_url','source_title','source_caption','image_url','photographer',
    'source_html_sha256','source_image_sha256','rights_url','rights_html_sha256',
    'rights_grant','rights_grant_sha256'}


def sha(raw): return hashlib.sha256(raw).hexdigest()


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.main=0; self.figure=None; self.figures=[]
        self.canonicals=[]; self.headings=[]; self.heading=False; self.caption=False
        self.skip=0; self.text=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag in ('script','style'): self.skip+=1
        if tag=='main': self.main+=1
        if tag=='link' and a.get('rel')=='canonical': self.canonicals.append(a.get('href'))
        if tag=='h1' and self.main: self.headings.append(''); self.heading=True
        if tag=='figure' and self.main and {'image','main-image'}<=set(a.get('class','').split()):
            if self.figure is not None: raise ValueError('Nested main image')
            self.figure={'images':[],'caption':''}
        if self.figure is not None:
            if tag=='img': self.figure['images'].append(a)
            if tag=='figcaption': self.caption=True
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
        if tag=='h1': self.heading=False
        if tag=='figcaption': self.caption=False
        if tag=='figure' and self.figure is not None:
            self.figures.append(self.figure); self.figure=None
        if tag=='main': self.main=max(0,self.main-1)
    def handle_data(self, data):
        if self.skip:return
        self.text.append(data)
        if self.heading:self.headings[-1]+=data
        if self.caption and self.figure is not None:self.figure['caption']+=data


def parsed(raw):
    if not raw or len(raw)>MAX_HTML:raise ValueError('Invalid source page size')
    parser=Page();parser.feed(raw.decode('utf-8'));parser.close();return parser


def image_url_allowed(url):
    p=urlsplit(url)
    return (p.scheme=='https' and not p.username and not p.password and not p.fragment
        and p.port in (None,443) and ((p.hostname=='stplattaprod.blob.core.windows.net'
            and p.path.startswith('/etusivu64e62prod/styles/')) or
            (p.hostname=='www.hel.fi' and p.path.startswith('/fi/_flysystem/azure/styles/')))
        and p.path.endswith(('.jpg','.jpeg','.png','.webp')))


def candidate(source_url, source_html, rights_html):
    if not SOURCE.fullmatch(source_url):raise ValueError('Not a Helsinki news source')
    rights=' '.join(' '.join(parsed(rights_html).text).split())
    if GRANT not in rights:raise ValueError('Explicit related-news IMAGE grant missing')
    page=parsed(source_html)
    if page.canonicals!=[source_url] or len(page.headings)!=1 or len(page.figures)!=1:
        raise ValueError('Ambiguous news or main-photo identity')
    title=' '.join(page.headings[0].split());fig=page.figures[0]
    if not 10<=len(title)<=300 or len(fig['images'])!=1:raise ValueError('Missing main image/title')
    img=fig['images'][0];url=img.get('src','');caption=' '.join(fig['caption'].split())
    author=caption.rpartition('Kuva:')[2].strip()
    if (not image_url_allowed(url) or 'Kuva:' not in caption or not 1<=len(author)<=160 or not caption or len(caption)>1000
            or any(term in caption.casefold() for term in ('all rights reserved','ei saa käyttää','käyttö kielletty'))):
        raise ValueError('Missing or conflicting main-photo credit/grant')
    e=dict(kind='related_helsinki_news_image',source_url=source_url,source_title=title,
        source_caption=caption,image_url=url,photographer=author,source_html_sha256=sha(source_html),
        rights_url=RIGHTS_URL,rights_html_sha256=sha(rights_html),rights_grant=GRANT,
        rights_grant_sha256=sha(GRANT.encode()))
    return dict(photo_id='helsinki-'+digest({'source':source_url,'image':url})[:24],
        photo_page=source_url,image_url=url,name=author,profile=source_url,
        title=title,license=LICENSE,license_url=RIGHTS_URL,news_evidence=e)


def validate_provenance(p):
    e=p.get('news_evidence')
    if not isinstance(e,dict) or set(e)!=FIELDS:raise ValueError('Incomplete news-image evidence')
    if (e['kind']!='related_helsinki_news_image' or not SOURCE.fullmatch(str(e['source_url']))
            or not image_url_allowed(e['image_url']) or e['rights_url']!=RIGHTS_URL
            or e['rights_grant']!=GRANT or e['rights_grant_sha256']!=sha(GRANT.encode())
            or any(not SHA.fullmatch(str(v)) for k,v in e.items() if k.endswith('_sha256'))
            or not isinstance(e['source_title'],str) or not 10<=len(e['source_title'])<=300
            or not isinstance(e['source_caption'],str) or not 1<=len(e['source_caption'])<=1000
            or 'Kuva:' not in e['source_caption']
            or not isinstance(e['photographer'],str) or not 1<=len(e['photographer'])<=160
            or e['source_caption'].rpartition('Kuva:')[2].strip()!=e['photographer']):
        raise ValueError('Invalid related-news grant evidence')
    if (p['provider']!='helsinki' or p['photo_id']!='helsinki-'+digest({'source':e['source_url'],'image':e['image_url']})[:24]
            or p['photo_url']!=e['source_url'] or p['photographer_url']!=e['source_url']
            or p['photographer']!=e['photographer'] or p['image_url']!=e['image_url']
            or p['license']!=LICENSE or p['license_url']!=RIGHTS_URL
            or p.get('attribution',{}).get('title')!=e['source_title']):
        raise ValueError('News image/provenance identity mismatch')


def validate_relation(provenance, packet, draft):
    validate_provenance(provenance)
    if packet.get('publication_basis',{}).get('provider')!='helsinki':
        raise ValueError('Helsinki image requires its related official news packet')
    sources=[s for s in packet.get('sources',[]) if s.get('url')==provenance['photo_url']]
    if len(sources)!=1 or not any(sources[0]['id'] in p.get('source_ids',[]) for p in draft['paragraphs']):
        raise ValueError('Related-news grant cannot authorize another article')


def pixel_context(provenance, image_sha):
    validate_provenance(provenance)
    if not SHA.fullmatch(str(image_sha)):raise ValueError('Invalid news image pixels')
    return {'provider':'helsinki','provenance':provenance,'image_sha256':image_sha}


def _read_html(url):
    from .imagery import _open
    with _open(urllib.request.Request(url,headers={'Accept':'text/html'}),urlsplit(url).hostname,
            timeout=25,credentialed=False) as response:
        if response.status!=200 or response.geturl()!=url:raise ValueError('Source/grant fetch mismatch')
        raw=response.read(MAX_HTML+1)
    parsed(raw);return raw


def fetch(packet, draft, state_dir, decision, accept):
    """At most one main image per cited Helsinki source; mandatory exact-pixel review."""
    from . import imagery
    if not packet or packet.get('publication_basis',{}).get('provider')!='helsinki' or accept is None:
        return None
    sources=[s for s in packet.get('sources',[]) if SOURCE.fullmatch(str(s.get('url','')))
        and any(s['id'] in p.get('source_ids',[]) for p in draft['paragraphs'])]
    if not sources:return None
    rights=_read_html(RIGHTS_URL)
    folder=Path(state_dir)/'source-news-rights';folder.mkdir(parents=True,exist_ok=True)
    for source in sources[:3]:
        try:
            html=_read_html(source['url']);c=candidate(source['url'],html,rights)
            raw=imagery._get_bytes(c['image_url'],urlsplit(c['image_url']).hostname)
            if raw is None:continue
            persisted=imagery._persist_verified_image(raw,state_dir)
            if persisted is None:continue
            image_sha,local_path,pixels=persisted;c['news_evidence']['source_image_sha256']=sha(raw)
            # Capture immutable source/grant/pixel bytes before asking any reviewer.
            for body,ext in ((html,'.html'),(rights,'.html'),(raw,'.image')):
                target=folder/(sha(body)+ext)
                if target.exists() and target.read_bytes()!=body:raise ValueError('Changed news evidence')
                target.write_bytes(body)
            described=imagery.describe(raw)
            if not described:continue
            relevance=imagery.relevance_check(described,decision,'vision')
            if not imagery._can_review_stock_composition(relevance,described,decision,accept,True):continue
            record=imagery._open_source_record('helsinki',c,source['title'],state_dir,pixels,
                image_sha,local_path,described,decision,relevance,
                datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            validate_relation(record['stock_provenance'],packet,draft)
            accepted=imagery._accepted_stock(record,accept)
            if accepted is not None:
                imagery.validate_pixel_review(accepted,draft)
                return accepted
        except (ValueError,KeyError,TypeError,OSError,RuntimeError):
            continue
    return None

"""Exact captured institutional article and rights parsing for official intake."""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .official import Page
from .official import MAX_ARTICLE_CHARS

def policy():
 from .official import policy as current_policy
 return current_policy()
def parse(raw,select):
 p=Page(select);p.feed(raw.decode('utf-8'));return p
class Meta(Page):
 def __init__(self):super().__init__(lambda t,a:False);self.values={};self.canonicals=[]
 def handle_starttag(self,t,attrs):
  a=dict(attrs)
  if t=='link' and a.get('rel')=='canonical':self.canonicals.append(a.get('href'))
  if t=='meta':self.values.setdefault(a.get('property',a.get('name')),[]).append(a.get('content',''))
  super().handle_starttag(t,attrs)
 def one(self,k):
  values=self.values.get(k,[])
  if len(values)!=1:raise ValueError('Missing/ambiguous metadata: '+k)
  return values[0]
def canonical(url,provider):
 # ECB's doubled separator is an explicit observed URL contract, never repaired.
 if not re.fullmatch(policy()['providers'][provider]['article_pattern'],url):raise ValueError('Unapproved article URL')
 return url
def rights_text(raw,provider):
 if provider.startswith('poliisi-'):
  text=parse(raw,lambda t,a:t=='body').text()
  start='Tekijänoikeudet tekstiin, kuviin ja muuhun sisältöön'
  end='Henkilötietojen käsittely'
  if text.count(start)!=1 or end not in text:raise ValueError('Missing exact Police reuse terms')
  return text[text.index(start):text.index(end,text.index(start))]
 if provider=='ec-press':
  text=parse(raw,lambda t,a:t=='main').text()
  start='Copyright notice';end='Related links'
  if text.count(start)!=1 or end not in text:raise ValueError('Missing exact Commission reuse terms')
  return text[text.index(start):text.index(end,text.index(start))]
 if provider=='espoo':
  text=parse(raw,lambda t,a:t=='main').text() or parse(raw,lambda t,a:t=='body').text()
  start='Oikeudet';end='Vastuukysymykset'
  if text.count(start)!=1 or end not in text:raise ValueError('Missing exact Espoo reuse terms')
  section=text[text.index(start):text.index(end,text.index(start))]
  if 'Lehdistötiedotteet, uutiset ja muu julkiseksi tarkoitettu materiaali on vapaata julkaistavaksi.' not in section:
   raise ValueError('Espoo news publication grant missing')
  return section
 if provider=='valtioneuvosto':
  # Exact reuse grant, captured verbatim: text reuse and linking permitted in good-faith
  # contexts with source attribution; commercial use requires a separate agreement. Perttu
  # approved adding this source on the non-commercial basis (2026-09-16). Pinning the text
  # means a change to these terms fails closed rather than silently continuing.
  text=parse(raw,lambda t,a:t=='body').text()
  start='Tekijänoikeudet';end='Tietosuoja ja henkilötietojen käsittely'
  if text.count(start)!=1 or end not in text:raise ValueError('Missing exact Valtioneuvosto reuse terms')
  return text[text.index(start):text.index(end,text.index(start))]
 if provider in ('kuopio','vantaa'):
  # Municipal open-data terms, captured verbatim from the publisher's own licence page.
  # Kuopio grants worldwide free irrevocable reuse for commercial and non-commercial
  # purposes over "tekstejä" (texts). Vantaa is covered by HRI (Espoo/Helsinki/Vantaa/
  # Kauniainen), which grants CC BY 4.0 for both non-commercial and commercial use.
  # Pinning the exact text means a licence change fails closed instead of silently
  # continuing on stale permission.
  text=parse(raw,lambda t,a:t=='main').text() or parse(raw,lambda t,a:t=='body').text()
  if provider=='kuopio':
   # Kuopio publishes its licence only as a PDF, so the intake pins the document by file
   # hash instead; this branch is a defensive fallback if an HTML version is ever added.
   start='Kuopion kaupungin avoimen datan käyttöehdot';end='Sovellettava laki'
  else:
   # HRI's terms page: pin the section that actually grants reuse and names its scope.
   start='Käyttöoikeus';end='Palvelun tuottajat'
  if text.count(start)<1 or end not in text:raise ValueError('Missing exact municipal reuse terms')
  return text[text.index(start):text.index(end,text.index(start))]
 if provider=='oulu':
  # ouka.fi/kayttoehdot resolves to the city's Avoin data terms: Nimeä (CC BY 4.0),
  # including commercial use, with attribution. Pinned verbatim; a terms change fails closed.
  text=parse(raw,lambda t,a:t=='main').text() or parse(raw,lambda t,a:t=='body').text()
  start='Oulun kaupungin julkaiseman avoimen datan käyttö edellyttää Nimeä-lisenssin noudattamista'
  end='Lisätietoja'
  if text.count(start)!=1 or end not in text:raise ValueError('Missing exact municipal reuse terms')
  return text[text.index(start):text.index(end,text.index(start))]
 text=parse(raw,lambda t,a:t=='main').text()
 if provider=='ecb':
  start='Copyright\nCopyright ©';end='\nUse of name and logos'
 else:
  start='Kuntaliitolla on tekijänoikeudet';end='\nKuntaliiton asiantuntijat'
 if text.count(start)!=1 or end not in text:raise ValueError('Missing exact rights section')
 return text[text.index(start):text.index(end,text.index(start))]
def _ec_press_fields(raw,url):
 try:data=json.loads(raw)
 except (TypeError,ValueError) as error:raise ValueError('Invalid Commission article JSON') from error
 match=re.fullmatch(r'https://ec\.europa\.eu/commission/presscorner/detail/fi/([a-z]+)_(\d{2})_(\d+)',url)
 expected=f'{match.group(1).upper()}/{match.group(2)}/{match.group(3)}' if match else None
 resource=data.get('docuLanguageResource') if isinstance(data,dict) else None
 if (not expected or data.get('refCd')!=expected or not isinstance(resource,dict)
     or resource.get('language')!='FI'):
  raise ValueError('Commission article identity mismatch')
 title=resource.get('title')
 body=parse(str(resource.get('htmlContent','')).encode(),lambda t,a:True).text()
 published=data.get('publishDate')
 try:
  if datetime.fromisoformat(published).date()!=datetime.fromisoformat(data.get('eventDate')).date():
   raise ValueError('Commission publication date disagreement')
 except (TypeError,ValueError) as error:raise ValueError('Missing Commission publication date') from error
 if (not title or len(body)<200 or len(body)>MAX_ARTICLE_CHARS
     or re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|copyright|©',body,re.I)):
  raise ValueError('Missing text or third-party/restricted rights')
 return {'id':'A','title':title,'published_at':published,'text':body}

def _espoo_fields(raw,url):
 page=Meta();page.feed(raw.decode())
 title=page.one('og:title').removesuffix(' | Espoon kaupunki').strip()
 heading=parse(raw,lambda t,a:t=='h1').text()
 match=re.search(rb'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',raw,re.S)
 if not match:raise ValueError('Missing Espoo article data')
 try:data=json.loads(match.group(1))
 except (TypeError,ValueError) as error:raise ValueError('Invalid Espoo article data') from error
 path=url.removeprefix('https://www.espoo.fi')
 found=[]
 def visit(value):
  if isinstance(value,dict):
   if isinstance(value.get('meta'),dict) and value['meta'].get('path')==path:
    found.append(value)
   for child in value.values():visit(child)
  elif isinstance(value,list):
   for child in value:visit(child)
 visit(data)
 if len(found)!=1:raise ValueError('Missing or ambiguous Espoo article identity')
 news=found[0]
 if news.get('title')!=title or heading!=title:raise ValueError('Article title mismatch/ambiguity')
 parts=[news.get('lead','')]
 for component in news.get('content',[]):
  if not isinstance(component,dict) or component.get('type')!='TextParagraph':continue
  for section in component.get('text',{}).get('structured',[]):
   if section.get('heading'):parts.append(section['heading'])
   parts.append(parse(str(section.get('htmlContent','')).encode(),lambda t,a:True).text())
 body='\n'.join(part.strip() for part in parts if isinstance(part,str) and part.strip())
 try:published=datetime.fromtimestamp(news['meta']['publishedTime'],timezone.utc).isoformat()
 except (KeyError,TypeError,ValueError,OverflowError) as error:raise ValueError('Missing Espoo publication date') from error
 day=datetime.fromisoformat(published)
 if f'/{day:%Y/%m}/' not in url:raise ValueError('URL date mismatch')
 if len(body)<200 or len(body)>MAX_ARTICLE_CHARS:raise ValueError('Missing substantive article text')
 return {'id':'A','title':title,'published_at':published,'text':body}

def source_fields(raw,provider,url):
 spec=policy()['providers'][provider];url=canonical(url,provider)
 if provider=='ec-press':return _ec_press_fields(raw,url)
 if provider=='espoo':return _espoo_fields(raw,url)
 meta=Meta();meta.feed(raw.decode())
 if provider=='valtioneuvosto' or provider.startswith('poliisi-'):
  # This portal emits no <link rel=canonical> at all, so og:url is the self-reference and is
  # checked in the provider branch below. Requiring a canonical tag here would reject every
  # valid Valtioneuvosto article.
  if meta.canonicals:raise ValueError('Unexpected canonical tag')
  if canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
 elif meta.canonicals != [url] or canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
 title=meta.one('og:title');title=title.removesuffix(' | Kuntaliitto.fi').removesuffix(' - Kuopio').removesuffix(' | Vantaa').strip();heading=parse(raw,lambda t,a:t=='h1').text()
 # Some portal templates prepend a rubric/kicker to the <h1>, so the heading reads
 # "<kicker> <title>" (observed: "Hallituksen talousarvioesitys vuodelle 2027 Orpon hallitus:
 # Talous kasvaa, ja hallitus vauhdittaa kasvua täsmätoimilla"). Accept a heading that ENDS
 # with the metadata title; the title must still match exactly, so this cannot smuggle a
 # different article in, and a heading that neither equals nor ends with it is still refused.
 if not title or (title!=heading and not heading.endswith(title)):
  raise ValueError('Article title mismatch/ambiguity')
 if provider.startswith('poliisi-'):
  if meta.one('og:type')!='article' or canonical(meta.one('og:url'),provider)!=url:
   raise ValueError('Not an article page')
  published=meta.one('article:published_time')
  day=datetime.fromisoformat(published).date()
  if day.strftime('%-d.%-m.%Y') not in parse(raw,lambda t,a:t=='body').text():
   raise ValueError('Publication date disagreement')
  body=parse(raw,lambda t,a:a.get('itemprop')=='articleBody').text()
  if len(body)<200:raise ValueError('Missing substantive article text')
  if len(body)>MAX_ARTICLE_CHARS:raise ValueError('Source is an aggregator/hub page, not a single article')
  if re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|copyright|©|press agency|Reuters|Associated Press',body,re.I):
   raise ValueError('Third-party/restricted rights on page')
  return {'id':'A','title':title,'published_at':published,'text':body}
 if provider=='valtioneuvosto':
  # Liferay/portal site: og:url is the authoritative self-reference because the pages emit
  # no <link rel=canonical> at all. og:type=article and article:published_time are present.
  if meta.one('og:type')!='article':raise ValueError('Not an article page')
  if canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
  published=meta.one('article:published_time')
  day=datetime.fromisoformat(published).date()
  # The dated slug is absent, but the visible Finnish publication date is present; use it as
  # an independent cross-check so a template change cannot silently move the timestamp.
  if day.strftime('%-d.%-m.%Y') not in parse(raw,lambda t,a:t=='body').text():raise ValueError('Publication date disagreement')
  # Content lives in Liferay's journal-content-article container; there is no <article>.
  body=parse(raw,lambda t,a:'journal-content-article' in a.get('class','').split()).text()
  if len(body)<200:raise ValueError('Missing substantive article text')
  # Liferay emits the site menu inside the content container on some renders, sometimes with no
  # separators at all ("liikenne- ja viestintäministeriömaa- ja metsätalousministeriö...", the
  # list of every ministry). Left in, the writer treats the menu as source text and the body can
  # exceed the excerpt limit - a real budget article failed with "Invalid source excerpt".
  from .related import strip_navigation
  stripped=strip_navigation(body)
  if len(stripped)>=200:body=stripped
  if len(body)>MAX_ARTICLE_CHARS:raise ValueError('Source is an aggregator/hub page, not a single article')
  wrapper=parse(raw,lambda t,a:t=='body').text()
  # Valtioneuvosto text reuse is permitted with attribution; commercial use needs a separate
  # agreement, so the terms page is pinned and the commercial status is recorded in policy.
  if re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|kaikki oikeudet pidätetään|©|press agency|Reuters|Associated Press|vieraskynä|guest author',wrapper,re.I):raise ValueError('Third-party/restricted rights on page')
  return {'id':'A','title':title,'published_at':published,'text':body}
 if provider in ('kuopio','vantaa'):
  # Vantaa's news pages report og:type=website and carry no article:published_time, so the
  # RSS pubDate is the publication authority (captured in the recipe, not guessed here).
  # Kuopio is WordPress and does expose article:published_time.
  if provider=='kuopio':
   day=datetime.fromisoformat(meta.one('article:published_time')).date()
   # Kuopio's URL carries the date, so it is a real cross-check.
   if not re.search(r'/'+day.strftime('%Y/%m/%d')+r'/',url):raise ValueError('URL date mismatch')
  else:
   # Vantaa reports og:type=website and has no article:published_time, but the page carries
   # a machine-readable <time datetime="YYYY-MM-DD HH:MM">. Use that, and cross-check the
   # visible Finnish date so a theme change cannot silently shift publication time. Vantaa
   # URLs are dateless (/ajankohtaista/tiedote/<slug>), so no URL date cross-check applies.
   stamps=sorted({m for m in parse(raw,lambda t,a:t=='time').times if 'T' in m or '-' in m})
   if len(stamps)!=1:raise ValueError('Missing or ambiguous publication timestamp')
   day=datetime.fromisoformat(stamps[0].replace(' ','T')).date()
   if day.strftime('%-d.%-m.%Y') not in parse(raw,lambda t,a:t=='time').text():raise ValueError('Publication date disagreement')
  body=parse(raw,lambda t,a:t=='article').text()
  if len(body)<200:
   # Vantaa (Drupal) uses no <article> element; body text lives in the field--body container.
   # Kuopio (WordPress) also exposes entry-content. Take the first that yields real text.
   for select in (lambda t,a:'field--body' in a.get('class','').split(),
                  lambda t,a:'entry-content' in a.get('class','').split(),
                  lambda t,a:'fragmented__main' in a.get('class','').split()):
    candidate=parse(raw,select).text()
    if len(candidate)>len(body):body=candidate
  wrapper=parse(raw,lambda t,a:t=='main').text() or body
  if len(body)<200 or re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|kaikki oikeudet pidätetään|copyright|©|press agency|Reuters|Associated Press|vieraskynä|guest author|tekijänoikeu',wrapper,re.I):raise ValueError('Missing text or third-party/restricted rights')
  return {'id':'A','title':title,'published_at':datetime.combine(day,datetime.min.time(),ZoneInfo(spec['timezone'])).isoformat(),'text':body}
 if provider=='oulu':
  # Drupal portal: no article:published_time; the page's own 'published' element carries
  # the date and the <article> body repeats the h1 as its first line. Strip it.
  stamps=parse(raw,lambda t,a:'published' in a.get('class','').split()).text().splitlines()
  if not stamps:raise ValueError('Missing publication date')
  day=datetime.strptime(stamps[0].strip(),'%d.%m.%Y').date()
  body=parse(raw,lambda t,a:t=='article').text()
  first,_,rest=body.partition('\n')
  if first.strip()==title:body=rest.strip()
  if len(body)<200:raise ValueError('Missing substantive article text')
  if len(body)>MAX_ARTICLE_CHARS:raise ValueError('Source is an aggregator/hub page, not a single article')
  wrapper=parse(raw,lambda t,a:t=='main').text()
  if re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|kaikki oikeudet pidätetään|copyright|©|press agency|Reuters|Associated Press|vieraskynä|guest author|tekijänoikeu',wrapper,re.I):raise ValueError('Third-party/restricted rights on page')
  stamp=datetime.combine(day,datetime.min.time(),ZoneInfo(spec['timezone'])).isoformat()
  return {'id':'A','title':title,'published_at':stamp,'text':body}
 if provider=='ecb':
  if meta.one('author')!='European Central Bank':raise ValueError('Named author exception')
  date=meta.one('article:published_time');day=datetime.strptime(date,'%Y-%m-%d').date()
  visible=parse(raw,lambda t,a:'ecb-publicationDate' in a.get('class','').split()).text()
  # ECB emits trailing whitespace inside citation_title (observed live: "...wage growth ").
  # Compare normalised titles so a formatting artefact is not read as a content disagreement,
  # while a genuinely different headline still fails.
  if visible.strip()!=meta.one('citation_online_date').strip() or datetime.strptime(visible.strip(),'%d %B %Y').date()!=day or meta.one('citation_title').strip()!=title:raise ValueError('Publication date/title disagreement')
  if not re.search(r'ecb\.(?:mp|pr)'+day.strftime('%y%m%d')+r'~',url):raise ValueError('URL date mismatch')
  main=parse(raw,lambda t,a:t=='main').text()
  if not main.startswith('PRESS RELEASE\n') or 'Reproduction is permitted provided that the source is acknowledged.' not in main:raise ValueError('Missing institutional press reuse notice')
  body=parse(raw,lambda t,a:t=='div' and a.get('class')=='section').text()
  # Section also occurs in navigation: select the uniquely dated news section via text bounds.
  if body.count(visible)!=1:raise ValueError('Ambiguous press body')
  body=body[body.index(visible)+len(visible):].split('\nRelated topics')[0].strip()
 else:
  date=parse(raw,lambda t,a:'field--name-node-post-date' in a.get('class','').split()).text();day=datetime.strptime(date,'%d.%m.%Y').date()
  if '/'+str(day.year)+'/' not in url:raise ValueError('URL year mismatch')
  body=parse(raw,lambda t,a:all(c in a.get('class','').split() for c in ('field--name-body','container-narrow'))).text()
  if meta.one('og:type')!='article' or meta.one('addsearch-category')!='Ajankohtaista':raise ValueError('Not institutional current-news category')
 wrapper=parse(raw,lambda t,a:t=='main').text()
 if len(body)<200 or re.search(r'CC[- ]BY[- ]ND|CC[- ]BY[- ]NC|all rights reserved|kaikki oikeudet pidätetään|copyright|©|press agency|Reuters|Associated Press|vieraskynä|guest author|tekijänoikeu',wrapper,re.I):raise ValueError('Missing text or third-party/restricted rights')
 # Date-only publication conservatively means start of the publisher's local day.
 stamp=datetime.combine(day,datetime.min.time(),ZoneInfo(spec['timezone'])).isoformat()
 return {'id':'A','title':title,'published_at':stamp,'text':body}

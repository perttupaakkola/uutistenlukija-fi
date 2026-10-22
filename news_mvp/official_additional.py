"""Exact captured institutional article and rights parsing for official intake."""
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
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
STTINFO_GRANT = ('STT Infossa julkaistu materiaali on vapaasti julkaistavissa, '
                 'ellei toisin mainita.')


def rights_text(raw,provider):
 if provider=='sttinfo':
  text=(raw.decode('utf-8') if raw==STTINFO_GRANT.encode('utf-8')
        else parse(raw,lambda t,a:t=='body').text())
  if text.count(STTINFO_GRANT)!=1:raise ValueError('Missing exact STT Info reuse grant')
  return STTINFO_GRANT
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

def _sttinfo_title_key(value):
 return ' '.join(re.findall(r'[a-z0-9åäö]+',value.casefold()))


def _sttinfo_non_news(title):
 value=' '.join(title.casefold().split())
 if 'nostot medialle' in value:return 'non-news: Nostot medialle'
 if re.search(r'\b(?:media|lehdistö)kutsu\b|\bkutsu\s*:',value):return 'non-news: media invitation'
 if re.search(r'\b(?:rekrytointi|rekry|työpaikat?|avoimet työpaikat|haemme)\b',value):
  return 'non-news: recruitment or job ad'
 return None


def sttinfo_publisher_allowed(name,spec):
 """Return the deterministic public-body decision before any permissive rule."""
 folded=' '.join(name.casefold().split())
 party=(r'puolue|\bsdp\b|kokoomu|perussuomalai|\bkeskusta\b|vihreät|'
        r'vasemmistoliitto|\brkp\b|\bsfp\b|\bkd\b|liike nyt')
 if re.search(party,folded):return False,'political party or politician feed'
 if re.search(r'\b(?:oyj?|ab)\b',folded):return False,'company'
 if re.search(r'\b(?:ry|rf)\b|yhdistys|järjestö|liitto|säätiö',folded):
  return False,'association or foundation'
 explicit={value.casefold() for value in spec.get('allowed_publishers',[])}
 if folded in explicit:return True,'explicit public-body allowlist'
 # A trailing translated abbreviation does not change the Finnish institutional name.
 base=re.sub(r'\s*\([^)]{2,12}\)\s*$','',folded)
 if re.search(r'(?:virasto|laitos|keskus|valvonta)$',base):
  return True,'state authority or agency name'
 if base.endswith('ministeriö'):return True,'ministry'
 if 'hyvinvointialue' in base:return True,'wellbeing services county'
 if re.search(r'\b(?:kaupunki|kunta)\b',base):return True,'city or municipality'
 if 'yliopisto' in base or 'ammattikorkeakoulu' in base:return True,'university'
 if re.search(r'(?:oikeus|tuomioistuin)$',base):return True,'court'
 if base=='eduskunta':return True,'Eduskunta'
 return False,'unknown publisher'


def _sttinfo_restriction(text,now,published):
 folded=' '.join(text.casefold().split())
 for pattern,label in ((r'ei saa julkaista','publication prohibited'),
                       (r'\bembargo\b','embargo'),
                       (r'vain tiedotusvälineiden käyttöön','media-only use'),
                       (r'kaikki oikeudet pidätetään','all rights reserved')):
  if re.search(pattern,folded):return label
 matches=re.finditer(r'julkaisuvapaa(?:na)?(?:\s+(\d{1,2}\.\d{1,2}\.\d{4}))?'
                     r'\s+klo\s+(\d{1,2})[.:](\d{2})',folded)
 local_now=now.astimezone(ZoneInfo('Europe/Helsinki'))
 for match in matches:
  day=(datetime.strptime(match.group(1),'%d.%m.%Y').date() if match.group(1)
       else published.astimezone(ZoneInfo('Europe/Helsinki')).date())
  release=datetime.combine(day,datetime.min.time(),ZoneInfo('Europe/Helsinki')).replace(
      hour=int(match.group(2)),minute=int(match.group(3)))
  if release>local_now:return 'future publication time'
 return None


def _sttinfo_parts(raw,url,now):
 spec=policy()['providers']['sttinfo']
 if not re.fullmatch(spec['article_pattern'],url):raise ValueError('Unapproved article URL')
 page=Meta();page.feed(raw.decode('utf-8'))
 if page.one('og:type')!='article':raise ValueError('Not an STT Info release')
 canonical_url=page.one('og:url').replace('&amp;','&')
 if urlsplit(canonical_url)._replace(query='')!=urlsplit(url)._replace(query=''):
  raise ValueError('Canonical article mismatch')
 lines=parse(raw,lambda t,a:t=='body').text().splitlines()
 if len(lines)<5 or lines.count('Tietoja julkaisijasta')!=1:
  raise ValueError('Missing STT Info release or publisher block')
 title=lines[0].strip()
 header=lines[1].split(' | ')
 if len(header)!=3 or not header[1].strip():
  raise ValueError('Missing exact STT Info publisher header')
 if header[2]!='Tiedote':raise ValueError('non-news STT Info item type: '+header[2])
 publisher=header[1].strip()
 meta_title=page.one('og:title')
 if title!=parse(raw,lambda t,a:t=='h1').text() or meta_title!=title+' | '+publisher:
  raise ValueError('STT Info title or publisher mismatch')
 stamp,separator,zone=header[0].rpartition(' ')
 try:
  if not separator or zone not in ('EET','EEST'):raise ValueError
  local=datetime.strptime(stamp,'%d.%m.%Y %H:%M:%S')
 except ValueError as error:raise ValueError('Missing STT Info publication time') from error
 published=local.replace(tzinfo=ZoneInfo('Europe/Helsinki'))
 expected_zone='EEST' if published.dst().total_seconds() else 'EET'
 if zone!=expected_zone:raise ValueError('STT Info timezone mismatch')
 stops=[i for i,line in enumerate(lines[3:],3)
        if line in ('Avainsanat','Liitteet','Linkit','Tietoja julkaisijasta')]
 if not stops:raise ValueError('Missing STT Info article boundary')
 body='\n'.join(lines[3:min(stops)]).strip()
 if len(body)<200 or len(body)>MAX_ARTICLE_CHARS:
  raise ValueError('Missing substantive STT Info release text')
 rejection=_sttinfo_non_news(title)
 if rejection:raise ValueError(rejection)
 allowed,reason=sttinfo_publisher_allowed(publisher,spec)
 if not allowed:raise ValueError(reason+': '+publisher)
 restriction=_sttinfo_restriction('\n'.join(lines),now,published)
 if restriction:raise ValueError('Restricted STT Info release: '+restriction)
 return {'id':'A','title':title,'published_at':published.isoformat(),'text':body,
         'publisher':publisher+' / STT Info'},page,publisher,reason


def _sttinfo_duplicate(title,page,excluded):
 excluded=set(excluded)
 if any(link.get('href') in excluded or 'url:'+link.get('href','') in excluded
        for link in page.links):return 'duplicate URL/story key'
 key=_sttinfo_title_key(title)
 existing=[value[6:] for value in excluded if isinstance(value,str) and value.startswith('title:')]
 if any(key==old or SequenceMatcher(None,key,old).ratio()>=.90 for old in existing):
  return 'duplicate title similarity'
 return None


def sttinfo_candidates(raw,spec,now,excluded,response):
 """Inspect one rotating release: one feed fetch in caller plus one page fetch here."""
 try:items=ET.fromstring(raw).findall('./channel/item')
 except ET.ParseError as error:raise ValueError('Invalid STT Info RSS') from error
 candidates=[]
 for item in items[:50]:
  url=item.findtext('link','');title=item.findtext('title','').strip()
  try:
   date=parsedate_to_datetime(item.findtext('pubDate',''))
   if date.tzinfo is None:raise ValueError
   age=(now-date).total_seconds()
  except (TypeError,ValueError):continue
  if (url in excluded or 'url:'+url in excluded or not 0<=age<=48*3600 or
      not re.fullmatch(spec['article_pattern'],url) or _sttinfo_non_news(title)):
   continue
  candidates.append((url,title))
 if not candidates:return []
 # Fifteen-minute rotation means an ineligible head item cannot starve the rest of the feed.
 url,feed_title=candidates[int(now.timestamp()//900)%len(candidates)]
 article=response(url,spec['hosts'])
 fields,page,publisher,reason=_sttinfo_parts(article,url,now)
 if fields['title']!=feed_title:raise ValueError('STT Info feed/article title mismatch')
 duplicate=_sttinfo_duplicate(feed_title,page,excluded)
 if duplicate:raise ValueError(duplicate)
 return [{'family':'finnish-official','provider':'sttinfo','url':url,
          '_source_raw':article,'publisher':publisher,'publisher_reason':reason}]


def source_fields(raw,provider,url,now=None):
 if provider=='sttinfo':
  fields,_,_,_=_sttinfo_parts(raw,url,now or datetime.now(timezone.utc))
  return fields
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

"""Exact captured institutional article and rights parsing for official intake."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from .official import Page

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
 text=parse(raw,lambda t,a:t=='main').text()
 if provider=='ecb':
  start='Copyright\nCopyright ©';end='\nUse of name and logos'
 else:
  start='Kuntaliitolla on tekijänoikeudet';end='\nKuntaliiton asiantuntijat'
 if text.count(start)!=1 or end not in text:raise ValueError('Missing exact rights section')
 return text[text.index(start):text.index(end,text.index(start))]
def source_fields(raw,provider,url):
 spec=policy()['providers'][provider];url=canonical(url,provider);meta=Meta();meta.feed(raw.decode())
 if provider=='valtioneuvosto':
  # This portal emits no <link rel=canonical> at all, so og:url is the self-reference and is
  # checked in the provider branch below. Requiring a canonical tag here would reject every
  # valid Valtioneuvosto article.
  if meta.canonicals:raise ValueError('Unexpected canonical tag')
  if canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
 elif meta.canonicals != [url] or canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
 title=meta.one('og:title');title=title.removesuffix(' | Kuntaliitto.fi').removesuffix(' - Kuopio').removesuffix(' | Vantaa').strip();heading=parse(raw,lambda t,a:t=='h1').text()
 if not title or title!=heading:raise ValueError('Article title mismatch/ambiguity')
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

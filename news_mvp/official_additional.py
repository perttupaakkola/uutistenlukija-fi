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
 text=parse(raw,lambda t,a:t=='main').text()
 if provider=='ecb':
  start='Copyright\nCopyright ©';end='\nUse of name and logos'
 else:
  start='Kuntaliitolla on tekijänoikeudet';end='\nKuntaliiton asiantuntijat'
 if text.count(start)!=1 or end not in text:raise ValueError('Missing exact rights section')
 return text[text.index(start):text.index(end,text.index(start))]
def source_fields(raw,provider,url):
 spec=policy()['providers'][provider];url=canonical(url,provider);meta=Meta();meta.feed(raw.decode())
 if meta.canonicals != [url] or canonical(meta.one('og:url'),provider)!=url:raise ValueError('Canonical article mismatch')
 title=meta.one('og:title').removesuffix(' | Kuntaliitto.fi').strip();heading=parse(raw,lambda t,a:t=='h1').text()
 if not title or title!=heading:raise ValueError('Article title mismatch/ambiguity')
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

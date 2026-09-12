"""One bounded NASA MODIS image-of-the-day source family; no backlog or feed framework."""
import hashlib,json,re
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from .editorial import digest,validate_packet,web_url
from .intake import ArticleHTML,fetch

ORIGIN='https://modis.gsfc.nasa.gov'
INDEX=ORIGIN+'/gallery/showall.php'
RIGHTS='https://www.nasa.gov/nasa-brand-center/images-and-media/'
HOSTS=['modis.gsfc.nasa.gov','www.nasa.gov']
CREDIT='MODIS Land Rapid Response Team, NASA GSFC'
PATTERN=r'https://modis\.gsfc\.nasa\.gov/gallery/individual\.php\?db_date=(\d{4}-\d{2}-\d{2})'

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'):self.links.append(a['href'])
        if tag=='img' and a.get('src'):self.images.append(a)

def discover(config,now=None):
    settings=config.get('discovery')
    if not settings:return []
    if settings.get('family')!='nasa-modis':raise ValueError('Unknown discovery family')
    limit=settings.get('max_candidates',5)
    if type(limit) is not int or not 1<=limit<=5:raise ValueError('Discovery limit must be 1–5')
    now=now or datetime.now(timezone.utc)
    raw,mime,_=fetch(INDEX,HOSTS);assert mime=='text/html'
    parser=Links();parser.feed(raw.decode('utf-8'))
    found={}
    for link in parser.links:
        url=urljoin(INDEX,link).replace('http://modis.gsfc.nasa.gov/','https://modis.gsfc.nasa.gov/')
        match=re.fullmatch(PATTERN,url)
        if not match:continue
        published=datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc)
        age=(now-published).total_seconds()
        if 0<=age<=config['max_source_age_hours']*3600:found[url]={'family':'nasa-modis','url':url}
    return [found[url] for url in sorted(found,reverse=True)[:limit]]

def collect_modis(recipe,state_dir,now=None):
    now=now or datetime.now(timezone.utc);url=web_url(recipe['url']);match=re.fullmatch(PATTERN,url)
    if not match:raise ValueError('Not an allowlisted MODIS article')
    raw,mime,final=fetch(url,HOSTS)
    if mime!='text/html' or final!=url:raise ValueError('Unexpected article response')
    source=raw.decode('utf-8');body=ArticleHTML('option');body.feed(source);text=body.article_text()
    date=match[1];display=datetime.fromisoformat(date).strftime('%B %d, %Y').replace(' 0',' ')
    title_match=re.search(re.escape(display)+r'\s*-\s*([^\n]+)',text)
    acquired=re.search(r'Date Acquired:\s*(\d{1,2}/\d{1,2}/\d{4})',text)
    credit=re.search(r'Image Credit:\s*([^\n]+)',text)
    if not title_match or not acquired or not credit or credit[1].strip()!=CREDIT:
        raise ValueError('Missing exact article date, image capture date or NASA GSFC credit')
    text=text[text.index(display+' - '):]
    title=title_match[1].strip();photo_date=datetime.strptime(acquired[1],'%m/%d/%Y').date().isoformat()
    if photo_date>date:raise ValueError('Capture date later than publication')
    links=Links();links.feed(source)
    expected=ORIGIN+'/gallery/images/image'+datetime.fromisoformat(date).strftime('%m%d%Y')+'_main.jpg'
    images=[i for i in links.images if i['src'].replace('http://','https://')==expected and i.get('alt','').strip()==title]
    if len(images)!=1:raise ValueError('Image URL/date/title identity mismatch')
    image_raw,image_mime,image_final=fetch(expected,HOSTS,8000000)
    if image_mime!='image/jpeg' or not image_raw.startswith(b'\xff\xd8\xff') or image_final!=expected:raise ValueError('Expected exact NASA source JPEG')
    rights_raw,_,rights_final=fetch(RIGHTS,HOSTS);rights=ArticleHTML('entry-content');rights.feed(rights_raw.decode('utf-8'))
    if len(rights.article_text())<200:raise ValueError('Missing permission evidence')
    image_sha=hashlib.sha256(image_raw).hexdigest()
    image={'url':expected,'source_url':url,'license_url':RIGHTS,'license':'NASA media guidelines: informational/editorial use with NASA credit; no endorsement','credit':CREDIT,'photo_date':photo_date,'caption':f'NASA MODIS: {title}. Kuva otettu {photo_date}; NASA julkaisi kuvaesittelyn {date}.','alt':f'NASA MODIS -satelliittikuva: {title}.','sha256':image_sha,'local_path':'media/'+image_sha+'.jpg','source_caption':images[0]['alt']}
    packet={'story_key':'url:'+url,'fixture':False,'sources':[{'id':'A','url':url,'publisher':'NASA GSFC / MODIS','title':title,'published_at':date+'T00:00:00+00:00','text':text+'\nPublication day from source heading; timestamp uses conservative UTC start of that day.'}],'image':image,'supporting_documents':[{'id':'RIGHTS','purpose':'image permission, not a news event','url':rights_final,'retrieved_at':now.isoformat(),'text':rights.article_text()[:20000],'sha256':hashlib.sha256(rights_raw).hexdigest()}]}
    validate_packet(packet,now)
    directory=Path(state_dir)/'intake'/digest(packet);directory.mkdir(parents=True,exist_ok=True)
    (directory/'source.html').write_bytes(raw);(directory/'rights.html').write_bytes(rights_raw)
    media=Path(state_dir)/image['local_path'];media.parent.mkdir(parents=True,exist_ok=True);media.write_bytes(image_raw)
    receipt={'retrieved_at':now.isoformat(),'source_url':url,'source_sha256':hashlib.sha256(raw).hexdigest(),'image_url':expected,'image_sha256':image_sha,'image_bytes':len(image_raw),'rights_sha256':hashlib.sha256(rights_raw).hexdigest(),'discovered_from':INDEX,'fixture':False}
    (directory/'packet.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n');(directory/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return packet,receipt

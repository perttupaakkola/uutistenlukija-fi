"""One existing GitHub/Pages executor; SQLite remembers the exact release identity."""
import base64
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

from cutover.check_release import check
from .authorization import authorize
from .editorial import ROOT, digest
from .site import atomic_write, article_path, esc, page, render_site

REPO='perttupaakkola/uutistenlukija-fi'
WORKFLOW='246481423'


def cmd(*args):
    return subprocess.check_output(args,cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()


def api(path, data=None, method=None):
    if data is None and method is None:
        return json.loads(cmd('gh','api',f'repos/{REPO}/{path}'))
    # Existing Git credential has repository/workflow write scope. The existing
    # gh credential owns Actions dispatch. Neither is copied or reconfigured.
    result=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
                          cwd=ROOT,capture_output=True,text=True,check=True,timeout=15)
    credential=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    request=urllib.request.Request(f'https://api.github.com/repos/{REPO}/{path}',data=json.dumps(data).encode(),
        headers={'Authorization':'Bearer '+credential['password'],'User-Agent':'Uutistenlukija-MVP','Content-Type':'application/json'},method=method or 'POST')
    with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)


def guard(config_path):
    if json.loads(Path(config_path).read_text())['enabled'] is not True:
        raise ValueError('Controller stopped')
    authorize(json.loads(Path(config_path).read_text()),cmd('git','rev-parse','HEAD'))
    if cmd('git','status','--porcelain','--untracked-files=no'):
        raise ValueError('Commit source changes before publishing')
    drain=json.loads((Path(json.loads(Path(config_path).read_text())['state_dir'])/'cutover/drain-verified.json').read_text())
    if drain['legacy_processes_active'] or drain['legacy_actions_active']:
        raise ValueError('Legacy writers have not drained')


def ensure_table(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS publications (
        job_id TEXT PRIMARY KEY, packet_sha TEXT NOT NULL, draft_sha TEXT NOT NULL,
        image_sha TEXT NOT NULL, source_commit TEXT NOT NULL, remote_commit TEXT,
        run_id INTEGER, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT)''');store.db.commit()


def public_bundle(store,job,state):
    ids={r[0] for r in store.db.execute("SELECT job_id FROM publications WHERE status='deployed'")}|{job['id']}
    site=Path(state)/'live-site'  # Never reads or overlays the abandoned public-history tree.
    render_site(store,site,state,public=True,include_ids=ids)
    privacy='''<article class="story"><h1>Tietosuoja ja evästeet</h1><p>Voit käyttää uutispalvelua sallimatta analytiikkaa. Luvallasi käytämme Google Analyticsia sivuston käytön mittaamiseen. Emme käytä mainonnan evästeitä.</p><p>Suostumus tallennetaan selaimeesi. Voit muuttaa valintaasi sivun Evästeasetukset-painikkeella. Analytiikan poistaminen käytöstä poistaa tämän sivuston Google Analytics -evästeet selaimesta.</p><p>Uutiset laaditaan tekoälyn avulla ja tarkastetaan erillisessä lähdearvioinnissa. Alkuperäiset lähteet, kuvan tekijä ja käyttöoikeus näkyvät artikkelissa.</p></article>'''
    atomic_write(site/'tietosuoja/index.html',page('Tietosuoja ja evästeet',privacy,'/tietosuoja/'))
    atomic_write(site/'404.html',page('Sivua ei löytynyt','<h1>Sivua ei löytynyt</h1><p><a href="/">Siirry uusimpiin uutisiin</a></p>','/404.html'))
    urls=['https://uutistenlukija.fi/','https://uutistenlukija.fi/tietosuoja/']+['https://uutistenlukija.fi/uutiset/'+i+'/' for i in sorted(ids)]
    atomic_write(site/'sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+esc(u)+'</loc></url>' for u in urls)+'</urlset>')
    atomic_write(site/'robots.txt','User-agent: *\nAllow: /\nSitemap: https://uutistenlukija.fi/sitemap.xml\n')
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    receipt={'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi','ga4_id':'G-35XERS8V6J',
        'source_commit':cmd('git','rev-parse','HEAD'),'job_id':job['id'],'packet_sha256':digest(packet),
        'draft_sha256':digest(draft),'image_sha256':draft['image']['sha256'],
        'new_article_files':[article_path(job)+'index.html'],
        'files':{str(p.relative_to(site)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(site.rglob('*')) if p.is_file()}}
    check(site,receipt)
    atomic_write(Path(state)/'release.json',json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return site,receipt


def make_commit(site,receipt):
    parent=api('git/ref/heads/main')['object']['sha'];base=api('git/commits/'+parent)['tree']['sha']
    def blob(data):return api('git/blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})['sha']
    public_tree=api('git/trees',{'tree':[{'path':name,'mode':'100644','type':'blob','sha':blob((site/name).read_bytes())} for name in receipt['files']]})['sha']
    paths=cmd('git','ls-files').splitlines()
    entries=[{'path':name,'mode':'100644','type':'blob','sha':blob((ROOT/name).read_bytes())} for name in paths]
    entries += [{'path':'public','mode':'040000','type':'tree','sha':public_tree},
        {'path':'release/release.json','mode':'100644','type':'blob','sha':blob(json.dumps(receipt,ensure_ascii=False,indent=2).encode())},
        {'path':'.github/workflows/deploy.yml','mode':'100644','type':'blob','sha':blob((ROOT/'ops/deploy.yml').read_bytes())},
        {'path':'.github/workflows/source-validation.yml','mode':'100644','type':'blob','sha':blob((ROOT/'ops/source-validation.yml').read_bytes())}]
    tree=api('git/trees',{'base_tree':base,'tree':entries})['sha']
    return api('git/commits',{'message':'Fresh MVP reviewed article '+receipt['job_id'][:12], 'tree':tree,'parents':[parent],
                            'author':{'name':'Uutistenlukija MVP','email':'news-mvp@localhost'}})['sha']


def matching_runs(commit):
    return json.loads(cmd('gh','run','list','--repo',REPO,'--workflow',WORKFLOW,'--commit',commit,
                         '--event','workflow_dispatch','--limit','10','--json','databaseId,status,conclusion,headSha'))


def publish(store,job,state,config_path):
    ensure_table(store);guard(config_path)
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',
            (job['id'],digest(packet),digest(draft),draft['image']['sha256'],cmd('git','rev-parse','HEAD'),'preparing'))
    row=dict(store.db.execute('SELECT * FROM publications WHERE job_id=?',(job['id'],)).fetchone())
    if row['packet_sha']!=digest(packet) or row['draft_sha']!=digest(draft):raise ValueError('Publication packet changed')
    if row['status']=='deployed':return {'status':'idle','job_id':job['id'],'remote_commit':row['remote_commit']}
    if row['status']=='failed' or row['attempts']>=3:return {'status':'failed','job_id':job['id']}
    try:
        if not row['remote_commit']:
            with store.db:store.db.execute('UPDATE publications SET attempts=attempts+1 WHERE job_id=?',(job['id'],))
            site,receipt=public_bundle(store,job,state);guard(config_path)
            row['remote_commit']=make_commit(site,receipt)
            with store.db:store.db.execute('UPDATE publications SET remote_commit=?,status=? WHERE job_id=?',(row['remote_commit'],'prepared',job['id']))
        guard(config_path)
        current=api('git/ref/heads/main')['object']['sha']
        if current!=row['remote_commit']:
            api('git/refs/heads/main',{'sha':row['remote_commit'],'force':False},method='PATCH')
        runs=matching_runs(row['remote_commit'])
        if not runs:
            if row['status'] in ('dispatching','dispatched'):
                return {'status':'awaiting_dispatch_visibility','job_id':job['id'],'remote_commit':row['remote_commit']}
            guard(config_path)
            cmd('gh','workflow','enable',WORKFLOW,'--repo',REPO)
            with store.db:store.db.execute("UPDATE publications SET status='dispatching' WHERE job_id=?",(job['id'],))
            cmd('gh','workflow','run','deploy.yml','--repo',REPO,'--ref','main')
            with store.db:store.db.execute("UPDATE publications SET status='dispatched' WHERE job_id=?",(job['id'],))
            return {'status':'dispatched','job_id':job['id'],'remote_commit':row['remote_commit']}
        run=runs[0]
        with store.db:store.db.execute('UPDATE publications SET run_id=? WHERE job_id=?',(run['databaseId'],job['id']))
        if run['status']!='completed':return {'status':'deploying','job_id':job['id'],'run_id':run['databaseId']}
        if run['conclusion']!='success':raise ValueError('Public deployment failed; no automatic redispatch')
        receipt_dir=Path(state)/'deployments'/str(run['databaseId'])
        receipt_dir.mkdir(parents=True,exist_ok=True)
        if not (receipt_dir/'live-deployment.json').exists():
            cmd('gh','run','download',str(run['databaseId']),'--repo',REPO,'--name','live-deployment','--dir',str(receipt_dir))
        live=json.loads((receipt_dir/'live-deployment.json').read_text())
        assert live['remote_commit']==row['remote_commit'] and live['packet_sha256']==row['packet_sha'] and live['draft_sha256']==row['draft_sha'] and live['image_sha256']==row['image_sha']
        url='https://uutistenlukija.fi/'+article_path(job)
        def read(url):
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:return r.read()
        html=read(url);image=read('https://uutistenlukija.fi/mvp-assets/'+row['image_sha']+'.jpg')
        assert hashlib.sha256(image).hexdigest()==row['image_sha']
        assert esc(draft['title']).encode() in html and ('href="'+url+'"').encode() in html
        for paragraph in draft['paragraphs']:assert esc(paragraph['text']).encode() in html
        live.update(canonical_article=url,live_html_sha256=hashlib.sha256(html).hexdigest(),live_image_sha256=hashlib.sha256(image).hexdigest())
        atomic_write(receipt_dir/'live-readback.json',json.dumps(live,indent=2)+'\n')
        with store.db:store.db.execute("UPDATE publications SET status='deployed' WHERE job_id=?",(job['id'],))
        return {'status':'deployed','job_id':job['id'],'run_id':run['databaseId'],'remote_commit':row['remote_commit'],'deployment_id':live['deployment_id']}
    except Exception as error:
        with store.db:store.db.execute("UPDATE publications SET status='failed',error=? WHERE job_id=?",(type(error).__name__,job['id']))
        raise

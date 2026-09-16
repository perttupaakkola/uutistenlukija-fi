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
from .diagnostics import safe_error
from .editorial import ROOT, digest, timestamp, validate_review, validate_packet
from datetime import datetime, timezone
from .release_contract import media, verify_intake, check_article
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
        image_sha TEXT, source_commit TEXT NOT NULL, remote_commit TEXT,
        run_id INTEGER, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT)''');store.db.commit()
    columns = list(store.db.execute('PRAGMA table_info(publications)'))
    if next(c for c in columns if c[1]=='image_sha')[3]:
        _image_constraint(store,required=False)


def _image_constraint(store,required):
    # Operator schema transition/rollback must hold the existing controller lock.
    expected=['job_id','packet_sha','draft_sha','image_sha','source_commit','remote_commit','run_id','status','attempts','error']
    if [c[1] for c in store.db.execute('PRAGMA table_info(publications)')] != expected:
        raise ValueError('Unknown publication schema; refuse migration')
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE tbl_name='publications' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchone():
        raise ValueError('Unknown publication index/trigger; refuse migration')
    if required and store.db.execute('SELECT 1 FROM publications WHERE image_sha IS NULL').fetchone():
        raise ValueError('Text-only publication exists; keep compatible candidate stopped')
    constraint=' NOT NULL' if required else ''
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        store.db.execute('CREATE TABLE publications_transition (job_id TEXT PRIMARY KEY, packet_sha TEXT NOT NULL, draft_sha TEXT NOT NULL, image_sha TEXT'+constraint+', source_commit TEXT NOT NULL, remote_commit TEXT, run_id INTEGER, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT)')
        store.db.execute('INSERT INTO publications_transition SELECT * FROM publications')
        store.db.execute('DROP TABLE publications')
        store.db.execute('ALTER TABLE publications_transition RENAME TO publications')


def restore_image_required_schema(store):
    """Pre-activation rollback only; never discard text-only rows to fit old code."""
    _image_constraint(store,required=True)


def public_bundle(store,job,state):
    ids={r[0] for r in store.db.execute("SELECT job_id FROM publications WHERE status='deployed'")}|{job['id']}
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    binding=media(packet,draft)
    if binding['image_sha256'] is None:verify_intake(packet,state)
    site=Path(state)/'live-site'  # Never reads or overlays the abandoned public-history tree.
    render_site(store,site,state,public=True,include_ids=ids)
    privacy='''<article class="story"><h1>Tietosuoja ja evästeet</h1><p>Voit käyttää uutispalvelua sallimatta analytiikkaa. Luvallasi käytämme Google Analyticsia sivuston käytön mittaamiseen. Emme käytä mainonnan evästeitä.</p><p>Suostumus tallennetaan selaimeesi. Voit muuttaa valintaasi sivun Evästeasetukset-painikkeella. Analytiikan poistaminen käytöstä poistaa tämän sivuston Google Analytics -evästeet selaimesta.</p><p>Uutiset laaditaan tekoälyn avulla ja tarkastetaan erillisessä lähdearvioinnissa. Alkuperäiset lähteet ja käyttöehdot näkyvät artikkelissa. Uutinen voi olla kuvaton; käytetyn kuvan tekijä ja käyttöoikeus ilmoitetaan kuvan yhteydessä.</p></article>'''
    atomic_write(site/'tietosuoja/index.html',page('Tietosuoja ja evästeet',privacy,'/tietosuoja/'))
    atomic_write(site/'404.html',page('Sivua ei löytynyt','<h1>Sivua ei löytynyt</h1><p><a href="/">Siirry uusimpiin uutisiin</a></p>','/404.html'))
    urls=['https://uutistenlukija.fi/','https://uutistenlukija.fi/tietosuoja/']+['https://uutistenlukija.fi/uutiset/'+i+'/' for i in sorted(ids)]
    # `<lastmod>` tells the crawler a page actually changed; without it every URL looks
    # equally old, which is one reason a fresh article can sit unrecrawled.
    article_mod={}
    for row in store.db.execute('SELECT id,created_at FROM jobs'):
        try: article_mod[row['id']]=timestamp(row['created_at']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        except Exception: pass
    def _url_entry(u,mod=None):
        return '<url><loc>'+esc(u)+'</loc>'+(('<lastmod>'+esc(mod)+'</lastmod>') if mod else '')+'</url>'
    entries=[_url_entry('https://uutistenlukija.fi/'),_url_entry('https://uutistenlukija.fi/tietosuoja/')]
    entries+= [_url_entry('https://uutistenlukija.fi/uutiset/'+i+'/', article_mod.get(i)) for i in sorted(ids)]
    atomic_write(site/'sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(entries)+'</urlset>')
    atomic_write(site/'robots.txt','User-agent: *\nAllow: /\nSitemap: https://uutistenlukija.fi/sitemap.xml\n')
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    receipt={'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi','ga4_id':'G-35XERS8V6J',
        'source_commit':cmd('git','rev-parse','HEAD'),'job_id':job['id'],'packet_sha256':digest(packet),
        'draft_sha256':digest(draft),**binding,
        'new_article_files':[article_path(job)+'index.html'],
        'files':{str(p.relative_to(site)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(site.rglob('*')) if p.is_file()}}
    if binding['image_sha256'] is None:
        receipt.update(schema_version=2,packet=packet,draft=draft,review=json.loads(job['review']))
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
    binding=media(packet,draft)
    if not validate_review(json.loads(job['review']),draft)['approved']:raise ValueError('Unapproved publication')
    if store.db.execute('SELECT 1 FROM publications WHERE job_id=?',(job['id'],)).fetchone() is None:
        validate_packet(packet,datetime.now(timezone.utc),48)
    if binding['image_sha256'] is None:verify_intake(packet,state)
    with store.db:
        store.db.execute('INSERT OR IGNORE INTO publications(job_id,packet_sha,draft_sha,image_sha,source_commit,status) VALUES(?,?,?,?,?,?)',
            (job['id'],digest(packet),digest(draft),binding['image_sha256'],cmd('git','rev-parse','HEAD'),'preparing'))
    row=dict(store.db.execute('SELECT * FROM publications WHERE job_id=?',(job['id'],)).fetchone())
    if row['packet_sha']!=digest(packet) or row['draft_sha']!=digest(draft) or row['image_sha']!=binding['image_sha256']:raise ValueError('Publication packet changed')
    if row['status']=='deployed':return {'status':'idle','job_id':job['id'],'remote_commit':row['remote_commit']}
    if row['status']=='failed':return {'status':'failed','job_id':job['id']}
    if row['attempts']>=3 and not row['remote_commit']:return {'status':'publication_blocked','job_id':job['id'],'reason':'Unresolved preparation attempts'}
    if row['status'] not in ('preparing','prepared','dispatching','dispatched','unknown'):
        return {'status':'publication_blocked','job_id':job['id'],'reason':'Unknown publication state'}
    if row['status']=='unknown' and not row['remote_commit']:
        return {'status':'publication_blocked','job_id':job['id'],'reason':'Unknown remote commit outcome'}
    external_started=False
    try:
        if not row['remote_commit']:
            with store.db:store.db.execute('UPDATE publications SET attempts=attempts+1 WHERE job_id=?',(job['id'],))
            site,receipt=public_bundle(store,job,state);guard(config_path)
            external_started=True
            row['remote_commit']=make_commit(site,receipt)
            with store.db:store.db.execute('UPDATE publications SET remote_commit=?,status=? WHERE job_id=?',(row['remote_commit'],'prepared',job['id']))
        guard(config_path)
        if row['status'] in ('preparing','prepared'):
            current=api('git/ref/heads/main')['object']['sha']
            if current!=row['remote_commit']:
                api('git/refs/heads/main',{'sha':row['remote_commit'],'force':False},method='PATCH')
        runs=matching_runs(row['remote_commit'])
        if not runs:
            if row['status'] in ('dispatching','dispatched','unknown'):
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
        if run['conclusion']!='success':
            with store.db:store.db.execute("UPDATE publications SET status='failed',error='ConfirmedCompletedRunFailure' WHERE job_id=?",(job['id'],))
            raise ValueError('Public deployment failed; no automatic redispatch')
        receipt_dir=Path(state)/'deployments'/str(run['databaseId'])
        receipt_dir.mkdir(parents=True,exist_ok=True)
        if not (receipt_dir/'live-deployment.json').exists():
            cmd('gh','run','download',str(run['databaseId']),'--repo',REPO,'--name','live-deployment','--dir',str(receipt_dir))
        live=json.loads((receipt_dir/'live-deployment.json').read_text())
        assert live['remote_commit']==row['remote_commit'] and live['packet_sha256']==row['packet_sha'] and live['draft_sha256']==row['draft_sha'] and live['image_sha256']==row['image_sha']
        if live.get('text_only') != binding.get('text_only'):
            raise ValueError('Deployment text policy/provenance mismatch')
        url='https://uutistenlukija.fi/'+article_path(job)
        def read(url):
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:return r.read()
        html=read(url)
        image_sha=None
        if row['image_sha'] is not None:
            image=read('https://uutistenlukija.fi/mvp-assets/'+row['image_sha']+'.jpg')
            image_sha=hashlib.sha256(image).hexdigest()
            assert image_sha==row['image_sha']
        check_article(html.decode(),packet,draft,canonical=url)
        live.update(canonical_article=url,live_html_sha256=hashlib.sha256(html).hexdigest(),live_image_sha256=image_sha)
        atomic_write(receipt_dir/'live-readback.json',json.dumps(live,indent=2)+'\n')
        with store.db:store.db.execute("UPDATE publications SET status='deployed' WHERE job_id=?",(job['id'],))
        return {'status':'deployed','job_id':job['id'],'run_id':run['databaseId'],'remote_commit':row['remote_commit'],'deployment_id':live['deployment_id']}
    except Exception as error:
        saved=store.db.execute('SELECT status,remote_commit FROM publications WHERE job_id=?',(job['id'],)).fetchone()
        outcome='failed' if saved['status']=='failed' else ('unknown' if external_started or saved['remote_commit'] else 'failed')
        with store.db:store.db.execute("UPDATE publications SET status=?,error=? WHERE job_id=?",(outcome,safe_error(error),job['id']))
        raise

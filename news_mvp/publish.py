"""One existing GitHub/Pages executor; SQLite remembers the exact release identity."""
import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from cutover.check_release import check
from .authorization import authorize
from .diagnostics import safe_error
from .editorial import ROOT, digest, timestamp, validate_review, validate_packet
from datetime import datetime, timezone
from .release_contract import media, verify_intake, check_article, load_legacy_redirects, legacy_redirect_lines
from .site import (CATEGORY_PAGES, LATEST_PATH, OPPAAT_PATH, atomic_write, article_path,
                   esc, missing_page, page, render_site)
from .store import database
from . import slugs

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
    # Git blobs/trees are content addressed: retrying identical bytes creates no
    # second object. Commits, refs and dispatch retain their uncertain-outcome
    # handling and are never automatically replayed here.
    attempts = 3 if path in ('git/blobs','git/trees') and request.method == 'POST' else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (502,503,504) or attempt+1 == attempts:
                detail = ''
                try:
                    body=json.loads(error.read(8000))
                    detail=safe_error(ValueError(json.dumps({k:body[k] for k in ('message','errors') if k in body})))
                except (ValueError,TypeError,AttributeError):
                    pass
                raise RuntimeError(f'GitHub {request.method} {path}: HTTP {error.code} {detail}') from None
            time.sleep(2 ** attempt)


def guard(config_path):
    if json.loads(Path(config_path).read_text())['enabled'] is not True:
        raise ValueError('Controller stopped')
    authorize(json.loads(Path(config_path).read_text()))
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


class _CanonicalLinks(HTMLParser):
    """Collect the `<link rel="canonical">` hrefs of a public page.

    A page is only a usable redirect target when it names exactly one canonical and that
    URL is exactly its own path, so every other shape - no link, several links, a
    valueless or duplicated href, a duplicated attribute - is recorded as an unusable
    value instead of being guessed at.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs=[]

    def handle_starttag(self,tag,attrs):
        if tag!='link':return
        values={}
        duplicated=False
        for name,value in attrs:
            name=name.lower()
            duplicated=duplicated or name in values
            values[name]=value
        # `rel` may itself be spelled more than once, so a canonical claim is judged from
        # the raw attribute values: a value the dict overwrote is still a claim, and the
        # element is unusable either way because no single rel/href pair can be trusted
        # while the markup is ambiguous. A duplicated attribute is recorded as an unusable
        # href rather than discarded, so an earlier valid canonical can never keep an
        # ambiguous page eligible.
        rels=[value for name,value in attrs if name.lower()=='rel']
        if not any('canonical' in (value or '').lower().split() for value in rels):
            return
        if duplicated:
            self.hrefs.append('')
            return
        href=values.get('href')
        self.hrefs.append(href if isinstance(href,str) else '')


def _canonical_links(html):
    """Canonical hrefs of a page in document order; unparseable markup fails closed."""
    parser=_CanonicalLinks()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    return parser.hrefs


def _bundle_index(site,path):
    """The real `index.html` for a bundle-relative `path`, or None when there is none.

    Every node between the real bundle root and the file must be a real directory: the
    root, each ancestor directory and the file itself must not be symlinks, so a link can
    never make a file outside the bundle pass as a published page. Absolute paths and
    traversal segments are refused outright.
    """
    relative=Path(path)
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        return None
    if site.is_symlink() or not site.is_dir():
        return None
    node=site
    for part in relative.parts:
        node=node/part
        if node.is_symlink():
            return None
    if not node.is_dir():
        return None
    index=node/'index.html'
    if index.is_symlink() or not index.is_file():
        return None
    return index


def _published_page(site,path):
    """True when this bundle serves `path` as a real page that canonicalises to itself."""
    index=_bundle_index(site,path)
    if index is None:
        return False
    try:
        html=index.read_text(encoding='utf-8')
    except (OSError,UnicodeDecodeError):
        return False
    return _canonical_links(html)==['https://uutistenlukija.fi/'+path]


def _bundle_content(site):
    """Every public name in the bundle: real file paths and the directories serving a page.

    Symlinked names are recorded but never followed, so a link can neither hide content
    behind it nor take the scan outside the bundle. Only a real (or symlinked)
    `index.html` marks a directory as a page.
    """
    files,pages=set(),set()
    if site.is_symlink() or not site.is_dir():
        return files,pages
    stack=[(site,'')]
    while stack:
        node,prefix=stack.pop()
        try:
            entries=list(os.scandir(node))
        except OSError:
            continue
        if any(entry.name=='index.html' and (entry.is_symlink() or entry.is_file()) for entry in entries) and prefix:
            pages.add(prefix.rstrip('/'))
        for entry in entries:
            relative=prefix+entry.name
            if entry.is_symlink():
                files.add(relative)
            elif entry.is_dir():
                stack.append((Path(entry.path),relative+'/'))
            else:
                files.add(relative)
    return files,pages


def _serves_public_content(source,files,pages):
    """True when a reviewed mapping source already is, holds or sits under public content.

    A redirect may not take over a path a reader can already reach: a real file
    (`404.html`, `rss.xml`, an asset), a directory page (`/tietosuoja/`,
    `/ai-kuvat/`, `/sivu/N/`, an article), a source underneath such a page (its
    subtree), or an ancestor of real content (`/sivu/` above `/sivu/2/`, `/uutiset/`
    above every article). The homepage is always content and can never be a source.
    """
    segments=source.split('/')[1:-1]
    if not segments:
        return True  # the homepage always serves content; never a redirect source
    for depth in range(1,len(segments)+1):
        prefix='/'.join(segments[:depth])
        if prefix in files or prefix in pages:
            return True
    source_path='/'.join(segments)
    if source_path in files:
        return True  # `/mvp-assets/style.css/` next to the real asset file
    return any(path.startswith(source_path+'/') for path in files)


def public_bundle(store,job,state):
    ids={r[0] for r in store.db.execute("SELECT job_id FROM publications WHERE status='deployed'")}|{job['id']}
    from .backfill import release_records
    corrections = release_records(store,job['id'])
    ids.update(r['job_id'] for r in corrections)
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    binding=media(packet,draft)
    if packet.get('publication_basis') is not None:verify_intake(packet,state,archive_image_only=bool(corrections))
    site=Path(state)/'live-site'  # Never reads or overlays the abandoned public-history tree.
    # The reviewed legacy demand inventory is loaded before anything is written: a missing
    # or malformed inventory fails the release closed rather than producing a bundle whose
    # redirects silently lost the reviewed mappings. Eligibility of each mapping is judged
    # later, against the pages this render actually wrote.
    mappings=load_legacy_redirects()['mappings']
    # Only the article being published now must satisfy today's policy digest; the archive
    # was released under the policy in force then and is bound to its captured bytes.
    from .frontpage import load
    snapshot = load(state)
    render_site(store,site,state,public=True,include_ids=ids,verify_policy_ids={job['id']},snapshot=snapshot)
    privacy='''<article class="story"><h1>Tietosuoja ja evästeet</h1><p>Voit käyttää uutispalvelua sallimatta analytiikkaa. Luvallasi käytämme Google Analyticsia sivuston käytön mittaamiseen. Emme käytä mainonnan evästeitä.</p><p>Suostumus tallennetaan selaimeesi. Voit muuttaa valintaasi sivun Evästeasetukset-painikkeella. Analytiikan poistaminen käytöstä poistaa tämän sivuston Google Analytics -evästeet selaimesta.</p><p>Uutiset laaditaan tekoälyn avulla ja tarkastetaan erillisessä lähdearvioinnissa. Alkuperäiset lähteet ja käyttöehdot näkyvät artikkelissa. Jokaisella uutisella on tarkastettu aiheeseen liittyvä kuva; käytetyn kuvan tekijä ja käyttöoikeus ilmoitetaan kuvan yhteydessä.</p></article>'''
    atomic_write(site/'tietosuoja/index.html',page('Tietosuoja ja evästeet',privacy,'/tietosuoja/',snapshot=snapshot))
    # Terms for AI illustrations. This is the license_url/source_url of every generated article
    # image, so it must exist and must actually describe the image rights - pointing that field
    # at the privacy page was rejected by the independent reviewer, correctly.
    illustrations = '''<article class="story"><h1>AI-generoidut kuvat</h1>
<p>Osa uutisten kuvista on tekoälyn tuottamia. Ne eivät ole valokuvia todellisista tapahtumista eivätkä esitä todellisia henkilöitä.</p>
<p>Artikkelin kuvan alla lukee: AI-generoitu kuva. Ei valokuva tapahtumasta.</p>
<p>AI-generoitu kuva perustuu tarkastetun uutisen sisältöön. Se näyttää aiheeseen liittyviä esineitä, paikkoja tai prosesseja ilman keksittyjä henkilöitä tai tapahtumatilanteita.</p>
<p>Ensisijaisesti käytämme aiheeseen liittyvää oikeaa kuvaa, jonka käyttöoikeus on erikseen varmistettu. Lähdetekstin käyttöehdot eivät yksin anna oikeutta lähteen valokuviin. Kuvan tekijä, lähde ja käyttöehdot ilmoitetaan artikkelin käyttöoikeusosiossa.</p>
<p>Kuvituksen tuottamiseen käytetty malli ja kehotteen tarkiste tallennetaan julkaisurekisteriin.</p>
</article>'''
    atomic_write(site/'ai-kuvat/index.html',page('AI-generoidut kuvat',illustrations,'/ai-kuvat/',snapshot=snapshot))
    # A reused build directory must not re-publish the superseded generated
    # terms page. Remove only that known derived page after verifying its own
    # canonical identity; protected source/state/history is never touched.
    from .image_wording import RETIRED_IMAGE_STEM
    retired_terms = RETIRED_IMAGE_STEM + 'at/'
    retired_index = site/retired_terms/'index.html'
    if retired_index.is_symlink() or (site/retired_terms).is_symlink():
        raise ValueError('Refuse a linked retired image terms page')
    if retired_index.exists():
        if not _published_page(site, retired_terms):
            raise ValueError('Retired image terms page has an unexpected identity')
        retired_index.unlink()
    # One pass over the store builds the slug/mtime maps used by the sitemap and redirects.
    article_mod={}
    title_by_id={}
    for row in store.db.execute('SELECT id,created_at,draft FROM jobs'):
        title_by_id[row['id']]=row['draft']
        try: article_mod[row['id']]=timestamp(row['created_at']).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        except Exception: pass
    def _slug_for(identifier):
        # title_by_id maps id->raw draft; a NULL draft must still yield a valid slug
        # rather than crashing the whole publish (regression: 2026-09-17).
        draft = title_by_id.get(identifier)
        if draft is not None and not isinstance(draft, (str, bytes, dict)):
            draft = None
        return article_path({'id': identifier, 'draft': draft})
    def _url_entry(u,mod=None):
        return '<url><loc>'+esc(u)+'</loc>'+(('<lastmod>'+esc(mod)+'</lastmod>') if mod else '')+'</url>'
    entries=[_url_entry('https://uutistenlukija.fi/'),
             _url_entry('https://uutistenlukija.fi/tietosuoja/'),
             _url_entry('https://uutistenlukija.fi/lahteet/')]
    entries+= [_url_entry('https://uutistenlukija.fi/'+_slug_for(i), article_mod.get(i)) for i in sorted(ids)]
    # Rendered archive pages are published pages too; the sitemap must list them.
    # Symlinked roots/directories/index files and nonnumeric or leading-zero names are not pages.
    archive_root=site/'sivu'
    archive_pages=[]
    if not archive_root.is_symlink() and archive_root.is_dir():
        for child in archive_root.iterdir():
            if child.is_symlink() or not child.is_dir(): continue
            if not (child.name.isascii() and child.name.isdigit()) or child.name.startswith('0'): continue
            if int(child.name)<2: continue
            index=child/'index.html'
            if index.is_symlink() or not index.is_file(): continue
            archive_pages.append(int(child.name))
    # The public 404 body is a real page with usable exits, not a bare stub. It always
    # names the newest listing, and names /sivu/2/ only when that archive page really
    # exists in this bundle, judged by the same archive_pages validation the sitemap uses.
    atomic_write(site/'404.html',missing_page('/sivu/2/' if 2 in archive_pages else '/'))
    entries+=[_url_entry('https://uutistenlukija.fi/sivu/'+str(n)+'/') for n in sorted(archive_pages)]
    # Category/latest/guides routes are sitemap entries only when the bundle really
    # contains a page whose canonical points back to that exact route. This keeps a
    # stale or tampered directory out without changing article/archive/legacy checks.
    listing_paths = [f'categories/{slug}/' for slug, _display in CATEGORY_PAGES]
    listing_paths += [LATEST_PATH.lstrip('/'), OPPAAT_PATH.lstrip('/')]
    entries += [_url_entry('https://uutistenlukija.fi/'+path)
                for path in listing_paths if _published_page(site, path)]
    atomic_write(site/'sitemap.xml','<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(entries)+'</urlset>')
    atomic_write(site/'robots.txt','User-agent: *\nAllow: /\nSitemap: https://uutistenlukija.fi/sitemap.xml\n')
    # --- Redirects: reviewed legacy mappings plus same-article hash aliases -----
    # Eligibility is what THIS render actually wrote: the current job plus deployed ids
    # render_site selected, each confirmed as a real, non-symlink index.html inside the
    # real bundle root whose single canonical is exactly its own path. A deployed id this
    # render did not write, or whose page is missing, linked or mis-canonical, is not a
    # working 301 target and must never get a rule.
    written=[]
    for candidate in store.articles():
        if candidate['id'] not in ids:
            continue
        path=article_path(candidate)
        if _published_page(site,path):
            written.append((candidate['id'],path))
    eligible=['/'+path for _,path in written]
    # Reviewed legacy demand is data-driven and fail-closed: a malformed inventory, or a
    # mapping that is not a reviewed equivalence onto a page this bundle serves, fails the
    # release. An invalid mapping is never dropped so that a release can proceed without it.
    # A source that is, holds or lives under real public content (privacy, illustrations,
    # archive listings, article files, any ancestor or descendant of them) is refused: the
    # bundle already owns that path and a rule there would hijack what readers can reach.
    if mappings:
        files,pages=_bundle_content(site)
        for mapping in mappings:
            source=mapping['source']
            if _serves_public_content(source,files,pages):
                raise ValueError('Legacy mapping source already serves public content: '+source)
    # Bare hash URLs for the eligible articles get an additive 301 to their readable slug.
    # These are generated, not editorial: the source is the article's own legacy hash
    # identity and the target is the canonical path this same render wrote for that same id.
    # They deliberately skip the public-content check - the bundle may hold content at the
    # legacy path (an alias page or a leftover) and the rule is still that article's old URL
    # resolving to its new one - but the union below still refuses duplicates, chains and
    # loops, and no rule may ever target the homepage or a wildcard.
    aliases=[]
    for identifier,path in written:
        if not slugs.is_legacy_hash_path(identifier):
            continue
        source='/uutiset/'+identifier+'/'
        if source=='/'+path:
            continue  # a self-alias is not a redirect
        aliases.append((source,'/'+path))
    lines=legacy_redirect_lines(mappings,eligible,aliases)
    if lines:
        atomic_write(site/'_redirects','\n'.join(lines)+'\n')
    else:
        # No rules is not the same as no file: a leftover _redirects from an earlier
        # release would keep serving retired wildcards/paths this release does not own.
        stale=site/'_redirects'
        if stale.is_symlink() or stale.exists():
            stale.unlink()
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    receipt={'public_release_authorized':True,'hermes_step':5,'origin':'https://uutistenlukija.fi','ga4_id':'G-35XERS8V6J',
        'source_commit':cmd('git','rev-parse','HEAD'),'job_id':job['id'],'packet_sha256':digest(packet),
        'draft_sha256':digest(draft),**binding,
        'new_article_files':[article_path(job)+'index.html'],
        'files':{str(p.relative_to(site)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(site.rglob('*')) if p.is_file()}}
    if binding.get('text_only') or binding.get('text_provenance'):
        receipt.update(schema_version=2,packet=packet,draft=draft,review=json.loads(job['review']))
    if corrections:
        receipt.update(image_backfill=corrections,image_backfill_sha256=digest(corrections))
    check(site,receipt)
    atomic_write(Path(state)/'release.json',json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return site,receipt


def upload_blob(site,data):
    expected=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    checkpoint=Path(site).parent/'uploaded-git-blobs'/expected
    if checkpoint.exists():
        if checkpoint.read_text()!=expected+'\n':raise ValueError('Uploaded Git blob checkpoint changed')
        return expected
    actual=api('git/blobs',{'content':base64.b64encode(data).decode(),'encoding':'base64'})['sha']
    if actual!=expected:raise ValueError('Uploaded Git blob identity mismatch')
    atomic_write(checkpoint,expected+'\n')
    return expected


class UncommittedPreparationError(RuntimeError):
    """Only content-addressed objects were attempted; no commit/ref/dispatch."""


def incremental_tree(entries, base=None):
    """Bound GitHub's nested-path work while retaining every preceding chunk."""
    # Full public trees contain hundreds of nested article/image paths. GitHub
    # can reject one large request with a 422 server processing timeout.
    # A base tree makes successive chunks an exact cumulative tree; it does not
    # update a branch. Preserve last-entry replacement semantics for workflows.
    entries = {entry['path']: entry for entry in entries}
    ordered = [entries[path] for path in sorted(entries)]
    for offset in range(0, len(ordered), 64):
        request = {'tree': ordered[offset:offset+64]}
        if base is not None:
            request['base_tree'] = base
        base = api('git/trees', request)['sha']
    if base is None:
        raise ValueError('Refuse an empty release tree')
    return base


def prepare_commit_tree(site,receipt):
    parent=api('git/ref/heads/main')['object']['sha'];base=api('git/commits/'+parent)['tree']['sha']
    def blob(data):return upload_blob(site,data)
    public_tree=incremental_tree([{'path':name,'mode':'100644','type':'blob','sha':blob((site/name).read_bytes())} for name in receipt['files']])
    paths=cmd('git','ls-files').splitlines()
    entries=[{'path':name,'mode':'100644','type':'blob','sha':blob((ROOT/name).read_bytes())} for name in paths]
    entries += [{'path':'public','mode':'040000','type':'tree','sha':public_tree},
        {'path':'release/release.json','mode':'100644','type':'blob','sha':blob(json.dumps(receipt,ensure_ascii=False,indent=2).encode())},
        {'path':'.github/workflows/deploy.yml','mode':'100644','type':'blob','sha':blob((ROOT/'ops/deploy.yml').read_bytes())},
        {'path':'.github/workflows/source-validation.yml','mode':'100644','type':'blob','sha':blob((ROOT/'ops/source-validation.yml').read_bytes())}]
    tree=incremental_tree(entries,base)
    return parent,tree


def make_commit(site,receipt):
    try:
        parent,tree=prepare_commit_tree(site,receipt)
    except Exception as error:
        raise UncommittedPreparationError(safe_error(error)) from error
    # Beyond this point an uncertain response must remain blocked. Never replay
    # a commit, ref update or workflow dispatch as a preparation retry.
    return api('git/commits',{'message':'Fresh MVP reviewed article '+receipt['job_id'][:12], 'tree':tree,'parents':[parent],
                            'author':{'name':'Uutistenlukija MVP','email':'news-mvp@localhost'}})['sha']


def matching_runs(commit):
    return json.loads(cmd('gh','run','list','--repo',REPO,'--workflow',WORKFLOW,'--commit',commit,
                         '--event','workflow_dispatch','--limit','10','--json','databaseId,status,conclusion,headSha'))


def publish(store,job,state,config_path):
    ensure_table(store);guard(config_path)
    packet,draft=json.loads(job['packet']),json.loads(job['draft'])
    from .site import display_image
    if not display_image(draft.get('image')):
        return {'status': 'image_pending', 'job_id': job['id'], 'retryable': True}
    binding=media(packet,draft)
    if not validate_review(json.loads(job['review']),draft)['approved']:raise ValueError('Unapproved publication')
    if store.db.execute('SELECT 1 FROM publications WHERE job_id=?',(job['id'],)).fetchone() is None:
        validate_packet(packet,datetime.now(timezone.utc),48)
    if packet.get('publication_basis') is not None:
        from .backfill import active
        verify_intake(packet,state,archive_image_only=active(store,job['id']) is not None)
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
        if (('stock_image' in live) != ('stock_image' in binding) or
                live.get('stock_image') != binding.get('stock_image')):
            raise ValueError('Deployment stock binding mismatch')
        if live.get('text_only') != binding.get('text_only'):
            raise ValueError('Deployment text policy/provenance mismatch')
        # Legacy image deployment records predate text_provenance, so only new
        # receipts carrying the additive marker must match it exactly.
        if 'text_provenance' in live and live['text_provenance'] != binding.get('text_provenance'):
            raise ValueError('Deployment text policy/provenance mismatch')
        from .backfill import release_records, complete as complete_backfill
        corrections=release_records(store,job['id'])
        if corrections and live.get('image_backfill_sha256')!=digest(corrections):
            raise ValueError('Deployment archive correction binding mismatch')
        url='https://uutistenlukija.fi/'+article_path(job)
        def read(url):
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=25) as r:return r.read()
        # URL-scheme migration: a deployment dispatched before slugs shipped published the
        # article at the hash path, and the slug now 404s until a slug-built bundle deploys.
        # Read whichever form this exact deployment actually produced, and record which one,
        # so reconciliation is not wedged by the scheme change. The canonical URL written to
        # the receipt is still the slug, which is what the site will serve going forward.
        legacy_url='https://uutistenlukija.fi/uutiset/'+job['id']+'/'
        try:
            html=read(url)
        except urllib.error.HTTPError as error:
            if error.code!=404 or url==legacy_url:
                raise
            html=read(legacy_url)
            url=legacy_url
        image_sha=None
        if row['image_sha'] is not None:
            image=read('https://uutistenlukija.fi/mvp-assets/'+row['image_sha']+'.jpg')
            image_sha=hashlib.sha256(image).hexdigest()
            assert image_sha==row['image_sha']
        check_article(html.decode(),packet,draft,canonical=url)
        complete_backfill(store,job['id'],row['remote_commit'],run['databaseId'],read)
        live.update(canonical_article=url,live_html_sha256=hashlib.sha256(html).hexdigest(),live_image_sha256=image_sha)
        atomic_write(receipt_dir/'live-readback.json',json.dumps(live,indent=2)+'\n')
        with store.db:store.db.execute("UPDATE publications SET status='deployed' WHERE job_id=?",(job['id'],))
        # Best-effort search-engine ping; must never affect the publication outcome.
        try:
            from .indexing import ping
            ping([url,'https://uutistenlukija.fi/'])
        except Exception:
            pass
        return {'status':'deployed','job_id':job['id'],'run_id':run['databaseId'],'remote_commit':row['remote_commit'],'deployment_id':live['deployment_id']}
    except Exception as error:
        saved=store.db.execute('SELECT status,remote_commit FROM publications WHERE job_id=?',(job['id'],)).fetchone()
        outcome='failed' if saved['status']=='failed' else ('unknown' if external_started or saved['remote_commit'] else 'failed')
        if isinstance(error,UncommittedPreparationError) and not saved['remote_commit']:
            outcome='preparing'
        with store.db:store.db.execute("UPDATE publications SET status=?,error=? WHERE job_id=?",(outcome,safe_error(error),job['id']))
        raise


def requeue_failed(config, job_id=None):
    """Reset failed publications to 'preparing' so live ticks can retry them.

    'failed' is normally terminal: it records a confirmed bad outcome. This operator
    path exists for the other class - outcomes that failed because of a since-fixed
    pipeline bug. It re-derives packet/draft/image hashes from the stored records (a
    failed attempt may predate an attached illustration) and clears run state; the
    normal publish path then re-validates everything before anything reaches the
    public site.
    """
    state=config['state_dir']
    reset,skipped=[],[]
    with database(state) as store:
        ensure_table(store)
        query="SELECT job_id FROM publications WHERE status='failed'"
        rows=store.db.execute(query+(" AND job_id=?" if job_id else "")+" ORDER BY rowid",
                              ((job_id,) if job_id else ())).fetchall()
        for row in rows:
            identifier=row['job_id']
            job=store.get(identifier)
            if job is None or not job.get('draft') or not job.get('review'):
                skipped.append({'job_id':identifier,'reason':'No reviewed draft'})
                continue
            try:
                packet,draft=json.loads(job['packet']),json.loads(job['draft'])
                binding=media(packet,draft)
            except (ValueError,TypeError,KeyError) as error:
                skipped.append({'job_id':identifier,'reason':safe_error(error)})
                continue
            with store.db:
                store.db.execute("UPDATE publications SET packet_sha=?,draft_sha=?,image_sha=?,status='preparing',attempts=0,remote_commit=NULL,run_id=NULL,error=NULL WHERE job_id=?",
                                 (digest(packet),digest(draft),binding['image_sha256'],identifier))
            reset.append(identifier)
        remaining=store.db.execute("SELECT count(*) FROM publications WHERE status='failed'").fetchone()[0]
    return {'reset':reset,'skipped':skipped,'remaining_failed':remaining}

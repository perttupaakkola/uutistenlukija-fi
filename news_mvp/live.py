"""One scheduled controller: explicit source recipes -> draft/review -> one publisher."""
import json
import time
from pathlib import Path

from .diagnostics import safe_error
from .controller import (backfill_missing_images, has_missing_images, hermes_model, ingest,
                          load_config, single_tick, tick)
from .editorial import ROOT, digest, web_url
from .intake import collect
from .discovery import discover,collect_modis
from .publish import ensure_table, publish, guard
from .store import database

_RELATED_SEARCHER = None


def _advance_job(store, job, config, config_path, errors=None):
    """Advance one admitted job before considering another discovery candidate."""
    if job['status'] in ('ready', 'running', 'approved'):
        tick(config_path, _already_locked=True, target_job_id=job['id'],
             image_backfill_limit=1)
        job = store.get(job['id'])
    if job['status'] in ('rendered', 'approved'):
        result = publish(store, job, config['state_dir'], config_path)
    else:
        result = {'status': job['status'], 'job_id': job['id']}
    if errors:
        result['source_errors'] = errors
    return result


def _related_searcher():
    """Lazily build the search backend used for related-coverage lookups.

    Returns None when no backend is importable, in which case collection proceeds with a
    single source exactly as before. Cached so a tick does not rebuild the client per story.
    """
    global _RELATED_SEARCHER
    if _RELATED_SEARCHER is not None:
        return _RELATED_SEARCHER or None
    try:
        from ddgs import DDGS
    except ImportError:
        _RELATED_SEARCHER = False
        return None

    def search(query, limit):
        results = []
        with DDGS() as client:
            for item in client.text(query, max_results=limit):
                url = item.get("href") or item.get("url")
                if url:
                    results.append({"url": url, "title": item.get("title") or ""})
        return results

    _RELATED_SEARCHER = search
    return search


def live_tick(config_path):
    config=load_config(config_path)
    if not config['enabled']:return {'status':'stopped'}
    if config['backend']!='hermes':raise ValueError('Live scheduler refuses the fixture backend')
    if config.get('discovery',{}).get('family')=='finnish-official':
        raise ValueError('Official Finnish sources are private preparation only; public policy is not approved')
    if config.get('discovery',{}).get('family')=='news-reviewed-v2':guard(config_path)
    with single_tick(config['state_dir']) as locked:
        if not locked:return {'status':'busy'}
        with database(config['state_dir']) as store:
            ensure_table(store)
            # Publication reconciliation owns the tick, even after its source disappears
            # or ages out. Never rotate providers while an outcome is unresolved.
            pending=store.db.execute("SELECT job_id,status FROM publications WHERE status NOT IN ('deployed','failed') ORDER BY rowid LIMIT 2").fetchall()
            if pending:
                if len(pending)!=1:
                    return {'status':'publication_blocked','reason':'Multiple unresolved publications require operator reconciliation'}
                job=store.get(pending[0]['job_id'])
                if job is None:
                    return {'status':'publication_blocked','job_id':pending[0]['job_id'],'reason':'Missing pending publication job'}
                return publish(store,job,config['state_dir'],config_path)
            # A timed-out/interrupted article must retain queue priority even if it has fallen
            # out of the newest discovery window. Without this step, fresh candidates can strand
            # a due retry forever.
            store.recover(config['max_attempts'])
            retry = None
            for candidate in store.db.execute(
                    "SELECT id,packet FROM jobs WHERE status='ready' AND next_attempt<=? "
                    "AND attempts<? ORDER BY created_at, id",
                    (time.time(), config['max_attempts'])):
                try:
                    fixture = json.loads(candidate['packet']).get('fixture') is True
                except (TypeError, ValueError):
                    fixture = False
                if not fixture:
                    retry = candidate
                    break
            if retry:
                return _advance_job(store, store.get(retry['id']), config, config_path)
            recipes=[json.loads((ROOT/path).read_text()) for path in config.get('source_recipes',[])]
            errors=[]
            if config.get('discovery',{}).get('family')=='news-reviewed-v2':
                excluded={r[0] for r in store.db.execute("SELECT source_url FROM jobs WHERE status IN ('rejected','failed') OR id IN (SELECT job_id FROM publications WHERE status IN ('deployed','failed'))")}
                last=store.db.execute('SELECT packet FROM jobs ORDER BY created_at DESC,rowid DESC LIMIT 1').fetchone()
                previous=json.loads(last[0]) if last else {}
                after=previous.get('publication_basis',{}).get('provider') or ('nasa-modis' if previous.get('sources') and 'nasa.gov' in previous['sources'][0]['url'] else None)
                recipes+=discover(config,excluded=excluded,errors=errors,after_provider=after)
            else:recipes+=discover(config)
            seen=set()
            for recipe in recipes:
                job_id=digest('url:'+web_url(recipe['url']))
                publication=store.db.execute('SELECT * FROM publications WHERE job_id=?',(job_id,)).fetchone()
                if job_id in seen:continue
                seen.add(job_id)
                if publication and publication['status'] in ('deployed','failed'):continue
                job=store.get(job_id)
                if job and job['status'] in ('rejected','failed'):continue
                if job is None:
                    cap=config.get('migration_publication_limit')
                    if config.get('authorization_mode','migration')=='migration' and cap is not None:
                        if store.db.execute("SELECT count(*) FROM publications WHERE status='deployed'").fetchone()[0]>=cap:continue
                    try:
                        collector=collect_modis if recipe.get('family')=='nasa-modis' else collect
                        # Related-coverage search turns the single-source packet into a
                        # multi-source one so the writer synthesises instead of restating one
                        # publisher. Best-effort by design: no searcher (or a failing one)
                        # leaves the packet exactly as it was.
                        collector_options = {}
                        if collector is collect and config.get('related_sources', True):
                            searcher = _related_searcher()
                            if searcher is not None:
                                collector_options['search'] = searcher
                        packet,intake_receipt=collector(recipe,config['state_dir'],**collector_options)
                    except (ValueError,OSError) as error:
                        errors.append({'provider':recipe.get('provider',recipe.get('family','explicit')),'stage':'collection','url':recipe['url'],'error':safe_error(error)})
                        continue
                    admission=ingest(config,packet)
                    if admission['id']!=job_id:raise ValueError('Source identity mismatch')
                    job=store.get(job_id)
                # Public publication state is one-row-at-a-time; keep any image backfill
                # attached to this live tick inside the same atomic release.
                return _advance_job(store, job, config, config_path, errors)
            # Existing published/text-only stories use the same reviewed image chain as new
            # stories. A live release tracks one publication row at a time; the private
            # controller may fill up to three, but the public tick attaches one atomically.
            if config.get('illustrations', True) and has_missing_images(store):
                model=hermes_model(config)
                backfilled=backfill_missing_images(store,config['state_dir'],model,limit=1)
                if backfilled:
                    result=publish(store,backfilled[0],config['state_dir'],config_path)
                    result['image_backfilled']=len(backfilled)
                    return result
            result={'status':'idle','publications':store.db.execute("SELECT count(*) FROM publications WHERE status='deployed'").fetchone()[0]}
            if errors:result['source_errors']=errors
            return result

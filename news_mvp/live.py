"""One scheduled controller: explicit source recipes -> draft/review -> one publisher."""
import json
from pathlib import Path

from .controller import ingest, load_config, single_tick, tick
from .editorial import ROOT, digest, web_url
from .intake import collect
from .discovery import discover,collect_modis
from .publish import ensure_table, publish, guard
from .store import database


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
                        packet,intake_receipt=collector(recipe,config['state_dir'])
                    except (ValueError,OSError) as error:
                        errors.append({'provider':recipe.get('provider',recipe.get('family','explicit')),'stage':'collection','url':recipe['url'],'error':type(error).__name__})
                        continue
                    admission=ingest(config,packet)
                    if admission['id']!=job_id:raise ValueError('Source identity mismatch')
                    job=store.get(job_id)
                if job['status'] in ('ready','running','approved'):
                    tick(config_path,_already_locked=True,target_job_id=job_id)
                    job=store.get(job_id)
                if job['status'] in ('rendered','approved'):
                    result=publish(store,job,config['state_dir'],config_path)
                    if errors:result['source_errors']=errors
                    return result
                result={'status':job['status'],'job_id':job_id}
                if errors:result['source_errors']=errors
                return result
            result={'status':'idle','publications':store.db.execute("SELECT count(*) FROM publications WHERE status='deployed'").fetchone()[0]}
            if errors:result['source_errors']=errors
            return result

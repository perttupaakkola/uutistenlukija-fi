"""One scheduled controller: explicit source recipes -> draft/review -> one publisher."""
import json
from pathlib import Path

from .controller import ingest, load_config, single_tick, tick
from .editorial import ROOT, digest, web_url
from .intake import collect
from .discovery import discover,collect_modis
from .publish import ensure_table, publish
from .store import database


def live_tick(config_path):
    config=load_config(config_path)
    if not config['enabled']:return {'status':'stopped'}
    if config['backend']!='hermes':raise ValueError('Live scheduler refuses the fixture backend')
    with single_tick(config['state_dir']) as locked:
        if not locked:return {'status':'busy'}
        with database(config['state_dir']) as store:
            ensure_table(store)
            recipes=[json.loads((ROOT/path).read_text()) for path in config.get('source_recipes',[])]
            recipes+=discover(config)
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
                    except (ValueError,OSError):
                        continue
                    admission=ingest(config,packet)
                    if admission['id']!=job_id:raise ValueError('Source identity mismatch')
                    job=store.get(job_id)
                if job['status'] in ('ready','running','approved'):
                    tick(config_path,_already_locked=True,target_job_id=job_id)
                    job=store.get(job_id)
                if job['status'] in ('rendered','approved'):
                    return publish(store,job,config['state_dir'],config_path)
                return {'status':job['status'],'job_id':job_id}
            return {'status':'idle','publications':store.db.execute("SELECT count(*) FROM publications WHERE status='deployed'").fetchone()[0]}

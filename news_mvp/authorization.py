"""Migration gate now; exact operator-reviewed steady-state policy only after activation."""
import json
from pathlib import Path
from .editorial import ROOT,digest

def authorize(config,source_commit):
    if config.get('enabled') is not True:raise ValueError('Controller stopped')
    mode=config.get('authorization_mode','migration')
    if mode=='migration':
        from cutover.prepare import BUNDLE,released
        control=json.loads((BUNDLE/'CONTROL.json').read_text());review=json.loads((BUNDLE/'reviews/04.json').read_text())
        if not released(control,review,ROOT):raise ValueError('Public migration gate closed')
        return
    if mode!='steady_state':raise ValueError('Unknown publication authorization mode')
    policy=json.loads((Path(config['state_dir'])/'steady-state-policy.json').read_text())
    family=config.get('discovery',{}).get('family')
    if family=='news-reviewed-v2':
        expected=proposed_policy_v2(source_commit)
        expected.update(enabled=True,approved_by='Hermes',review_ref=policy.get('review_ref'))
        if policy!=expected or not policy.get('review_ref') or config.get('source_recipes') or config['max_source_age_hours']!=48 or config['discovery']!={'family':'news-reviewed-v2','max_candidates':5}:
            raise ValueError('Combined source policy is not explicitly approved for this exact candidate')
        return
    required={'enabled':True,'approved_by':'Hermes','source_commit':source_commit,'origin':'https://uutistenlukija.fi','repository':'perttupaakkola/uutistenlukija-fi','workflow_id':246481423,'source_family':'nasa-modis','max_admissions_per_tick':1}
    if any(policy.get(k)!=v for k,v in required.items()) or not policy.get('review_ref'):
        raise ValueError('Steady-state policy is not explicitly approved for this candidate')
    if config.get('source_recipes') or config.get('discovery',{}).get('family')!='nasa-modis':
        raise ValueError('Source configuration exceeds reviewed policy')
    if config['max_source_age_hours']>policy['max_source_age_hours'] or config['discovery'].get('max_candidates',5)>policy['max_candidates']:
        raise ValueError('Source limits exceed reviewed policy')

def proposed_policy(source_commit):
    return {'enabled':False,'approved_by':None,'review_ref':None,'source_commit':source_commit,
            'origin':'https://uutistenlukija.fi','repository':'perttupaakkola/uutistenlukija-fi',
            'workflow_id':246481423,'source_family':'nasa-modis','max_candidates':5,
            'max_source_age_hours':48,'max_admissions_per_tick':1,'timer_interval_seconds':900}


def proposed_policy_v2(source_commit):
    from .official import policy
    return {**proposed_policy(source_commit),'schema_version':2,'source_family':'news-reviewed-v2',
            'source_families':['nasa-modis','helsinki','stat','kuntaliitto','ecb'],'text_only_policy':'official-text-v1',
            'text_only_policy_sha256':digest(policy()),'max_index_entries_per_official_source':50,
            'max_fetch_calls_per_tick':20}

"""Isolated crash proof using a read-only copy of the reviewed phase-3 record."""
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from news_mvp.controller import tick, ingest, load_config
from news_mvp.store import database


def proof(source, evidence):
    source=Path(source)
    with tempfile.TemporaryDirectory(prefix='news-mvp-restart-') as tmp:
        root=Path(tmp);state=root/'state';state.mkdir()
        live=sqlite3.connect(f'file:{source}/jobs.sqlite?mode=ro',uri=True)
        snapshot=sqlite3.connect(state/'jobs.sqlite');live.backup(snapshot);live.close()
        snapshot.execute("UPDATE jobs SET status='approved' WHERE status='rendered'");snapshot.commit();snapshot.close()
        with database(state) as store:
            original=dict(store.articles()[0]);packet=json.loads(original['packet']);image=packet.get('image')
        if image and image.get('local_path'):
            dst=state/image['local_path'];dst.parent.mkdir(parents=True);shutil.copyfile(source/image['local_path'],dst)
        config=root/'config.json';config.write_text(json.dumps({'enabled':True,'backend':'hermes','state_dir':str(state),'output_dir':str(root/'site')}))
        code='''import os,signal,sys
from news_mvp.controller import tick
from news_mvp.store import Store
def crash(self, ids): os.kill(os.getpid(), signal.SIGKILL)
Store.mark_rendered=crash
tick(sys.argv[1])
'''
        child=subprocess.run([sys.executable,'-B','-c',code,str(config)],timeout=15,capture_output=True)
        assert child.returncode==-9
        class NoModel:
            name='no-model-allowed'
            def call(self,*args,**kwargs):raise AssertionError('Persisted review must avoid all model calls')
        result=tick(config,model=NoModel());assert result['status']=='rendered'
        replay=ingest(load_config(config),packet);assert replay['admitted'] is False
        assert tick(config,model=NoModel())['status']=='idle'
        with database(state) as store:
            final=dict(store.articles()[0]);assert len(store.articles())==1
            assert final['draft']==original['draft'] and final['review']==original['review']
        pages=list((root/'site/uutiset').glob('*/index.html'));assert len(pages)==1
        report={'child_signal':'SIGKILL','child_returncode':child.returncode,'resume':result,'duplicate_admitted':False,'second_tick':'idle','articles':1,'model_calls':0,'id':final['id'],'draft_sha256':hashlib.sha256(final['draft'].encode()).hexdigest(),'article_sha256':hashlib.sha256(pages[0].read_bytes()).hexdigest(),'scope':'temporary isolated SQLite backup and one reviewed photo; live state never opened writable; no deployment'}
        Path(evidence).write_text(json.dumps(report,indent=2)+'\n')
        return report


if __name__=='__main__':print(json.dumps(proof(sys.argv[1],sys.argv[2])))

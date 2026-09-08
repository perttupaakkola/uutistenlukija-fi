"""Actual retained shell wrappers; ALL article/repository data is synthetic.
Linux Landlock denies nonfixture home reads and outside-scratch writes; seccomp
blocks sockets. No production Python imports, env files, queues or credentials.
Only producer/send boundaries and Git fault/identity seams are mocked; Git refs,
fetches, commits and pushes use real owned local repositories. Scratch retained.
"""
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parent
ROOT = Path(tempfile.mkdtemp(prefix='legacy-git-synthetic-'))
ENV = {'PATH': '/usr/bin:/bin', 'HOME': str(ROOT), 'GIT_CONFIG_NOSYSTEM': '1',
       'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_ALLOW_PROTOCOL': 'file',
       'GIT_TERMINAL_PROMPT': '0', 'LANG': 'C', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}


def sandbox():
    """Fail test setup if kernel isolation cannot be installed."""
    libc = ctypes.CDLL(None, use_errno=True)
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled', ctypes.c_uint64)]
    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed', ctypes.c_uint64), ('parent', ctypes.c_int)]
    rights = (1 << 15) - 1
    attr = Ruleset(rights)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'Landlock required')
    for path, allowed in [(str(ROOT), rights), ('/usr', 13), ('/bin', 13),
                          ('/lib', 13), ('/lib64', 13), ('/dev/null', 6),
                          ('/dev/urandom', 4)]:
        pfd = os.open(path, os.O_PATH)
        rule = PathRule(allowed, pfd)
        if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
            raise OSError(ctypes.get_errno(), path)
        os.close(pfd)
    if libc.prctl(38, 1, 0, 0, 0) or libc.syscall(446, fd, 0):
        raise OSError(ctypes.get_errno(), 'Landlock restrict')
    os.close(fd)
    sec = ctypes.CDLL('libseccomp.so.2')
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    ctx = sec.seccomp_init(0x7fff0000)
    for name in [b'socket', b'connect']:
        nr = sec.seccomp_syscall_resolve_name(name)
        if sec.seccomp_rule_add(ctx, 0x50000 | errno.EPERM, nr, 0):
            raise RuntimeError('seccomp rule failed')
    if sec.seccomp_load(ctx):
        raise RuntimeError('seccomp required')


def run(args, cwd, env=ENV, guarded=False, check=True):
    p = subprocess.run(args, cwd=cwd, env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       preexec_fn=sandbox if guarded else None, timeout=15)
    if check and p.returncode:
        raise AssertionError(p.stdout)
    return p


def git(repo, *args):
    return run(['/usr/bin/git', *args], repo).stdout.strip()


GIT_SHIM = '''#!/usr/bin/python3
import os, pathlib, subprocess, sys
root=pathlib.Path(os.environ['FIXTURE'])
assert pathlib.Path.cwd().is_relative_to(root)
a=sys.argv[1:]; case=os.environ['CASE']; produced=(root/'produced').exists()
assert not set(a).intersection({'reset','checkout','stash','rebase','pull','clean','--force','--force-with-lease'})
remote=subprocess.check_output(['/usr/bin/git','config','--get','remote.origin.url'], text=True).strip()
assert pathlib.Path(remote).is_relative_to(root)
if a[:2]==['remote','get-url']:
    print('https://github.com/perttupaakkola/uutistenlukija-fi.git' if case!='wrongrepo' else 'https://invalid.example/repo.git'); sys.exit(0)
command=a[0] if a[0]!='-c' else a[2]
fail={'fetchfail':'fetch','reffail':'rev-parse','statusfail':'status','postfetch':'fetch','postref':'rev-parse','poststatus':'status','pushfail':'push','addfail':'add','difffail':'diff','commitfail':'commit'}.get(case)
if command==fail and (not case.startswith('post') or produced):
    if command!='rev-parse' or 'refs/remotes/origin/main^{commit}' in a:
        sys.exit(71)
if command=='diff-tree' and case=='deltaerror': sys.exit(72)
if command=='commit' and case in {'tamperdelta','tamperparents','tampertree'}:
    if case=='tamperdelta':
        pathlib.Path('static/metrics/extra.json').write_text('SYNTHETIC extra')
        subprocess.run(['/usr/bin/git','add','static/metrics/extra.json'],check=True)
    if case=='tampertree':
        pathlib.Path('content/posts/synthetic.md').write_text('SYNTHETIC tampered')
        subprocess.run(['/usr/bin/git','add','content/posts/synthetic.md'],check=True)
    if case=='tamperparents':
        side=subprocess.check_output(['/usr/bin/git','commit-tree','HEAD^{tree}','-p','HEAD','-m','synthetic side'],text=True).strip()
        pathlib.Path('.git/MERGE_HEAD').write_text(side+'\\n')
os.execv('/usr/bin/git',['/usr/bin/git']+a)
'''
PRODUCER = '''#!/usr/bin/python3
import os, pathlib, subprocess, sys
r=pathlib.Path(os.environ['FIXTURE']); repo=r/'repo'
assert pathlib.Path.cwd().is_relative_to(repo)
assert sys.argv[1]!='-c', 'send/inline Python forbidden'
name=pathlib.Path(sys.argv[1]).name
allowed={'run_pipeline.py','generate_health.py','generate_pipeline_status.py','generate_search_index.py','category_distribution.py','update_publish_metrics.py','metrics.py','pipeline_run_summary.py'}
assert name in allowed
if name!='run_pipeline.py' or '--dry-run' in sys.argv: sys.exit(0)
(r/'produced').write_text('synthetic producer boundary')
(repo/'content/posts/synthetic.md').write_bytes(b'SYNTHETIC generated article\\n')
case=os.environ['CASE']
if case in {'postsource','postindex'}:
    (repo/'AGENTS.md').write_bytes(b'SYNTHETIC concurrent protected edit\\n')
    if case=='postindex': subprocess.run(['/usr/bin/git','add','AGENTS.md'],cwd=repo,check=True)
if case=='postadvance':
    subprocess.run(['/usr/bin/git','commit','--allow-empty','-m','synthetic concurrent advance'],cwd=r/'peer',check=True)
    subprocess.run(['/usr/bin/git','push','origin','main'],cwd=r/'peer',check=True)
if case=='postoperation':
    (repo/'.git/CHERRY_PICK_HEAD').write_text(subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=repo,text=True))
if case=='producerfail': sys.exit(19)
'''


SNAPSHOT = """#!/bin/bash
/usr/bin/python3 -I -S -B - <<'PY'
import json,pathlib
p=pathlib.Path('static/metrics/snapshot.json')
n=json.loads(p.read_text())['articlesTotal']+1
p.write_text(json.dumps(dict(articlesTotal=n, articlesPublishedToday=0, lastSuccessfulRun=None, pipelineErrorsToday=0, uptimeSinceRestart=0, generatedAt='2026-09-08T00:00:%02dZ'%n))+'\\n')
PY
"""

class LegacyShell(unittest.TestCase):
    def test_isolation(self):
        script = "import pathlib,socket;\nfor f in [lambda: list(pathlib.Path('/etc').iterdir()), lambda: pathlib.Path('/tmp/legacy-outside-guard').write_text('x'), lambda: socket.socket()]:\n try: f()\n except PermissionError: pass\n else: raise AssertionError('guard failed')\nprint('three guard denials verified')"
        self.assertTrue(Path('/etc').is_dir(), 'existing denied directory required')
        p = run(['/usr/bin/python3', '-I', '-S', '-B', '-c', script], ROOT, guarded=True)
        print(p.stdout.strip())

    def test_wrapper_matrix(self):
        cases = ['current','stale','fetchfail','reffail','statusfail','wrongrepo','branch',
                 'dirtyprotected','untrackedsource','dirtygenerated','postadvance',
                 'postfetch','postref','poststatus','postsource','postindex','pushfail',
                 'addfail','difffail','commitfail','producerfail','legacylock','workerlock','sharedlock']
        operations = ['MERGE_HEAD','rebase-merge','rebase-apply','CHERRY_PICK_HEAD','REVERT_HEAD','sequencer','BISECT_START','BISECT_LOG']
        cases += ['operation-'+s for s in operations] + ['postoperation','tamperdelta','tamperparents','tampertree','deltaerror']
        records = []
        for wrapper in ['auto_publish.sh','auto_publish_copy.sh','firehose_cron.sh']:
            for case in cases:
                with self.subTest(wrapper=wrapper, case=case):
                    r=ROOT/(wrapper+'-'+case); r.mkdir(); repo=r/'repo'; repo.mkdir()
                    (repo/'pipeline/logs').mkdir(parents=True); (repo/'content/posts').mkdir(parents=True)
                    (repo/'scripts').mkdir(); (r/'bin').mkdir()
                    for name in [wrapper,'legacy_publish_git.sh']:
                        (repo/'pipeline'/name).write_bytes((SOURCE/name).read_bytes())
                    (repo/'scripts/daily-snapshot.sh').write_text(SNAPSHOT)
                    (repo/'static/metrics').mkdir(parents=True)
                    (repo/'static/metrics/snapshot.json').write_text('{"articlesTotal":0}\n')
                    (repo/'AGENTS.md').write_bytes(b'SYNTHETIC protected source\n')
                    (repo/'content/posts/existing.md').write_bytes(b'SYNTHETIC existing article\n')
                    (repo/'.gitignore').write_text('pipeline/logs/\npipeline/.pipeline_lock\n')
                    git(repo,'init','-b','main'); git(repo,'config','user.name','Synthetic Fixture')
                    git(repo,'config','user.email','synthetic@example.invalid')
                    git(repo,'add','.'); git(repo,'commit','-m','synthetic fixture')
                    run(['/usr/bin/git','init','--bare','-b','main',str(r/'remote.git')],r)
                    git(repo,'remote','add','origin',str(r/'remote.git')); git(repo,'push','-u','origin','main')
                    run(['/usr/bin/git','clone',str(r/'remote.git'),str(r/'peer')],r)
                    git(r/'peer','config','user.name','Synthetic Fixture'); git(r/'peer','config','user.email','synthetic@example.invalid')
                    for name, text in [('git',GIT_SHIM),('python3',PRODUCER)]:
                        p=r/'bin'/name; p.write_text(text); p.chmod(0o755)
                    env={**ENV,'PATH':str(r/'bin')+':/usr/bin:/bin','FIXTURE':str(r),'CASE':case}
                    operation_bytes=None
                    if case.startswith('operation-'):
                        state=case.removeprefix('operation-'); marker=repo/'.git'/state
                        if state=='MERGE_HEAD':
                            side=git(repo,'commit-tree','HEAD^{tree}','-p','HEAD','-m','synthetic pending merge')
                            git(repo,'merge','--no-ff','--no-commit',side)
                        elif state in {'rebase-merge','rebase-apply','sequencer'}:
                            marker.mkdir(); (marker/'synthetic').write_text('SYNTHETIC operation')
                        else: marker.write_text(git(repo,'rev-parse','HEAD')+'\n')
                        operation_bytes={str(f):f.read_bytes() for f in ([marker] if marker.is_file() else marker.rglob('*')) if f.is_file()}
                        self.assertEqual(git(repo,'status','--porcelain=v1'),'')
                    if case=='stale':
                        git(r/'peer','commit','--allow-empty','-m','synthetic advance'); git(r/'peer','push','origin','main')
                    if case=='branch': git(repo,'switch','-c','not-main')
                    if case=='dirtyprotected': (repo/'AGENTS.md').write_bytes(b'SYNTHETIC owner dirty bytes\n')
                    if case=='untrackedsource': (repo/'pipeline/untracked.py').write_bytes(b'# SYNTHETIC untracked source\n')
                    if case=='dirtygenerated': (repo/'content/posts/pending.md').write_bytes(b'SYNTHETIC pending bytes\n')
                    if case=='legacylock': (repo/'pipeline/.pipeline_lock').write_bytes(b'SYNTHETIC legacy lock\n')
                    lock=None
                    if case in {'workerlock','sharedlock'}:
                        lock=open(repo/'.git'/('staged-monica-worker.lock' if case=='workerlock' else 'legacy-publishing.lock'),'w')
                        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                    before={str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest() for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts}
                    head=git(repo,'rev-parse','HEAD'); remote=git(r/'remote.git','rev-parse','main')
                    p=run(['/bin/bash',str(repo/'pipeline'/wrapper)],repo,env,guarded=True,check=False)
                    (r/'wrapper.log').write_text(p.stdout)
                    if lock: lock.close()
                    self.assertEqual(p.returncode==0, case=='current',p.stdout)
                    pre = case in cases[:10] or case in {'legacylock','workerlock','sharedlock'} or case.startswith('operation-')
                    if operation_bytes:
                        for f,b in operation_bytes.items(): self.assertEqual(Path(f).read_bytes(),b)
                    if case=='postoperation': self.assertEqual((repo/'.git/CHERRY_PICK_HEAD').read_text().strip(),head)
                    self.assertEqual((r/'produced').exists(), not pre or case=='current',p.stdout)
                    for rel, digest in before.items():
                        if rel=='static/metrics/snapshot.json' and (r/'produced').exists(): continue
                        if rel=='AGENTS.md' and case in {'postsource','postindex'}: continue
                        self.assertEqual(hashlib.sha256((repo/rel).read_bytes()).hexdigest(),digest,rel)
                    if (r/'produced').exists() and case!='tampertree':
                        self.assertEqual((repo/'content/posts/synthetic.md').read_bytes(),b'SYNTHETIC generated article\n')
                    if case in {'postsource','postindex'}:
                        self.assertEqual((repo/'AGENTS.md').read_bytes(),b'SYNTHETIC concurrent protected edit\n')
                    if case=='postindex': self.assertEqual(git(repo,'diff','--cached','--name-only'),'AGENTS.md')
                    if case=='current':
                        self.assertEqual(git(repo,'rev-parse','HEAD'),git(r/'remote.git','rev-parse','main'))
                        self.assertEqual(git(repo,'status','--porcelain=v1'),'')
                        if wrapper!='firehose_cron.sh':
                            self.assertEqual(json.loads((repo/'static/metrics/snapshot.json').read_text())['articlesTotal'],1)
                        again=run(['/bin/bash',str(repo/'pipeline'/wrapper)],repo,env,guarded=True,check=False)
                        self.assertEqual(again.returncode,0,again.stdout)
                        self.assertEqual(git(repo,'status','--porcelain=v1'),'')
                        self.assertEqual(git(repo,'rev-parse','HEAD'),git(r/'remote.git','rev-parse','main'))
                        if wrapper!='firehose_cron.sh':
                            self.assertEqual(json.loads((repo/'static/metrics/snapshot.json').read_text())['articlesTotal'],2)
                    elif case not in {'pushfail','tamperdelta','tamperparents','tampertree','deltaerror'}: self.assertEqual(git(repo,'rev-parse','HEAD'),head)
                    if case not in {'current','postadvance'}: self.assertEqual(git(r/'remote.git','rev-parse','main'),remote)
                    records.append({'wrapper':wrapper,'case':case,'rc':p.returncode,'preservation':'PASS','before_sha256':before})
                    print('PASS',wrapper,case,flush=True)
                    (ROOT/'results.json').write_text(json.dumps(records,indent=2))
        self.assertEqual(len(records),len(cases)*3)


if __name__=='__main__':
    print('SYNTHETIC guarded scratch:', ROOT, flush=True)
    unittest.main(verbosity=2)

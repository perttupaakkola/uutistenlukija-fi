"""Run only the repaired env-loader test with enforced file/network isolation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_scratch_owner = tempfile.TemporaryDirectory(prefix='uutis-env-test-')
SCRATCH = Path(_scratch_owner.name).resolve()
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'pipeline'), str(ROOT)]
tempfile.tempdir = str(SCRATCH)
DENIALS = []
ENV_OPENS = []

def guard(event, args):
    def deny(reason):
        DENIALS.append([event, reason])
        raise PermissionError(reason)
    def resolve(value, dir_fd=None):
        if isinstance(value, int):
            return Path(os.readlink('/proc/self/fd/'+str(value))).resolve()
        path = Path(os.fsdecode(value))
        if not path.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
            path = Path(os.readlink('/proc/self/fd/'+str(dir_fd))) / path
        return path.resolve()
    def writable(value, dir_fd=None):
        path = resolve(value, dir_fd)
        if not path.is_relative_to(SCRATCH):
            deny('write outside isolated scratch')
    if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        deny('network/process forbidden')
    if event == 'open':
        value, mode, flags = args
        path = resolve(value)
        if '.secrets' in path.parts or '.hermes' in path.parts:
            deny('private read forbidden')
        if path.name == '.env':
            if not path.is_relative_to(SCRATCH) or path.parent.name != 'synthetic-project':
                deny('non-fixture env access')
            ENV_OPENS.append({'fixture': path.parent.name, 'mode': mode})
        if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            writable(value)
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
        index = {'os.mkdir':2, 'os.chmod':2, 'os.utime':3}.get(event, 1)
        writable(args[0], args[index] if len(args)>index else None)
    elif event in ('os.rename', 'os.link'):
        writable(args[0]); writable(args[1])
    elif event == 'os.symlink':
        deny('symlinks forbidden')

sys.addaudithook(guard)
before = dict(os.environ)
suite = unittest.defaultTestLoader.loadTestsFromName('test_staged_publish.StagedPublishMetricsTests.test_enrich_images_loads_project_env_for_staged_publish')
result = unittest.TextTestRunner(verbosity=2).run(suite)
restored = dict(os.environ) == before
print('ENV_ISOLATION', json.dumps({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'denials': DENIALS, 'fixture_env_opens': ENV_OPENS, 'process_environment_restored': restored}))
sys.exit(not result.wasSuccessful() or bool(DENIALS) or not restored)

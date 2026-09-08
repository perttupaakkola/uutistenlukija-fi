"""Bounded image semantic tests under the existing env-test I/O guard pattern.

Run: env -i PATH=/usr/bin:/bin python3 -I -B pipeline/run_image_semantics_tests.py
No project imports precede the audit hook. Runtime/credential reads, writes
outside owned scratch, network and subprocesses fail the run even if caught.
Only the explicitly selected test modules below are admitted, never discovery.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
owner = tempfile.TemporaryDirectory(prefix='uutis-image-semantics-')
SCRATCH = Path(owner.name).resolve()
os.environ.clear()
os.environ.update({'HOME': str(SCRATCH), 'TMPDIR': str(SCRATCH)})
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'pipeline'), str(ROOT)]
tempfile.tempdir = str(SCRATCH)
DENIALS = []


def guard(event, args):
    def deny(reason):
        DENIALS.append([event, reason])
        raise PermissionError(reason)

    def resolve(value, dir_fd=None):
        if isinstance(value, int):
            return Path(os.readlink('/proc/self/fd/' + str(value))).resolve()
        path = Path(os.fsdecode(value))
        if not path.is_absolute() and isinstance(dir_fd, int) and dir_fd >= 0:
            path = Path(os.readlink('/proc/self/fd/' + str(dir_fd))) / path
        return path.resolve()

    def writable(value, dir_fd=None):
        if not resolve(value, dir_fd).is_relative_to(SCRATCH):
            deny('write outside isolated scratch')

    if event.startswith('socket.') or event in (
        'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork', 'pty.spawn',
    ):
        deny('network/process forbidden')
    if event == 'open':
        value, mode, flags = args
        path = resolve(value)
        if path.name.startswith('.env') or any(part in path.parts for part in (
            '.secrets', '.hermes', '.openclaw', '.ssh', '.aws', '.config',
        )) or (path.is_relative_to('/proc') and path.name == 'environ'):
            deny('private read forbidden')
        if (mode and any(c in mode for c in 'wax+')) or flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            writable(value)
        elif path.is_relative_to(ROOT) and path.suffix not in ('.py', '.pyc'):
            deny('project runtime/data read forbidden')
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime'):
        index = {'os.mkdir': 2, 'os.chmod': 2, 'os.utime': 3}.get(event, 1)
        writable(args[0], args[index] if len(args) > index else None)
    elif event in ('os.rename', 'os.link'):
        writable(args[0], args[2] if len(args) > 2 else None)
        writable(args[1], args[3] if len(args) > 3 else None)
    elif event == 'os.symlink':
        deny('symlinks forbidden')


sys.addaudithook(guard)
# Prove historical unsafe env access and process/network/write paths are denied
# before any action occurs; separate these expected self-checks from test I/O.
for event, args in (
    ('open', (str(ROOT / '.env'), 'r', 0)),
    ('open', (str(ROOT / '.env'), 'w', os.O_WRONLY)),
    ('open', (str(ROOT / 'pipeline/cache/health.json'), 'w', os.O_WRONLY)),
    ('socket.connect', (None, ('127.0.0.1', 9))),
    ('subprocess.Popen', ('forbidden', [], None, None)),
):
    try:
        sys.audit(event, *args)
    except PermissionError:
        pass
    else:
        raise AssertionError('I/O guard self-test failed: ' + event)
self_checks = len(DENIALS)
DENIALS.clear()

allowed = {
    'test_image_semantics', 'test_image_pipeline_grounding',
    'test_audit_image_flow_independent', 'test_generation_policy_order',
    'test_image_query_tokens', 'test_image_provider_result',
}
names = sys.argv[1:] or ['test_image_semantics']
if not all(name.split('.')[0] in allowed for name in names):
    raise ValueError('test module outside bounded image allowlist')
# These two old regressions read production packet/article paths; the independent
# eight-packet replay is run separately from immutable supplied pure inputs.
excluded = {
    'test_real_finance_packet_audit_flags_unsupported_intent_and_candidate',
    'test_real_conflict_packet_rejects_incidental_television_as_visual_truth',
}


excluded_tests = []


def selected(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from selected(item)
        elif item.id().split('.')[-1] not in excluded:
            yield item
        else:
            excluded_tests.append(item.id())


before = dict(os.environ)
suite = unittest.TestSuite(selected(unittest.defaultTestLoader.loadTestsFromNames(names)))
# Provider regressions use synthetic candidates but consult the real duplicate
# state loader. Point its storage boundary at an empty owned fixture, not the
# repository cache/posts. Do not mock semantic scoring or weaken the I/O hook.
import image_state
with patch.object(image_state, '_STATE_FILE', str(SCRATCH / 'used_images.json')), \
     patch.object(image_state, 'POSTS_DIR', str(SCRATCH / 'posts')):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
restored = dict(os.environ) == before
print('IMAGE_SEMANTICS_ISOLATION', json.dumps({
    'tests': result.testsRun, 'failures': len(result.failures),
    'errors': len(result.errors), 'skips': len(result.skipped),
    'guard_self_checks': self_checks, 'denials': DENIALS,
    'excluded_production_fixture_tests': excluded_tests,
    'environment_restored': restored, 'scratch': str(SCRATCH),
}))
owner.cleanup()
sys.exit(not result.wasSuccessful() or bool(DENIALS) or not restored)

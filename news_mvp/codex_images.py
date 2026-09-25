"""One bounded, OAuth-authenticated Codex image request, without publisher tools.

The CLI reply is not evidence: accept only a fresh decoded raster in the native
generated-images directory belonging to the successful ephemeral invocation.
Cache exact bytes across review outages. No paid-provider fallback occurs here.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone

MODEL = 'gpt-6-astra'
EFFORT = 'xhigh'
IMAGE_MODEL = 'codex-oauth:gpt-image-2'


def _binary():
    configured = os.environ.get('UUTIS_CODEX_BINARY')
    value = configured or shutil.which('codex')
    if not value:
        value = str(Path.home() / '.local/share/lean-support/node/lib/node_modules/@openai/codex/'
                    'node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex')
    path = Path(value)
    if not path.is_file() or not os.access(path, os.X_OK):
        from .imagery import GenerationError
        raise GenerationError('OAuth Codex CLI unavailable')
    return str(path.resolve())


def _environment():
    # Auth is read by Codex itself from its existing ChatGPT credential store.
    # Never read/copy credentials, inherit API keys, or expose production env.
    allowed = {'HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR',
               'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR', 'CODEX_HOME'}
    return {k: v for k, v in os.environ.items() if k in allowed}


def _request_path(subject, prompt, state_dir):
    key = hashlib.sha256(json.dumps([IMAGE_MODEL, subject, prompt], ensure_ascii=False).encode()).hexdigest()
    return Path(state_dir) / 'codex-image-requests' / key


def reject_codex(subject, prompt, state_dir):
    from .site import atomic_write
    path = _request_path(subject, prompt, state_dir) / 'request.json'
    if path.exists():
        value = json.loads(path.read_text()); value['rejected'] = True
        atomic_write(path, json.dumps(value, sort_keys=True))


def _image_output(stdout, generated_root, started_at, finished_at):
    from .imagery import GenerationError, verify
    try:
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        starts = [e['thread_id'] for e in events if e.get('type') == 'thread.started']
        if len(starts) != 1 or not re.fullmatch(r'[a-f0-9-]{36}', starts[0]):
            raise ValueError('No unique invocation identity')
        if (sum(e.get('type') == 'turn.completed' for e in events) != 1 or
                any(e.get('type') in ('error', 'turn.failed') for e in events)):
            raise ValueError('Invocation incomplete')
        forbidden = {'command_execution', 'file_change', 'mcp_tool_call'}
        if any(e.get('item', {}).get('type') in forbidden for e in events):
            raise ValueError('Unexpected tool use')
        directory = Path(generated_root) / starts[0]
        if directory.is_symlink():
            raise ValueError('Symlink output directory')
        files = [p for p in directory.iterdir() if p.is_file()]
        if len(files) != 1:
            raise ValueError('No unique actual image')
        path = files[0]
        if (path.is_symlink() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp') or
                not started_at <= path.stat().st_mtime <= finished_at + 1 or
                not 1000 <= path.stat().st_size <= 20_000_000):
            raise ValueError('Invalid or stale raster')
        raw = path.read_bytes()
        facts = verify(raw, expect_ratio=1.5)
        return raw, {'ephemeral_invocation_id': starts[0], 'original_path': str(path),
                     'pixels': facts, 'native_image_sha256': hashlib.sha256(raw).hexdigest()}
    except Exception as error:
        raise GenerationError('OAuth Codex returned no unique fresh verified image') from error


def _worker_alive(saved):
    try:
        stat = Path('/proc') / str(int(saved['worker_pid'])) / 'stat'
        return stat.read_text().split(') ', 1)[1].split()[19] == saved['worker_start_ticks']
    except (OSError, KeyError, ValueError, IndexError):
        return False


def _save_result(root, receipt, raw, actual, event_text):
    from .site import atomic_write
    attempt = str(receipt['attempt'])
    receipt.update(actual, state='success', raw_file=attempt + '/image.bin',
                   raw_sha256=hashlib.sha256(raw).hexdigest(),
                   events_sha256=hashlib.sha256(event_text.encode()).hexdigest(),
                   completed_at=datetime.now(timezone.utc).isoformat())
    atomic_write(root / receipt['raw_file'], raw)
    atomic_write(root / attempt / 'receipt.json', json.dumps(receipt, sort_keys=True))
    atomic_write(root / 'request.json', json.dumps(receipt, sort_keys=True))


def generate_codex(subject, prompt, state_dir, timeout=240):
    from .imagery import GenerationError
    try:
        return _generate_codex(subject, prompt, state_dir, timeout)
    except GenerationError:
        raise
    except Exception:
        raise GenerationError('OAuth image route unavailable; publication remains retryable') from None


def _generate_codex(subject, prompt, state_dir, timeout=240):
    from .imagery import GenerationError
    from .site import atomic_write
    if state_dir is None:
        raise GenerationError('OAuth generation requires durable request state')
    root = _request_path(subject, prompt, state_dir); root.mkdir(parents=True, exist_ok=True)
    with (root / 'request.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GenerationError('OAuth image request already active') from None
        path = root / 'request.json'
        saved = json.loads(path.read_text()) if path.exists() else {}
        if saved.get('state') == 'success' and not saved.get('rejected'):
            raw = (root / saved['raw_file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != saved['raw_sha256']:
                raise GenerationError('Cached OAuth image bytes changed')
            return raw, prompt, IMAGE_MODEL
        env = _environment()
        codex_home = Path(env.get('CODEX_HOME', str(Path.home() / '.codex')))
        # Reconcile a completed child after a parent interruption. An active or
        # uncertain child is never duplicated. Expired failures retain evidence
        # and back off before a genuinely new candidate request.
        if saved.get('state') == 'running':
            if _worker_alive(saved) or 'deadline_epoch' not in saved:
                raise GenerationError('OAuth image request needs interrupted-result reconciliation')
            try:
                event_text = (root / str(saved['attempt']) / 'events.jsonl').read_text()
                raw, actual = _image_output(event_text, codex_home / 'generated_images',
                                           saved['submitted_epoch'], time.time())
                _save_result(root, saved, raw, actual, event_text)
                return raw, prompt, IMAGE_MODEL
            except (OSError, GenerationError):
                if time.time() > saved['deadline_epoch'] + 30:
                    saved.update(state='failed', error_type='InterruptedInvocation', retry_after=time.time() + 900)
                    atomic_write(root / str(saved['attempt']) / 'receipt.json', json.dumps(saved, sort_keys=True))
                    atomic_write(path, json.dumps(saved, sort_keys=True))
            raise GenerationError('OAuth image request needs interrupted-result reconciliation')
        if saved.get('state') == 'failed' and time.time() < saved.get('retry_after', 0):
            raise GenerationError('OAuth image route temporarily unavailable; retry later')
        binary = _binary()
        auth = subprocess.run([binary, 'login', 'status'], env=env, capture_output=True,
                              text=True, timeout=15)
        auth_text = auth.stdout + auth.stderr
        if auth.returncode or 'ChatGPT' not in auth_text or 'API key' in auth_text:
            raise GenerationError('OAuth image route requires existing ChatGPT login')
        attempt = int(saved.get('attempt', 0)) + 1
        attempt_dir = root / str(attempt); attempt_dir.mkdir(exist_ok=False)
        started = time.time()
        receipt = {'provider': 'codex-oauth', 'model_documented': 'gpt-image-2',
                   'model_identity_returned': False, 'orchestrator_model': MODEL,
                   'reasoning_effort': EFFORT, 'state': 'running', 'attempt': attempt,
                   'auth_mode': 'ChatGPT', 'api_key_environment_passed': False,
                   'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                   'submitted_epoch': started, 'deadline_epoch': started + timeout,
                   'submitted_at': datetime.now(timezone.utc).isoformat()}
        atomic_write(path, json.dumps(receipt, sort_keys=True))
        instruction = (
            '$imagegen Generate exactly one image using only the built-in image generation tool. '
            'This is an isolated image-only request; no implementation, publishing, shell, other agents, '
            'API scripts, or third-party providers. Do not inspect repositories or production state. '
            'If the built-in tool is unavailable, report BUILTIN_IMAGE_TOOL_UNAVAILABLE and stop. '
            'Return the actual output path. The following is the bounded editorial image specification:\n'
            + prompt)
        atomic_write(attempt_dir / 'prompt.txt', instruction)
        try:
            with tempfile.TemporaryDirectory(prefix='uutis-codex-image-') as workspace:
                command = [binary, 'exec', '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
                    '--json', '--sandbox', 'read-only', '--disable', 'shell_tool', '--disable', 'apps',
                    '--disable', 'multi_agent', '--enable', 'image_generation', '-m', MODEL,
                    '-c', 'model_reasoning_effort="' + EFFORT + '"', '-c', 'approval_policy="never"',
                    '-c', 'web_search="disabled"', '-C', workspace, '-']
                with (attempt_dir / 'events.jsonl').open('w') as stdout, (attempt_dir / 'stderr.txt').open('w') as stderr:
                    proc = subprocess.Popen(command, env=env, stdin=subprocess.PIPE,
                                            stdout=stdout, stderr=stderr, text=True, start_new_session=True)
                    try:
                        receipt['worker_pid'] = proc.pid
                        receipt['worker_start_ticks'] = (Path('/proc') / str(proc.pid) / 'stat').read_text().split(') ', 1)[1].split()[19]
                        atomic_write(path, json.dumps(receipt, sort_keys=True))
                        proc.communicate(instruction, timeout=timeout)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL); proc.communicate()
                        raise GenerationError('OAuth image request timed out') from None
                    except Exception:
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGKILL); proc.communicate()
                        raise
                if proc.returncode:
                    raise GenerationError('OAuth image invocation failed')
            event_text = (attempt_dir / 'events.jsonl').read_text()
            raw, actual = _image_output(event_text, codex_home / 'generated_images', started, time.time())
            _save_result(root, receipt, raw, actual, event_text)
            return raw, prompt, IMAGE_MODEL
        except Exception as error:
            receipt.update(state='failed', error_type=type(error).__name__, retry_after=time.time() + 900,
                           finished_at=datetime.now(timezone.utc).isoformat())
            atomic_write(attempt_dir / 'receipt.json', json.dumps(receipt, sort_keys=True))
            atomic_write(path, json.dumps(receipt, sort_keys=True))
            raise GenerationError('OAuth image unavailable; publication remains retryable') from None

"""Explicitly selected, already configured private image/vision routes.

Credentials remain in their existing host-only files. No authenticated request
may redirect, and only public article text/pixels reach these providers.
"""
import base64
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

KIE_MODEL = 'nano-banana-2'
GOOGLE_IMAGE_MODEL = 'gemini-3.1-flash-image'
VISION_MODEL = 'gemini-2.5-flash'
GOOGLE_ENV = Path.home() / '.hermes/.env'
REQUEST_EVENTS = ContextVar('image_provider_request_events', default=None)
CANDIDATE_EVENTS = ContextVar('image_provider_candidate_events', default=None)


def request_event(host, status=None, error=None):
    events = REQUEST_EVENTS.get()
    if events is not None and len(events) < 300:
        events.append({'host': host, 'http_status': status, 'error_type': error})


def candidate_event(stock, image_sha256, outcome):
    """Record bounded identity/gate outcomes, never URLs, keys or provider bodies."""
    events = CANDIDATE_EVENTS.get()
    if events is None or len(events) >= 100:
        return
    provenance = stock.get('stock_provenance') or {}
    provider = provenance.get('provider')
    identity = str(provenance.get('photo_id', ''))
    if provider not in {'pexels', 'unsplash', 'wikimedia', 'google', 'statfi', 'helsinki'}:
        return
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', identity):
        return
    if not re.fullmatch(r'[0-9a-f]{64}', image_sha256 or ''):
        return
    if outcome not in {'duplicate_refused', 'pixel_refused', 'review_unavailable', 'accepted'}:
        return
    event = {'provider':provider, 'photo_id':identity,
             'image_sha256':image_sha256, 'outcome':outcome}
    if event not in events:
        events.append(event)


@contextmanager
def image_attempt(draft, state_dir):
    """Record actual HTTP outcomes without queries, URLs, credentials or bodies."""
    from .site import atomic_write
    events = []; token = REQUEST_EVENTS.set(events)
    candidates = []; candidate_token = CANDIDATE_EVENTS.set(candidates)
    article_hash = hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    receipt = {'started_at': datetime.now(timezone.utc).isoformat(), 'input_draft_sha256': article_hash,
               'requests': events, 'candidates':candidates, 'outcome': 'image_pending'}
    try:
        yield receipt
    finally:
        try:
            receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
            path = Path(state_dir) / 'image-provider-attempts' / article_hash / (str(time.time_ns()) + '.json')
            atomic_write(path, json.dumps(receipt, sort_keys=True))
        finally:
            REQUEST_EVENTS.reset(token)
            CANDIDATE_EVENTS.reset(candidate_token)


def _json(url, host, headers, body=None, timeout=60):
    from .imagery import _open, GenerationError
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={**headers, 'Content-Type': 'application/json'})
    try:
        with _open(request, host, timeout=timeout, credentialed=True) as response:
            return json.load(response)
    except Exception as error:
        code = getattr(error, 'code', None)
        raise GenerationError(f'{host} request unavailable: HTTP {code}' if isinstance(code, int)
                              else f'{host} request unavailable: {type(error).__name__}') from None


def google_vision(raw, instruction, max_tokens=1200):
    from .imagery import _pixels, _credential_value, _read_env_value, GenerationError
    key = _credential_value(('GOOGLE_API_KEY', 'GEMINI_API_KEY')) or _read_env_value(GOOGLE_ENV, 'GOOGLE_API_KEY')
    if not key:
        raise GenerationError('Configured Google vision credential unavailable')
    raster = _pixels(raw); raster.thumbnail((1024, 1024))
    buffer = io.BytesIO(); raster.save(buffer, format='JPEG', quality=90)
    body = {'contents': [{'role': 'user', 'parts': [
        {'text': instruction}, {'inline_data': {'mime_type': 'image/jpeg',
            'data': base64.b64encode(buffer.getvalue()).decode('ascii')}}]}],
        'generationConfig': {'temperature': 0, 'maxOutputTokens': max_tokens,
            'responseMimeType': 'application/json', 'thinkingConfig': {'thinkingBudget': 0}}}
    result = _json('https://generativelanguage.googleapis.com/v1beta/models/' + VISION_MODEL + ':generateContent',
                   'generativelanguage.googleapis.com', {'x-goog-api-key': key}, body, timeout=90)
    try:
        return json.loads(''.join(part.get('text', '') for part in result['candidates'][0]['content']['parts']))
    except (KeyError, IndexError, TypeError, ValueError):
        raise GenerationError('Google vision returned no valid JSON review') from None


CODEX_VISION_HOST = 'codex-oauth-vision'
CODEX_VISION_MODEL = 'gpt-6.1-sol'
CODEX_VISION_EFFORT = 'low'
CODEX_VISION_TIMEOUT = 120
# Per-process breaker: a publisher tick is one process, so this never outlives it.
_CODEX_VISION_STATE = {'down_until': 0.0, 'failures': 0}


def _codex_vision_model():
    value = os.environ.get('UUTIS_CODEX_VISION_MODEL', CODEX_VISION_MODEL)
    return value if re.fullmatch(r'[a-z0-9.-]{3,40}', value) else CODEX_VISION_MODEL


def _extract_json_object(text):
    text = (text or '').strip()
    fenced = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find('{'), text.rfind('}')
        if start < 0 or end <= start:
            raise ValueError('No JSON object') from None
        value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError('Vision reply is not a JSON object')
    return value


def codex_vision(raw, instruction, max_tokens=1200, timeout=CODEX_VISION_TIMEOUT):
    """One isolated ChatGPT-OAuth Codex vision call returning the google_vision JSON contract.

    Only a freshly re-encoded, metadata-free JPEG named ``image.jpg`` in a private temporary
    directory is attached; no filename, URL or EXIF reaches the model. No API-key environment
    is inherited, the sandbox is read-only and shell/apps/agents/web search are disabled.
    """
    from .imagery import _pixels, GenerationError
    from .codex_images import _binary, _environment
    raster = _pixels(raw); raster.thumbnail((1024, 1024))
    buffer = io.BytesIO(); raster.save(buffer, format='JPEG', quality=90)
    prompt = (instruction + '\n\nReply with exactly one JSON object and nothing else. '
              'Do not use tools; inspect only the attached image.')
    model = _codex_vision_model()
    try:
        binary = _binary()
        with tempfile.TemporaryDirectory(prefix='uutis-codex-vision-') as workspace:
            image = Path(workspace) / 'image.jpg'
            image.write_bytes(buffer.getvalue())
            last = Path(workspace) / 'reply.txt'
            command = [binary, 'exec', '--ephemeral', '--ignore-user-config', '--ignore-rules',
                '--skip-git-repo-check', '--json', '--sandbox', 'read-only',
                '--disable', 'shell_tool', '--disable', 'apps', '--disable', 'multi_agent',
                '-m', model, '-c', 'model_reasoning_effort="' + CODEX_VISION_EFFORT + '"',
                '-c', 'approval_policy="never"', '-c', 'web_search="disabled"',
                '-C', workspace, '-i', str(image), '-o', str(last), '-']
            proc = subprocess.Popen(command, env=_environment(), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            try:
                stdout, stderr = proc.communicate(prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL); proc.communicate()
                raise GenerationError('Codex vision timed out') from None
            limited = bool(re.search(r'usage limit|rate limit|too many requests|quota',
                                     (stdout or '') + (stderr or ''), re.I))
            if proc.returncode:
                raise GenerationError('Codex vision limit reached' if limited
                                      else 'Codex vision invocation failed')
            events = [json.loads(line) for line in stdout.splitlines() if line.strip().startswith('{')]
            if (sum(e.get('type') == 'turn.completed' for e in events) != 1 or
                    any(e.get('type') in ('error', 'turn.failed') for e in events)):
                raise GenerationError('Codex vision limit reached' if limited
                                      else 'Codex vision turn incomplete')
            if any((e.get('item') or {}).get('type') in
                   ('command_execution', 'file_change', 'mcp_tool_call', 'web_search') for e in events):
                raise GenerationError('Codex vision attempted tool use')
            reply = last.read_text() if last.exists() else ''
        try:
            return _extract_json_object(reply)
        except ValueError:
            raise GenerationError('Codex vision returned no valid JSON review') from None
    except GenerationError:
        raise
    except Exception as error:
        raise GenerationError('Codex vision unavailable: ' + type(error).__name__) from None


def vision(raw, instruction, max_tokens=1200, provider=None):
    """Configured vision route. Returns ``(json_value, model_label)``.

    ``codex-oauth`` uses the ChatGPT subscription; any Codex failure (including usage
    limits) falls back to Google for that call and is recorded as a bounded request event.
    """
    from .imagery import GenerationError
    provider = provider or os.environ.get('UUTIS_VISION_PROVIDER', 'openai')
    if provider == 'codex-oauth':
        state = _CODEX_VISION_STATE
        if time.time() >= state['down_until']:
            try:
                value = codex_vision(raw, instruction, max_tokens)
                state['failures'] = 0
                request_event(CODEX_VISION_HOST, 200)
                return value, 'codex-oauth:' + _codex_vision_model()
            except GenerationError as error:
                state['failures'] += 1
                limited = 'limit' in str(error)
                if limited or state['failures'] >= 3:
                    state['down_until'] = time.time() + (1800 if limited else 600)
                request_event(CODEX_VISION_HOST, None,
                              'UsageLimitFallback' if limited else 'CodexFallback')
        else:
            request_event(CODEX_VISION_HOST, None, 'BreakerFallback')
        return google_vision(raw, instruction, max_tokens), 'google:' + VISION_MODEL
    if provider == 'google':
        return google_vision(raw, instruction, max_tokens), 'google:' + VISION_MODEL
    raise GenerationError('Configured vision provider has no shared route')


def _request_path(subject, prompt, state_dir, model=KIE_MODEL):
    key = hashlib.sha256(json.dumps([model, subject, prompt], ensure_ascii=False).encode()).hexdigest()
    return Path(state_dir) / 'image-provider-requests' / (key + '.json')


def reject_kie(subject, prompt, state_dir):
    """Retain rejected task evidence; a retry must request different pixels."""
    from .site import atomic_write
    path = _request_path(subject, prompt, state_dir)
    if path.exists():
        receipt = json.loads(path.read_text()); receipt['rejected'] = True
        atomic_write(path, json.dumps(receipt, sort_keys=True))


def reject_google(subject, prompt, state_dir):
    from .site import atomic_write
    path = _request_path(subject, prompt, state_dir, GOOGLE_IMAGE_MODEL)
    if path.exists():
        receipt = json.loads(path.read_text()); receipt['rejected'] = True
        atomic_write(path, json.dumps(receipt, sort_keys=True))


def generate_google(subject, prompt, state_dir):
    """Cache exact synchronous results before a separate pixel/editorial review."""
    from .imagery import _credential_value, _read_env_value, GenerationError
    from .site import atomic_write
    if state_dir is None:
        raise GenerationError('Google generation requires durable request state')
    path = _request_path(subject, prompt, state_dir, GOOGLE_IMAGE_MODEL)
    saved = json.loads(path.read_text()) if path.exists() else None
    if saved and not saved.get('rejected'):
        cache = path.parent / (saved['raw_sha256'] + '.bin')
        if cache.exists() and hashlib.sha256(cache.read_bytes()).hexdigest() == saved['raw_sha256']:
            return cache.read_bytes(), prompt, 'google:' + GOOGLE_IMAGE_MODEL
    key = _credential_value(('GOOGLE_API_KEY', 'GEMINI_API_KEY')) or _read_env_value(GOOGLE_ENV, 'GOOGLE_API_KEY')
    if not key:
        raise GenerationError('Configured Google image credential unavailable')
    started = datetime.now(timezone.utc).isoformat()
    value = _json('https://generativelanguage.googleapis.com/v1beta/models/' + GOOGLE_IMAGE_MODEL + ':generateContent',
        'generativelanguage.googleapis.com', {'x-goog-api-key': key},
        {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
         'generationConfig': {'responseModalities': ['TEXT', 'IMAGE'],
             'imageConfig': {'aspectRatio': '3:2', 'imageSize': '1K'}}}, timeout=240)
    try:
        images = [p['inlineData'] for c in value['candidates'] for p in c['content']['parts']
                  if 'inlineData' in p and not p.get('thought')]
        if len(images) != 1 or images[0]['mimeType'] not in ('image/png', 'image/jpeg', 'image/webp'):
            raise ValueError('Expected one image')
        raw = base64.b64decode(images[0]['data'], validate=True)
        if not raw:
            raise ValueError('Empty image')
    except (KeyError, TypeError, ValueError):
        raise GenerationError('Google returned no unique valid image') from None
    sha = hashlib.sha256(raw).hexdigest()
    receipt = {'provider': 'google', 'model': GOOGLE_IMAGE_MODEL, 'state': 'success',
        'submitted_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
        'raw_sha256': sha, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()}
    atomic_write(path.parent / (sha + '.bin'), raw)
    atomic_write(path.parent / (sha + '.receipt.json'), json.dumps(receipt, sort_keys=True))
    atomic_write(path, json.dumps(receipt, sort_keys=True))
    return raw, prompt, 'google:' + GOOGLE_IMAGE_MODEL


def generate_kie(subject, prompt, state_dir, timeout=240):
    from .imagery import provider_key, _get_external_bytes, GenerationError
    from .site import atomic_write
    if state_dir is None:
        raise GenerationError('KIE generation requires durable request state')
    key = provider_key('kie')
    if not key:
        raise GenerationError('Configured KIE credential unavailable')
    headers = {'Authorization': 'Bearer ' + key}
    path = _request_path(subject, prompt, state_dir)
    saved = json.loads(path.read_text()) if path.exists() else None
    if saved and not saved.get('rejected') and saved.get('state') != 'fail':
        task = saved['task_id']
    else:
        result = _json('https://api.kie.ai/api/v1/jobs/createTask', 'api.kie.ai', headers,
            {'model': KIE_MODEL, 'input': {'prompt': prompt, 'aspect_ratio': '3:2',
                'resolution': '1K', 'output_format': 'png', 'image_input': []}})
        if result.get('code') != 200:
            code = result.get('code') if type(result.get('code')) is int else 'unspecified'
            raise GenerationError('KIE generation refused: code ' + str(code))
        task = (result.get('data') or {}).get('taskId')
        if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', task):
            raise GenerationError('KIE returned no valid task identity')
        saved = {'provider': 'kie', 'model': KIE_MODEL, 'task_id': task, 'state': 'waiting',
                 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                 'submitted_at': datetime.now(timezone.utc).isoformat()}
        atomic_write(path, json.dumps(saved, sort_keys=True))
    cache = path.parent / (task + '.bin')
    if cache.exists() and saved.get('raw_sha256') == hashlib.sha256(cache.read_bytes()).hexdigest():
        return cache.read_bytes(), prompt, 'kie:' + KIE_MODEL
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _json('https://api.kie.ai/api/v1/jobs/recordInfo?' + urllib.parse.urlencode({'taskId': task}),
                       'api.kie.ai', headers)
        value = result.get('data') or {}
        if result.get('code') != 200 or value.get('taskId') != task or value.get('model') != KIE_MODEL:
            raise GenerationError('KIE task identity or status response mismatch')
        saved['state'] = value.get('state')
        atomic_write(path, json.dumps(saved, sort_keys=True))
        if saved['state'] == 'fail':
            raise GenerationError('KIE generation task failed')
        if saved['state'] == 'success':
            try:
                urls = json.loads(value['resultJson'])['resultUrls']
                if not isinstance(urls, list) or len(urls) != 1:
                    raise ValueError('Expected one result')
                raw = _get_external_bytes(urls[0])
                if not raw:
                    raise ValueError('No image')
            except (KeyError, TypeError, ValueError):
                raise GenerationError('KIE returned no downloadable image') from None
            saved['raw_sha256'] = hashlib.sha256(raw).hexdigest()
            saved['completed_at'] = datetime.now(timezone.utc).isoformat()
            atomic_write(cache, raw)
            atomic_write(path, json.dumps(saved, sort_keys=True))
            atomic_write(path.parent / (task + '.receipt.json'), json.dumps(saved, sort_keys=True))
            return raw, prompt, 'kie:' + KIE_MODEL
        if saved['state'] not in ('waiting', 'queuing', 'generating'):
            raise GenerationError('Unknown KIE task state')
        time.sleep(3)
    raise GenerationError('KIE task pending; retry resumes the existing request')

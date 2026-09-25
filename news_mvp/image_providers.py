"""Explicitly selected, already configured private image/vision routes.

Credentials remain in their existing host-only files. No authenticated request
may redirect, and only public article text/pixels reach these providers.
"""
import base64
import hashlib
import io
import json
import re
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


def request_event(host, status=None, error=None):
    events = REQUEST_EVENTS.get()
    if events is not None and len(events) < 300:
        events.append({'host': host, 'http_status': status, 'error_type': error})


@contextmanager
def image_attempt(draft, state_dir):
    """Record actual HTTP outcomes without queries, URLs, credentials or bodies."""
    from .site import atomic_write
    events = []; token = REQUEST_EVENTS.set(events)
    article_hash = hashlib.sha256(json.dumps(draft, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    receipt = {'started_at': datetime.now(timezone.utc).isoformat(), 'input_draft_sha256': article_hash,
               'requests': events, 'outcome': 'image_pending'}
    try:
        yield receipt
    finally:
        try:
            receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
            path = Path(state_dir) / 'image-provider-attempts' / article_hash / (str(time.time_ns()) + '.json')
            atomic_write(path, json.dumps(receipt, sort_keys=True))
        finally:
            REQUEST_EVENTS.reset(token)


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

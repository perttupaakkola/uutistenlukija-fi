"""IndexNow submission: tell participating search engines about a fresh article.

Best-effort by design: the site must never fail a publish because a search-engine ping
failed. The key file is served from the site root, which is what proves host ownership
to the endpoint.

The key is not a secret - it is published at /<key>.txt by definition - so it lives
here as a constant rather than in configuration.
"""
import json
import urllib.request

INDEXNOW_KEY = '0bce47347326f83e8507a46c6b0c3bdb'
ENDPOINT = 'https://api.indexnow.org/indexnow'
HOST = 'uutistenlukija.fi'


def key_name():
    return INDEXNOW_KEY + '.txt'


def ping(urls, timeout=15, result_callback=None):
    """Best-effort submission; optional redacted receipt never affects the bool result."""
    from datetime import datetime, timezone
    import urllib.error

    urls = [u for u in urls if isinstance(u, str) and u.startswith('https://' + HOST + '/')]
    status = None
    result_class = 'skipped'
    error_class = None
    success = False
    if urls:
        body = json.dumps({'host': HOST, 'key': INDEXNOW_KEY, 'urlList': urls}).encode()
        request = urllib.request.Request(
            ENDPOINT, data=body, headers={'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                success = 200 <= status < 300
                result_class = ('received200' if status == 200 else
                                'validation_pending202' if status == 202 else
                                'other2xx' if success else 'rejected')
        except urllib.error.HTTPError as error:
            success = False
            status = error.code
            result_class = 'rejected'
            error_class = type(error).__name__
        except Exception as error:
            success = False
            result_class = 'unknown'
            error_class = type(error).__name__
    if result_callback is not None:
        try:
            receipt = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                       'canonical_urls': urls, 'http_status': status,
                       'result_class': result_class}
            if error_class is not None:
                receipt['error_class'] = error_class
            result_callback(receipt)
        except Exception:
            pass
    return success

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


def ping(urls, timeout=15):
    """Submit URLs for indexing; returns True only on a 2xx answer. Never raises."""
    urls = [u for u in urls if isinstance(u, str) and u.startswith('https://' + HOST + '/')]
    if not urls:
        return False
    body = json.dumps({'host': HOST, 'key': INDEXNOW_KEY, 'urlList': urls}).encode()
    request = urllib.request.Request(
        ENDPOINT, data=body, headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False

"""Offline, identified photo-page grants for stock-provider tests."""
import json
from news_mvp.pexels_rights import from_html


def photo_html(candidate, code='Pexels', **changes):
    attrs = {'id': int(candidate['photo_id']), 'license': code, 'status': 'approved',
        'published': True, 'pending': False,
        'user': {'first_name': candidate['name'], 'last_name': None,
                 'slug': candidate['profile'].rstrip('/').rsplit('@', 1)[-1]},
        'image': {'large': candidate['image_url']}}
    attrs.update(changes)
    page = {'id': candidate['photo_id'], 'medium': {
        'id': candidate['photo_id'], 'type': 'photo', 'attributes': attrs}}
    return ('<script id="__NEXT_DATA__" type="application/json">' +
            json.dumps({'props': {'pageProps': page}}) + '</script>').encode()


def grant(candidate, _state=None):
    return from_html(photo_html(candidate), candidate, 'pexels_https', '2026-09-26T12:00:00+00:00')

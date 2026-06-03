#!/bin/bash
# Refresh X/Twitter OAuth 2.0 access token.
# Access tokens expire every ~2h; run via cron every 90-120 minutes.
# Secret safety: client credentials are read from the 0600 token file, not hard-coded here.
set -euo pipefail

TOKENS_FILE="${X_TOKENS_FILE:-/workspace/.secrets/x-tokens.json}"

python3 - "$TOKENS_FILE" << 'PYEOF'
import json, urllib.request, urllib.parse, base64, sys, os, stat
from datetime import datetime, timezone

TOKENS_FILE = sys.argv[1]

try:
    with open(TOKENS_FILE) as f:
        d = json.load(f)
except Exception as e:
    print(f"ERROR: Cannot read {TOKENS_FILE}: {e}")
    sys.exit(1)

refresh_token = d.get('refresh_token', '')
client_id = d.get('client_id', '')
client_secret = d.get('client_secret', '')
if not refresh_token:
    print("ERROR: No refresh token found in tokens file")
    sys.exit(1)
if not client_id or not client_secret:
    print("ERROR: X client credentials missing from tokens file")
    sys.exit(1)

creds = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()
body = urllib.parse.urlencode({'grant_type': 'refresh_token', 'refresh_token': refresh_token}).encode()
req = urllib.request.Request(
    'https://api.x.com/2/oauth2/token',
    data=body,
    headers={'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': f'Basic {creds}'}
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
except urllib.error.HTTPError as e:
    try:
        resp = json.loads(e.read())
    except Exception:
        resp = {'status': e.code, 'error': 'token_refresh_http_error'}
    print(f"ERROR: Token refresh failed: {resp}")
    sys.exit(1)

if 'error' in resp:
    print(f"ERROR: {resp}")
    sys.exit(1)

d['access_token'] = resp['access_token']
if resp.get('refresh_token'):
    d['refresh_token'] = resp['refresh_token']
d['obtained_at'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

tmp = TOKENS_FILE + '.tmp'
with open(tmp, 'w') as f:
    json.dump(d, f, indent=2)
os.replace(tmp, TOKENS_FILE)
os.chmod(TOKENS_FILE, stat.S_IRUSR | stat.S_IWUSR)
print(f"OK: X token refreshed at {d['obtained_at']}")
PYEOF

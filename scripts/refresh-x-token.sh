#!/bin/bash
# Refresh X/Twitter OAuth 2.0 access token
# Access tokens expire every 2h, refresh tokens are long-lived
# Run via cron every 90 minutes
# NOTE: Uses Python — jq not available on this host

TOKENS_FILE="/workspace/.secrets/x-tokens.json"
CLIENT_ID="R29GV0ZxVW1JYndja3JlRncxT0c6MTpjaQ"
CLIENT_SECRET="NFW3LOQeQybm6msGZXnHPwwov5uN2-SbIz6uTcuShVNq0F1m--"

python3 - "$TOKENS_FILE" "$CLIENT_ID" "$CLIENT_SECRET" << 'PYEOF'
import json, urllib.request, urllib.parse, base64, sys, os
from datetime import datetime, timezone

TOKENS_FILE, CLIENT_ID, CLIENT_SECRET = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    d = json.load(open(TOKENS_FILE))
except Exception as e:
    print(f"ERROR: Cannot read {TOKENS_FILE}: {e}")
    sys.exit(1)

refresh_token = d.get('refresh_token', '')
if not refresh_token:
    print("ERROR: No refresh token found in tokens file")
    sys.exit(1)

creds = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()
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
    resp = json.loads(e.read())
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
print(f"OK: X token refreshed at {d['obtained_at']}")
PYEOF

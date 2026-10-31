#!/usr/bin/env bash
# Bounded Cloudflare Pages deploy. Retries only Cloudflare-side/transport failures.
set -uo pipefail
TRIES="${PAGES_DEPLOY_TRIES:-4}"
PAUSE="${PAGES_DEPLOY_PAUSE:-30}"
WRANGLER="${WRANGLER:-npx --yes wrangler@4}"
log="$(mktemp)"
for attempt in $(seq 1 "$TRIES"); do
  $WRANGLER pages deploy public --project-name=uutistenlukija-fi --branch=main \
      --commit-hash="$GITHUB_SHA" --commit-dirty=false >"$log" 2>&1
  rc=$?
  cat "$log"
  if [ "$rc" -eq 0 ]; then exit 0; fi
  if ! grep -Eqi 'internal server error|code: 10500|code: 10013|code: 8000000|5[0-9][0-9] (Internal|Bad Gateway|Service Unavailable|Gateway Timeout)|ETIMEDOUT|ECONNRESET|EAI_AGAIN|fetch failed|socket hang up' "$log"; then
    echo "Pages deploy failed with a non-transient error; not retrying" >&2
    exit 1
  fi
  if [ "$attempt" -lt "$TRIES" ]; then
    echo "Cloudflare-side error on attempt $attempt/$TRIES; retrying" >&2
    sleep $((attempt * PAUSE))
  fi
done
echo "Pages deploy still failing after $TRIES attempts" >&2
exit 1

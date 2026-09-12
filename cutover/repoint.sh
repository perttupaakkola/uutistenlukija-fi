#!/usr/bin/env bash
# Final public dispatch is deliberately separate from local preparation.
set -euo pipefail
cd /home/pertt/work/uutistenlukija
/home/pertt/.hermes/hermes-agent/venv/bin/python -B cutover/prepare.py gate
state=/home/pertt/.local/share/uutistenlukija/cutover
test -f "$state/stop.finished"
test -f "$state/drain-verified.json"
test -f "$state/public-continuity-verified.json"
/home/pertt/.hermes/hermes-agent/venv/bin/python -B - "$state" <<'PY_CHECK'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);d=json.loads((p/'drain-verified.json').read_text());c=json.loads((p/'public-continuity-verified.json').read_text())
assert d['legacy_processes_active']==0 and d['legacy_actions_active']==0
assert c['complete_history'] is True and c['local_assets_verified'] is True
assert c['release_commit']==(p/'release-remote-commit').read_text().strip()
PY_CHECK
# Step 5 supplies the reviewed remote commit after replacing ONLY the news executor
# and staging the complete public-data baseline + fresh output. Never force push.
release_commit=$(cat "$state/release-remote-commit")
test "$(gh api repos/perttupaakkola/uutistenlukija-fi/commits/main --jq .sha)" = "$release_commit"
touch "$state/repoint.started"
gh workflow enable 246481423 --repo perttupaakkola/uutistenlukija-fi
gh workflow run deploy.yml --repo perttupaakkola/uutistenlukija-fi --ref main
# No timer activation here. Step 5 verifies actual deployment before installing ONE timer.

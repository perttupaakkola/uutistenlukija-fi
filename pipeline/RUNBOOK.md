# Pipeline Operations Runbook — uutistenlukija.fi

> Last updated: 2026-03-25  
> Maintainer: Max (ops)

---

## Quick reference

| Check | Command |
|-------|---------|
| Pipeline health (24h) | `python3 pipeline/dashboard.py` |
| Feed health | `python3 pipeline/feed_health.py --report` |
| Publish stats | `bash scripts/publish-stats.sh` |
| Error classifier | `python3 pipeline/error_classifier.py --limit 24` |
| Manual run | `bash pipeline/auto_publish.sh` |
| Template validator | `bash scripts/validate_templates.sh --no-discord` |
| Live status page | https://uutistenlukija.fi/tila/ |

---

## 1. Common failure modes

### 🔴 Permission denied on auto_publish.sh

**Symptom:** `cron.log` shows `/bin/sh: pipeline/auto_publish.sh: Permission denied` repeatedly. No new articles. Spidey escalates.

**Root cause:** Bridge sync commits reset the execute bit from `100755` → `100644` in git. After `git pull`, the file loses `+x`.

**Fix (host):**
```bash
cd /home/pertt/.openclaw/workspace/projects/uutistenlukija
git pull          # restores 100755 automatically (stored correctly in remote)
bash pipeline/auto_publish.sh  # manual run to confirm recovery
```

**If git pull doesn't restore +x:**
```bash
chmod +x pipeline/auto_publish.sh
bash pipeline/auto_publish.sh
```

**Prevention:** `scripts/validate_templates.sh` and `.githooks/pre-commit` enforce 100755 on all `.sh` files. `pipeline/auto_publish.sh` also runs `git checkout HEAD -- pipeline/*.sh` before staging to prevent re-regression.

---

### 🔴 OpenAI quota exhausted (rewriter dead)

**Symptom:** Pipeline runs, scans articles, but rewriter fails. Logs show:
```
openai.RateLimitError: Error code: 429
'type': 'insufficient_quota'
You exceeded your current quota
```
`dashboard.py` shows `ok=0 error=N` for all recent runs.

**Root cause:** OpenAI billing limit hit. No code fix possible.

**Fix:** Perttu must add credits at https://platform.openai.com/account/billing

**Verify recovery:** After billing topped up, run `bash pipeline/auto_publish.sh` manually and watch for `[rewriter] ✅` lines.

---

### 🟡 Scanner 304 / articles not advancing

**Symptom:** Scanner fetches feeds but `[dedup] 0 new` every run. `publish-stats.sh` shows 0 published for hours.

**Root cause:** HTTP 304 Not Modified — scanner was sending `If-None-Match` / `If-Modified-Since` headers, causing feeds to return cached empty responses.

**Fix (already applied in production):** Scanner strips conditional headers. If it regresses, check `pipeline/scanner.py` for `If-None-Match` or `If-Modified-Since` in request headers and remove them.

**Diagnose:**
```bash
# Check if scanner is returning articles or 304s
grep -E "→ [0-9]+ articles|304|Not Modified" pipeline/logs/cron.log | tail -20
```

---

### 🟡 Dedup too aggressive (articles dropped)

**Symptom:** Scanner finds articles, dedup drops nearly all. `[dedup:published] X articles dropped` dominates logs.

**Parameters to tune (pipeline/dedup.py):**
```python
SIMILARITY_THRESHOLD = 0.60      # title similarity — lower = less aggressive
KEYWORD_OVERLAP_THRESHOLD = 12   # shared Finnish words — raise to be less aggressive
```
**Dedup window (auto_publish.sh):**
```bash
python3 run_pipeline.py --dedup-window 48  # hours to compare against — reduce to 24h if too aggressive
```

**Diagnose:**
```bash
grep "TITLE_MATCH\|KW_MATCH\|dropped" pipeline/logs/auto_publish_*.log | tail -20
```

**Note:** Before tuning, check if it's actually dedup causing the loss or the source-material filter (`MIN_SOURCE_WORDS`). They look similar in output but are different problems.

---

### 🟡 Source material filter blocking articles (no usable text)

**Symptom:** `[quality] Skipped N articles with < 25 words source material`. Published count stays near 0 even though scanner finds articles.

**Root cause:** Finnish paywalled sources (IS, IL, HS) return 10-30 word snippets. If Bing News is also rate-limited on the host, articles arrive with no research text.

**Parameters (pipeline/run_pipeline.py):**
```python
MIN_SOURCE_WORDS = 25   # lower threshold = more articles pass
# _total_source_words() now sums: title + description + research
```

**Diagnose:**
```bash
grep "Skipped.*words source\|→ No usable sources\|Bing returned empty" \
  pipeline/logs/auto_publish_$(ls -t pipeline/logs/auto_publish_*.log | head -1 | xargs basename | sed 's/auto_publish_//;s/.log//').log
```

---

### 🟡 Quality gate rejections

**Symptom:** Articles get rewritten but not published. `quality_gate_rejects.log` growing.

**Common reject reasons:**
| Reason | Fix |
|--------|-----|
| `too_short` (< 250 words) | Rewriter produces thin output — check source material quality |
| `keyword_stuffing` | Rewriter over-uses a word — usually improves with more source text |
| `few_paragraphs` | Source too short for rewriter to expand — raise MIN_SOURCE_WORDS |
| `lead_too_short` | Lead paragraph < 30 words — rewriter prompt issue |

**Inspect recent rejects:**
```bash
tail -20 pipeline/logs/quality_gate_rejects.log
```

---

### 🟡 Feed stale (no new articles 7+ days)

**Symptom:** `feed_health.py --report` shows `⚠️ STALE`. Discord alert fires once when stale flag sets.

**Root cause:** Feed URL changed, RSS format changed, or site restructured.

**Diagnose:**
```bash
python3 pipeline/feed_health.py --report
# Check feed URL manually:
curl -sI "https://feeds.example.com/rss" | head -5
```

**Fix:**
1. Update the `url` in `pipeline/scanner.py` RSS_FEEDS list if URL changed
2. If feed is permanently dead, remove it from RSS_FEEDS
3. Re-enable health tracking after fix: `python3 pipeline/feed_health.py --reset "Feed Name"`

**Known stale:** Yle Kulttuuri (last article 2026-02-10 — check https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_KULTTUURI)

---

### 🟡 Hugo build fails (template error)

**Symptom:** GH Actions shows ❌ on "Build" step. "Validate Hugo templates" step may show the error first.

**Quick triage:**
```bash
bash scripts/validate_templates.sh --no-discord
```

**Common causes seen in production:**
| Pattern | Fix |
|---------|-----|
| `{{ continue }}` in range | Replace with `{{- if not (COND) }}...{{- end }}` |
| `time()` standalone | Replace with `time.AsTime()` |
| `float()` standalone | Remove — `math.Div` handles integers natively |
| Unbalanced `if/range/with/end` | Count opens vs ends per file |
| `_internal/schema.html` | Remove — we use custom `json-ld.html` |

**These are caused by bridge sync commits overwriting layout files.** `auto_publish.sh` now runs `git checkout HEAD -- layouts/` before staging to prevent this.

---

### 🟡 Discord webhook 403

**Symptom:** `notify_discord_*` calls succeed locally but Discord returns 403. No alerts delivered.

**Fix:** Regenerate webhook URL in Discord server settings → Integrations → Webhooks. Update `DISCORD_PIPELINE_WEBHOOK` in `.env` and in GH Actions secrets.

**Check current webhook:**
```bash
grep DISCORD_PIPELINE_WEBHOOK pipeline/.env
```

---

### 🟡 Host checkout drift

**Symptom:** Host runs old code; CI is green but host pipeline fails. Recent fixes "not working" on host.

**Fix:**
```bash
cd /home/pertt/.openclaw/workspace/projects/uutistenlukija
git pull
git log --oneline -3  # confirm latest commit matches CI
```

---

## 2. Manual pipeline run

**From host:**
```bash
cd /home/pertt/.openclaw/workspace/projects/uutistenlukija
bash pipeline/auto_publish.sh
# Logs to: pipeline/logs/auto_publish_YYYYMMDD_HHMMSS.log
```

**Run pipeline only (no git push/build):**
```bash
cd pipeline
python3 run_pipeline.py --quick --max-articles 1 --dedup-window 48
```

**Run with more articles (catch-up after outage):**
```bash
python3 run_pipeline.py --quick --max-articles 5 --dedup-window 24
```

**Dry-run scanner (no publish):**
```bash
python3 scanner.py 2>&1 | head -30
```

---

## 3. Checking pipeline health

### From host

```bash
# Full dashboard
python3 pipeline/dashboard.py

# Last 6h focus
python3 pipeline/dashboard.py --hours 6

# Feed health
python3 pipeline/feed_health.py --report

# Recent publish log (most recent run)
tail -40 pipeline/logs/$(ls -t pipeline/logs/auto_publish_*.log | head -1 | xargs basename)

# Publish rate over 7 days
bash scripts/publish-stats.sh
```

### From sandbox (Max's perspective)

Sandbox has no access to host `/home/pertt` filesystem. Read-only access via:

```bash
# Clone and pull latest
cd /workspace/uutistenlukija-repo && git pull

# Check GH Actions (last 5 builds)
curl -s "https://api.github.com/repos/perttupaakkola/uutistenlukija-fi/actions/runs?per_page=5" \
  -H "Accept: application/vnd.github+json" | python3 -c "
import json,sys
for r in json.load(sys.stdin)['workflow_runs']:
    print(r.get('conclusion') or r['status'], r['head_sha'][:8], r['head_commit']['message'][:50])
"

# Check live site health JSON
curl -s https://uutistenlukija.fi/api/health.json | python3 -m json.tool

# Check live pipeline status (updated every ~15min by pipeline)
curl -s https://uutistenlukija.fi/api/pipeline-status.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('generated_at:', d['generated_at'])
print('last_published:', d['articles']['last_published_ts'])
print('published 24h:', d['articles']['published'])
print('run health:', d['runs'])
"

# Read most recent auto_publish log from metrics (indirect)
curl -s https://uutistenlukija.fi/api/health.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('status:', d['status'])
print('articles:', d['articleCount'])
print('lastPublished:', d['lastPublished'])
print('publishedToday:', d.get('pipeline',{}).get('publishedToday'))
"
```

---

## 4. Key file paths

```
pipeline/
  auto_publish.sh          — main cron entrypoint (every 10min)
  run_pipeline.py          — pipeline orchestrator
  scanner.py               — RSS feed fetcher
  dedup.py                 — deduplication (pre + post rewrite)
  rewriter.py              — OpenAI gpt-4o-mini article rewriter
  quality_gate.py          — article quality filter (post-rewrite)
  publisher.py             — writes .md files to content/posts/
  feed_health.py           — per-feed error/stale tracking
  dashboard.py             — CLI health dashboard
  generate_health.py       — writes static/api/health.json
  generate_pipeline_status.py — writes static/api/pipeline-status.json
  health_check.py          — Discord alert helpers
  error_classifier.py      — classifies ok/skip/error from metrics

  logs/
    auto_publish_YYYYMMDD_HHMMSS.log  — per-run logs
    cron.log                          — raw cron output
    publish-metrics.json              — JSONL run stats
    quality_gate_rejects.log          — TSV rejection reasons
    feed-health.json                  — per-feed state
    link_check.log                    — post-deploy internal link check

scripts/
  validate_templates.sh    — Hugo 0.147 template validator (runs pre-build)
  publish-stats.sh         — 7-day pipeline metrics summary
  pipeline-watchdog.sh     — restarts stuck pipeline runs

.githooks/
  pre-commit               — enforces +x on .sh files before every commit
  post-merge               — restores +x after every git pull/merge

.github/workflows/
  deploy.yml               — Hugo build + Cloudflare Pages deploy
```

---

## 5. Escalation path

| Severity | Condition | Who |
|----------|-----------|-----|
| P0 | Build broken (all deploys failing) | Max → Felix → Perttu (host access) |
| P0 | OpenAI quota exhausted | Max → Felix → Perttu (billing) |
| P1 | No articles published >6h | Max → Felix |
| P1 | Permission denied on auto_publish.sh | Max → Felix → Perttu (git pull on host) |
| P2 | Single feed stale | Max (auto-handled by feed_health.py) |
| P2 | Dedup too aggressive | Max |
| P3 | Quality gate tuning | Max + Felix |

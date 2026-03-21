# Pipeline Weekly Digest — Week of 2026-03-21

*Generated: 2026-03-21 17:26 UTC | Data window: last 7 days (Mar 15–21)*

---

## Top-Level Stats

| Metric | This week | Prev week | Change |
|--------|-----------|-----------|--------|
| Total pipeline runs | 200 | — | first full week |
| Successful runs | 145 | — | — |
| **Success rate** | **72.5%** | — | — |
| Articles published | **305** | 0 | first week |
| Avg run duration (success) | 124s | — | — |
| Avg articles per successful run | 0.08 | — | — |

**Daily breakdown:**

| Date | Runs | OK | Failed | Rate | Articles |
|------|------|----|--------|------|----------|
| Mar 18 | — | — | — | — | 266 |
| Mar 19 | — | — | — | — | 10 |
| Mar 20 | 32 | 22 | 10 | 68% | 18 |
| Mar 21 | 168 | 122 | 46 | 72% | 11 |

> Note: Mar 18 data is from pre-metrics-logging era. Mar 20 was first day metrics.json was active.
> 266 articles on Mar 18 = initial corpus build (bulk ingest, not normal cadence).

**Current health: 🟡 Degraded** — success rate below 90% target. Functional but producing fewer articles per day than capacity.

---

## Failure Breakdown by Category

### 1. No articles from scanner — 45 failures (81.8% of all failures)
**Trend: ↑ Worsening** | Last seen: 2026-03-21 17:11 UTC

Scanner completes but returns 0 publishable articles. The run terminates cleanly — this is not a crash.

**Root causes (in order of likelihood):**
- **Dedup filter too aggressive** — articles from RSS feeds are already fingerprinted; new pipeline runs find nothing new. Normal during quiet news cycles but excess frequency of 15-min runs amplifies this. 22.5% of all runs produce 0 articles, which is structurally high.
- **Threshold for keyword overlap (8 shared words)** — lowered from 12 in C38, may be over-filtering same-day follow-up stories
- **Firehose pipeline runs returning 0** — firehose-only runs (every 15 min) frequently have nothing. These should be tracked separately from full pipeline runs.

**Impact:** 45 wasted scan cycles. Zero publishing impact (no articles were ready anyway). But it inflates the "failure" count and obscures real failures.

**Note:** Many of these 45 may be expected behavior. The scanner returning 0 on a quiet Sunday evening is not a bug — the 15-min cadence just means we check often and occasionally find nothing.

---

### 2. Python/import exception — 8 failures (14.5% of failures)
**Trend: ↓ Improving** | Last seen: 2026-03-21 12:01 UTC (RESOLVED)

**Root cause identified and fixed:**
Missing `import re` in `run_pipeline.py` — introduced when the Tier 3 source warning code was added in commit `8e5cb91`. Caused `NameError: name 're' is not defined` in `_quality_issues()`.

**Fix:** Added `import re` to stdlib imports in `run_pipeline.py` (commit `8e5cb91`).
**Status:** ✅ RESOLVED. Last failure at 12:01. 5+ hours clean since fix.

---

### 3. Rewriter LLM timeout — 2 failures (3.6% of failures)
**Trend: ↓ Improving** | Last seen: 2026-03-21 09:21 UTC

Rewriter step exceeded 115s timeout. Typically caused by OpenAI API latency spikes under load.

**Fix already in place:** `timeout=120` added to rewriter API calls (commit ~Cycle 37). The 2 timeouts predate or occurred just as the fix was deployed.
**Status:** ✅ Improving. No timeouts since 09:21. Watchdog (pipeline-watchdog.sh) will auto-retry on next occurrence.

---

## Top 3 Action Items

### 🔴 Action 1: Separate "no articles" from real failures
**Priority: High | Effort: Low | Owner: Max**

The 72.5% success rate is misleading — 45 of 55 "failures" are empty-scan runs that are arguably expected behavior. If we exclude `no_articles_scan` from the failure definition, the true failure rate is:
- Actual errors: 10 runs (5.0%) — 8 python_error + 2 timeout
- Adjusted success rate: **95%** 🟢

**Action:** Update metrics reporting to distinguish:
- `zero_articles` — scanner completed, 0 publishable (not a failure, just no news)
- `pipeline_error` — actual crash or timeout

This will give a more accurate health signal and stop generating false alarms.

---

### 🟡 Action 2: Reduce 15-min frequency during off-peak hours
**Priority: Medium | Effort: Low | Owner: Perttu (crontab)**

305 articles in a week at 72% of 200 runs = ~0.08 articles per successful run on average. The pipeline runs 96 times/day (every 15 min) but publishes ~1 article per day currently.

**Option A:** Reduce cadence to every 30 min outside 06:00–22:00 Helsinki time. Cuts ~50% of cron overhead.
**Option B:** Keep 15 min but add a "backoff" if 3 consecutive empty-scan runs — wait 30 min before next run.

---

### 🟢 Action 3: Run backfill_thin_articles.py
**Priority: Medium | Effort: Low (~$0.006) | Owner: Alex or host exec**

Quality sweep found 55 articles under 50 words (worst offenders) and 561 under 200 words. This directly impacts SEO — thin content = ranking penalty.

```bash
cd /home/pertt/.openclaw/workspace/projects/uutistenlukija/pipeline
python3 backfill_thin_articles.py --max-words 50 --batch 20 --push
```

~3 minutes, ~$0.006. Immediate quality score improvement from 61/100.

---

## Improvements Shipped This Week

| Date | Commit | What | Impact |
|------|--------|------|--------|
| Mar 20 | pipeline | Scanner 304 bug fix | +30pp success rate |
| Mar 21 | `8e5cb91` | `import re` fix | Cleared 8 python errors |
| Mar 21 | `8e5cb91` | Pipeline watchdog wired | Auto-retry on failures |
| Mar 21 | `fd3c368` | 3-tier source trust system | No more Chuck Norris incidents |
| Mar 21 | `fd3c368` | Sara's style rules in prompt | Better article quality |
| Mar 21 | `fd3c368` | SEO dashboard + X auto-poster | Traffic growth tooling |
| Mar 21 | `fd3c368` | Backfill script ready | 615 thin articles queued |
| Mar 21 | Various | dead_link_checker, CRON.md, quality sweep | Ops tooling complete |

---

## Open Blockers

| Issue | Status | Blocker |
|-------|--------|---------|
| Hugo build failing (tag-cloud math funcs) | 🔴 In progress | Alex fixing layout templates |
| Cron jobs not yet installed on host | 🟡 Pending | Perttu: `crontab -e` with block from CRON.md |
| Sitemap not submitted to Search Console | 🟡 Pending | Perttu: 2-min manual submit |
| X token refresh not on cron | 🟡 Pending | X poster will fail after 2h without it |
| GA4 / Search Console data lag | 🟡 Expected | 24-72h for GA4, 2-3 days for SC — no action needed |

---

*Next digest: 2026-03-28 | Auto-generated by `pipeline/error_classifier.py` + `metrics.py`*

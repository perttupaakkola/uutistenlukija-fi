# Deploy Readiness Checklist — 2026-03-20

## Status: ✅ READY TO DEPLOY

All changes are already live on `main` and Cloudflare Pages auto-deploys on push.
This checklist covers **host-side config** that still needs to be set up manually.

---

## Commits Since Last Manual Deploy (Today's Session)

### Content (623 articles updated)
| SHA | Summary |
|-----|---------|
| `ffcb10c` + `39470a3` + `fec0dce` | Auto-tag all 623 articles (3-5 Finnish tags each) |
| `198143c` + `666f154` + `2369cc5` + `9e11885` + `7c8d159` | Image backfill — 448 articles with missing hero images |
| `1431bbd` | Truncate 70 over-length descriptions to ≤155 chars |
| `d3e076a` | Internal linking — 623 articles × 3 related article links |

### Pipeline Scripts (new/updated)
| SHA | Summary |
|-----|---------|
| `d3e076a` | `pipeline/internal_links.py` — related article scorer |
| `ea3fba1` | `pipeline/lighthouse_check.py` — PSI audit + Discord #metrics |
| `fec0dce` | `pipeline/auto_tag.py` — keyword-based Finnish tagger |
| `dc303ca` | `pipeline/backfill_images.py` — Unsplash/Pexels image backfill |
| `b171913` | `pipeline/pre_publish_check.py` — quality gate in auto_publish.sh |
| `48ce5cc` | `pipeline/validate_articles.py` — content health scorer |
| `53197a5` | `pipeline/dead_link_check.py` + `dead_link_cron.sh` |
| `b0b8c57` | `pipeline/CRON.md` — full cron schedule reference |

### SEO / Templates
| SHA | Summary |
|-----|---------|
| `bbcd129` | `static/robots.txt` (new) + sitemap `xmlns:image` namespace fix |
| `4561311` | JSON-LD NewsArticle schema + author enrichment |
| `498f5f4` | Category RSS feeds listing page |

### Performance / Infrastructure
| SHA | Summary |
|-----|---------|
| `e947138` | Inline critical CSS, lazy-load stylesheet, preconnects |
| `59cac33` | Daily metrics report script for #metrics channel |
| `53197a5` | 404 page GA4 custom event tracking |

---

## Host Config Needed ⚠️

### 1. Install cron jobs (REQUIRED for monitoring)

SSH into deploy host, `crontab -e`, add:

```cron
PIPELINE=/path/to/projects/uutistenlukija/pipeline

*/15 * * * * $PIPELINE/auto_publish.sh >> $PIPELINE/logs/auto_publish.log 2>&1
0 6 * * *   $PIPELINE/metrics_cron.sh >> $PIPELINE/logs/metrics-cron.log 2>&1
0 9 * * *   cd $PIPELINE && python3 lighthouse_check.py >> $PIPELINE/logs/lighthouse-cron.log 2>&1
0 7 * * 1   cd $PIPELINE && python3 validate_articles.py --all >> $PIPELINE/logs/validate-cron.log 2>&1
0 7 * * 0   $PIPELINE/dead_link_cron.sh >> $PIPELINE/logs/dead-link-cron.log 2>&1
```

See `pipeline/CRON.md` for full details.

### 2. pipeline/.env (REQUIRED for pipeline to function)

Create `pipeline/.env` with:

```bash
OPENAI_API_KEY=...
PEXELS_API_KEY=3HYwUfVZkBHgUt30ygCCt6qJrO7xW3CVe1OhwFUO7byYO5Er2L5txhem
UNSPLASH_ACCESS_KEY=50wJVJ-XzJC-oYF0pgGvD6v4q_ERyb8K0u4tn4m6B7g
KIE_API_KEY=bccd653c94693baab42985f14ec4a9dd
DISCORD_BOT_TOKEN=...          # for pipeline → Discord #metrics / #operations
DISCORD_WEBHOOK_METRICS=...    # optional webhook alternative for #metrics
DISCORD_WEBHOOK_OPS=...        # optional webhook alternative for #operations
```

### 3. GA4 OAuth (LOW PRIORITY — analytics still work via gtag.js)

The GA4 OAuth client was disabled in Google Cloud Console.
Affects: `pipeline/metrics_report.py` (traffic data from GA4 API).
GA4 tag `G-967GVZH75X` still fires in browser — real-time and standard reports unaffected.

To fix: Re-enable OAuth client at https://console.cloud.google.com/apis/credentials
Project: `uutistenlukija-fi`

### 4. Unsplash production key (LOW PRIORITY)

Current key is demo tier (50 req/hr). Upgrade for keyword-matched images instead of category fallbacks.
Apply at: https://unsplash.com/oauth/applications
Application ID: `900325`

### 5. Newsletter placeholders (LOW PRIORITY)

`layouts/partials/newsletter.html` still uses placeholder Mailchimp values.
Replace `MAILCHIMP_U` and `MAILCHIMP_ID` with real credentials when newsletter is activated.

---

## Hugo Build

```bash
# From project root:
hugo --minify --environment production

# Expected output:
# | EN
# +------------------+-----+
# | Pages            | 680+ |
# | Unique outputs   | 680+ |
# | Build time       | ~8s  |

# Verify no errors in output (watch for "WARN" template errors)
```

GitHub Actions handles production builds automatically on push to `main`.
Cloudflare Pages deploys from Actions output.
No manual build step needed for normal deploys.

---

## One-Time Backfill Tasks (run on host, not blocking deploy)

```bash
# Run internal links for new articles (after each batch publish)
cd pipeline && python3 internal_links.py

# Re-run auto-tagger if new categories added
cd pipeline && python3 auto_tag.py

# Backfill images for any new unimaged articles
cd pipeline && python3 backfill_images.py --source unsplash
```

---

## Content Quality Score

| Metric | Before (2026-03-20 AM) | After |
|--------|------------------------|-------|
| no_description | 70 | 0 ✅ |
| no_image | 448 | 0 ✅ |
| no_tags | 621 | 0 ✅ |
| duplicate_titles | 0 | 0 ✅ |
| Health score | 21/100 | ~100/100 ✅ |

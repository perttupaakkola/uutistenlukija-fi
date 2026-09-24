# Uutistenlukija — automated Finnish news site

One Python controller writes one Finnish article per tick from a reviewed official source,
an independent reviewer approves it, and one guarded executor deploys it to
uutistenlukija.fi (GitHub Actions → Cloudflare Pages). Steady state: the pipeline runs on
the VPS timer (`uutistenlukija-mvp.timer`). There are no owner-approval gates — review is
the in-pipeline chain below, and every decision is recorded in the plans docs.

## Sources (news-reviewed-v2)

- NASA MODIS image-of-the-day plus pinned official text sources in
  `sources/finnish-official.json` (Helsinki, Tilastokeskus, Kuntaliitto, ECB, Kuopio,
  Vantaa, Valtioneuvosto). Each provider pins its article-URL pattern, hosts, reuse
  terms (text hash; document hash for Kuopio) and licence — the licence is never
  defaulted.
- Discovery reads each provider's bounded index/RSS with 48-hour freshness, returns at
  most five recipes, admits one new source per tick, rotates providers after the last
  admitted provider, and reports per-provider source errors without suppressing others.
- Related-coverage search may add corroborating sources (B..N): best effort, never
  required, and never the sole basis of a claim.

## Provenance

- Text releases bind packet/source/rights hashes; before release, stored intake bytes
  must reproduce the reviewed source and rights, and live-page readback must match the
  reviewed text (reversible CDN e-mail obfuscation excepted).
- Generated illustrations (`news_mvp/imagery.py`) are built from the reviewed draft's
  own title/lead, pixel-verified, screened for legible text, credited as AI, and linked
  to the `/kuvituskuvat/` terms. Source images are never used.
- Headlines target ≤60 characters: the writer is instructed, one bounded repair call
  fits over-long ones, and the reviewer checks the final draft.
- The public bundle includes RSS (`/rss.xml`), sitemap, canonical links, OG/Twitter/
  JSON-LD metadata, and an IndexNow key file; deploys ping IndexNow best-effort.

## Operations

- `python3 -B -m unittest discover -s tests` — full suite.
- `python3 -B -m news_mvp live-tick --config config.json` — one scheduled tick.
- `python3 -B -m news_mvp requeue-failed --config config.json [--job ID]` — reset failed
  publications for retry (fixed-bug recovery); the normal publish path re-validates
  everything before anything reaches the public site.
- Pending-publication priority: each tick reconciles at most one nonterminal publication
  before any new admission; multiple pending rows or unknown commit outcomes stop for
  operator review instead of guessing.
- State lives in `/home/pertt/.local/share/uutistenlukija` (`jobs.sqlite`, `media/`,
  `learning/`).

## Front-page snapshots

The existing live controller refreshes four MET Norway location forecasts and ECB daily
EUR reference rates when `frontpage_snapshots` is enabled in the local config. Data is
cached in state `frontpage-data.json` (weather: one hour; currencies: six hours), then
embedded in the normal static release. Requests have an identifying User-Agent, an
8-second timeout and a size limit; upstream failures preserve the last snapshot. There
is no client API key, third-party page-load request or additional service. The browser
selects the nearest forecast hour and suppresses forecasts older than 18 hours or rates
older than seven days; source/model timestamps and the forecast/reference-rate labels
stay visible. Provider outages do not stop article publication.

The homepage may feature the newest illustrated article among the first nine stories
when it is within 48 hours of the newest article, labelled “Kuvassa”. All 30 recent
stories remain present and RSS/latest listings retain chronological order. Known
visually audited image exclusions and descriptive alt corrections are presentation-only
in `site.py`; original reviewed records remain intact.

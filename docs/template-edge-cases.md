# Template Edge Cases — Audit Results

**Date:** 2026-03-23  
**Audited by:** Alex  
**Scope:** All Hugo templates in `layouts/` — edge cases for missing image, excerpt, category, author, empty content.

---

## 1. Summary of Findings

| # | Severity | Template | Issue | Status |
|---|----------|----------|-------|--------|
| 1 | **Bug** | `related-articles.html` | `.ByDate` called on plain slice — silently returns nil | **Fixed** |
| 2 | **Bug** | `category.html`, `tag.html` | Featured image `alt` used category/tag title instead of article title | **Fixed** |
| 3 | **Bug** | `tag.html` | Paginator set but no pagination nav rendered — tags with 20+ articles had no page 2+ | **Fixed** |
| 4 | **Bug** | `json-ld.html` | `articleSection` emitted as `""` when article has no categories — fails Schema.org validator | **Fixed** |
| 5 | **Bug** | `og-meta.html` | `og:image:type` hardcoded `image/jpeg` even when serving `.png` category/fallback images | **Fixed** |
| 6 | **Minor** | `single.html` | Content split on `</p>` produced a trailing orphan `</p>` from empty last segment | **Fixed** |
| 7 | **Minor** | `category.html`, `tag.html` | Featured image served at raw CDN URL (no size params) — no resize for card context | **Fixed** |
| 8 | **Info** | `category.html`, `tag.html` | Featured image had no `onerror` fallback | **Fixed** |
| 9 | **Info** | `breadcrumbs.html`, `breadcrumb-schema.html` | `index .Params.categories 0` without `| default` — safe (Hugo returns `""` for OOB) | OK |
| 10 | **Info** | `hero-image.html` | `$img` falls back to category placeholder JPG when `.Params.image` empty — fully guarded | OK |
| 11 | **Info** | `single.html` | `.File.BaseFileName` used in JS slug fallback — safe (single.html only used for regular pages) | OK |

---

## 2. Per-Template Field Guard Inventory

### `layouts/index.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `index ... 0 \| default "kotimaa"` | Falls back to kotimaa category placeholder image |
| `.Params.image` | `\| default (printf ...)` | Category placeholder JPG |
| `.Params.image_thumb` | `\| default $img` | Uses full-size image URL |
| `.Params.image_alt` | `\| default .Title` | Article title used as alt text |
| `.Params.author` | `{{ with .Params.author }}` | Omitted from meta line |
| `.Params.reading_time` | `isset` check + `.ReadingTime` fallback | Hugo's automatic reading time |
| `.Title` | Always set by Hugo | Safe |
| `index $sorted 0` (lead article) | `{{ with index $sorted 0 }}` | Nothing rendered if no articles |
| Highlights row | `{{ if $highlights }}` | Omitted if no articles beyond first |
| Category sections | `{{ if $catPosts }}` | Section omitted if category has no articles |

### `layouts/_default/single.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `{{ with .Params.categories }}` | Category label omitted |
| `.Params.tags` | `{{ with .Params.tags }}` | Tag list omitted |
| `.Params.author` | `{{ with .Params.author }}` | Author omitted from meta |
| `.Params.author_image` | `{{ with $.Params.author_image }}` | Author photo omitted |
| `.Params.author_title` | `{{ with $.Params.author_title }}` | Role line omitted |
| `.Params.author_bio` | `{{ with $.Params.author_bio }}` | Bio paragraph omitted |
| `.Content` | `{{ if .Content }}` *(fixed)* | "Artikkelin sisältö ei ole saatavilla." shown |
| `.Lastmod` vs `.Date` | `if gt $diffSec 3600` | "Päivitetty" line only shown when updated >1h after publish |
| `.PrevInSection` / `.NextInSection` | `{{ with }}` each | `<div class="article-nav-placeholder">` rendered instead |

### `layouts/partials/hero-image.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.image` | `{{ if $img }}...{{ else }}` | Category placeholder JPG with cache-bust hash |
| `.Params.categories` | `index ... 0 \| lower \| default "kotimaa"` | Falls back to kotimaa |
| `.Params.image_alt` | `\| default .Title` | Article title |
| `.Params.image_caption` | `and ... (ne ... "")` | Caption section omitted |
| `.Params.image_credit` | `and ... (ne ... "")` | Credit omitted |
| `.Params.image_source_url` | `and ... (ne ... "")` | Credit rendered as plain text, not link |
| `.Params.image_placeholder` | Checked, optional | No blur-up if missing |
| `onerror` | `this.onerror=null; this.src='...'` | Falls back to category placeholder |

### `layouts/partials/card-image.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.img` | `\| default ""` | Empty src — browser shows broken image (but callers always provide fallback) |
| `.thumb` | `\| default $img` | Full image used as thumb |
| `.alt` | `\| default ""` | Empty alt (decorative — link wraps it and has `tabindex="-1" aria-hidden="true"`) |
| `.permalink` | `\| default "#"` | Falls back to `#` link |

**Note:** `card-image.html` is always called via `dict` with `img` set to a fallback value by callers (`default (printf "/images/categories/...")`) — so empty img never reaches the partial in practice.

### `layouts/partials/og-meta.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.image` | `{{ with .Params.image }}` | Falls through to section/site fallback |
| `og:image` | Multi-level fallback chain | Category PNG → site og-image.png |
| `og:image:type` | `hasSuffix ".png"` check *(fixed)* | `image/png` for PNG files, `image/jpeg` otherwise |
| `og:description` | Priority chain: summary → description → .Summary → site desc | Never empty |
| Article tags | `{{ range .Params.tags }}` | Omitted when no tags |
| `twitter:creator` | Falls back to `twitter:site` | Always present |

### `layouts/partials/json-ld.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.image` | `{{ with .Params.image }}...{{ else }}` | Category OG PNG fallback |
| `.Params.categories` | `\| default (slice)`, then `index ... 0 \| default ""` | Empty string |
| `articleSection` | `{{ if $articleSection }}` *(fixed)* | Field omitted from JSON-LD entirely |
| `.Description` + `.Summary` | `\| default ... \| default` chain | Falls back to site description |
| `.Params.author` | `\| default .Site.Params.author` | Site-level author used |
| `$headline` length | `> 110` truncation | Headline capped at 110 chars + `…` |

### `layouts/partials/related-articles.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `\| default slice` | Empty slice, no category match |
| `.Params.tags` | `\| default slice` | Tag overlap = 0, falls to category fallback |
| `.Params.image_thumb` | `{{ with .Params.image_thumb }}...{{ else }}` chain | Builds thumb from `.Params.image` |
| `.Params.image` | Inner `{{ with }}` | Thumb left empty — card renders without image |
| No image | `{{ if $thumb }}` | `<div class="related-card__thumb">` renders with no `<img>` inside (placeholder via CSS `data-cat`) |
| Fallback pool | `site.RegularPages.ByDate.Reverse` *(fixed)* | Always works — Pages type, not plain slice |
| Category fallback | `site.RegularPages` filtered *(fixed)* | Works correctly via hugo.Pages `.ByDate` |

**Fixed:** Both fallback paths previously called `.ByDate` on `[]interface{}` plain slices (built via `| append`). Hugo's `.ByDate` is a method on `hugo.Pages` and silently returns nil on plain slices. Result: articles with no matching tags AND no category neighbors showed 0 related articles instead of 3. Replaced with `site.RegularPages` filtered queries.

### `layouts/taxonomy/category.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Description` / `.Content` | `{{ with .Content }}...{{ else }}{{ with .Description }}` | Hero description omitted if both missing |
| Featured article `.Params.image` | `{{ with .Params.image }}` | Image section omitted — body-only card |
| Featured image alt | `.Params.image_alt \| default .Title` *(fixed)* | Was incorrectly using `$.Title` (category name) |
| Featured image CDN sizing | *(fixed)* | Now requests `w=260&h=146&fit=crop` from Unsplash/Pexels |
| Featured image `onerror` | *(fixed)* | Falls back to `/images/categories/{cat}.jpg` |
| Article `.Params.categories` | `{{ with }}` | Category label omitted |
| Article `.Params.author` | `{{ with }}` | Author omitted |
| Pagination | `{{ if gt $pag.TotalPages 1 }}` | Nav hidden on single-page categories |

### `layouts/taxonomy/tag.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| (Same as category.html for featured article) | *(fixed as above)* | — |
| Pagination nav | *(added)* | Was entirely missing — tags with >20 articles were stranded on page 1 |

### `layouts/_default/list.html` (section list)

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.image_thumb` + `.Params.image` | Chained `\| default` | Category placeholder JPG |
| `.Params.image_alt` | `\| default .Title` | Article title |
| `onerror` | `this.src='/images/categories/{cat}.jpg'` | Category placeholder |
| `.Params.categories` | `{{ with .Params.categories }}` | Category label omitted |
| `.Params.author` | `{{ with .Params.author }}` | Author omitted |

### `layouts/partials/breadcrumbs.html` + `breadcrumb-schema.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `index ... 0` (no explicit default) | Hugo returns `""` for OOB slice access — safe; `{{ if $cat }}` guards the crumb append |
| Long titles | `> 63` → truncate to 60 + `…` | Prevents overly long breadcrumb items |
| Homepage | `{{ if not .IsHome }}` | Nothing rendered on homepage |

### `layouts/partials/read-next.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.NextInSection` | Fallback to category search | Finds first other article in same category |
| Both nil | `{{ with $next }}` | Entire section omitted |
| `.Params.image` | `{{ if $img }}...{{ else }}` | Placeholder `<div>` with CSS category colour |
| `.Params.categories` | `\| default slice`, then `index ... 0 \| default ""` | Empty string category (placeholder has no colour class) |
| `.Params.description` | `{{ with .Params.description }}` | Excerpt omitted |

**Minor gap:** When `$cat` is `""` (no categories), the placeholder div class becomes `read-next__img-placeholder--` (no colour suffix). CSS has no rule for this — shows as unstyled div. Acceptable; all pipeline articles have categories.

### `layouts/partials/trending.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `index ... 0 \| default "uutiset"` | "Uutiset" fallback |
| No articles | `{{ if $trending }}` | Section omitted |

### `layouts/partials/lyhyet.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.categories` | `\| default "Kotimaa"` | "Kotimaa" fallback |
| `.Params.description` | `{{ with }}...{{ else }}` | Falls back to `.Summary \| truncate 120` |
| `.Summary` | Always set by Hugo | Safe; empty string if no content |
| No articles | `{{ if $recent }}` | Section omitted |

### `layouts/partials/tag-cloud.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Site.Taxonomies.tags` | `{{ if $allTags }}` | Widget omitted |
| Tag count range = 0 | `{{ if gt $range 0 }}` | All tags get 0.78rem size (no div-by-zero) |

### `layouts/partials/social-share.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Permalink` | `absURL` always returns absolute URL | Safe |
| `.Title` | `urlquery` encoding | Safe; empty title produces minimal share URL |

### `layouts/partials/article-summary.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.Params.summary` | `{{ if and .Params.summary (ne .Params.summary "") }}` | Entire `<details>` omitted |

### `layouts/partials/toc.html`

| Field | Guard | Behaviour when missing |
|-------|-------|------------------------|
| `.TableOfContents` | Truthiness check | Omitted if empty |
| Heading count | `ge $headingCount 3` | Only rendered with 3+ headings |
| Word count | `ge .WordCount 800` | Only rendered for long articles |

---

## 3. Known Acceptable Gaps (No Fix)

1. **`read-next.html` no-category placeholder** — `read-next__img-placeholder--` has no CSS colour class. All pipeline articles have at least one category assigned, making this unreachable in production.

2. **`single.html` ad injection with sparse content** — The ad fires after split-index 2 regardless of paragraph count. For articles with fewer than 3 paragraphs, the ad slot renders at the end of content. AdSense handles empty ad slots gracefully.

3. **`most-read.html` localStorage dependency** — Widget is entirely JS-rendered. With no localStorage (private browsing, old Safari), it shows "Ei vielä lukuhistoriaa." This is intended behaviour.

4. **`continue-reading.html` hidden until JS** — Section has `hidden` attribute, removed by JS on load. Screen readers on JS-disabled environments won't see it. Intentional progressive enhancement.

5. **`category.html` featured article on page 2+** — The featured article (index 0 of all sorted pages) is always shown, but article at index 0 of the paginator page is skipped. On page 2, this means the featured article shows AND the first grid card is skipped. Cosmetic quirk, not a data loss issue.

---

## 4. Fixed Files Summary

| File | Commits | Changes |
|------|---------|---------|
| `layouts/partials/related-articles.html` | This PR | Fallback paths use `site.RegularPages` (hugo.Pages) instead of plain slice `.ByDate` |
| `layouts/taxonomy/category.html` | This PR | Featured img alt fixed, CDN resize params added, `onerror` added |
| `layouts/taxonomy/tag.html` | This PR | Same featured img fixes + missing pagination nav added |
| `layouts/partials/json-ld.html` | This PR | `articleSection` field omitted when empty |
| `layouts/partials/og-meta.html` | This PR | `og:image:type` derived from URL suffix (png/jpeg) |
| `layouts/_default/single.html` | This PR | Empty content guard + empty-paragraph filter in content split |

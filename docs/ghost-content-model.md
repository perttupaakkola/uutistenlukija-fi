# Ghost Content Model — Frontmatter → Ghost Field Mapping

## Overview

The pipeline produces Hugo markdown files with YAML frontmatter. When `GHOST_ENABLED=true`, `ghost_publisher.py` also creates Ghost posts via Admin API. This document maps every frontmatter field to its Ghost equivalent.

## Field Mapping

| Hugo Frontmatter | Ghost API Field | Transform | Notes |
|---|---|---|---|
| `title` | `title` | Direct | Max 300 chars for `meta_title` |
| `description` | `custom_excerpt` | Truncated to 300 chars | Also used as `meta_description` (500 chars) |
| `date` | `published_at` | ISO 8601 | Ghost auto-sets if omitted |
| `categories` | `tags[0]` | First category → primary tag | Ghost uses flat tags, no taxonomy distinction |
| `tags` | `tags[1..n]` | Appended after category | Deduped against category name |
| `image` | `feature_image` | Uploaded to Ghost storage | Unsplash/Pexels URL → Ghost-hosted copy |
| `image_alt` | `feature_image_alt` | Direct, max 125 chars | Falls back to title |
| `author` | *(not mapped)* | — | Always "Toimitus"; Ghost uses its own staff system |
| `source_name` | *(in HTML body)* | Rendered as attribution footer | `<div class="source-attribution">` block |
| `source_url` | *(in HTML body)* | Link in attribution footer | `rel="noopener nofollow"` |
| `source_domain` | *(not mapped)* | — | For internal tracking only |
| `journalist_note` | *(in HTML body)* | Rendered as `<aside>` block | Only for analysis/opinion pieces |
| `content_type` | `tags` (internal) | `analysis` → `#analysis` tag | Internal tags (prefixed `#`) hidden from readers |
| `editorial_reviewed` | *(not mapped)* | — | Pipeline-internal QA flag |
| `keywords` | *(not mapped)* | — | SEO keywords for Hugo `<meta>` only |
| `original_title` | *(not mapped)* | — | Source language title, internal reference |
| Content body (markdown) | `html` | HTML pass-through | Content already in HTML from Hugo pipeline |

## Ghost-Specific Additions

Fields set by `ghost_publisher.py` that don't exist in Hugo frontmatter:

| Ghost Field | Value | Source |
|---|---|---|
| `status` | `"published"` | Always published immediately |
| `meta_title` | Same as `title` | Truncated to 300 chars |
| `meta_description` | Same as `description` | Truncated to 500 chars |
| `html` (footer) | Source attribution div | Built from `source_name` + `source_url` |
| `html` (aside) | Journalist note | Built from `journalist_note` |

## Tag Behaviour

Ghost creates tags on first use (no pre-creation needed). Tag mapping:

```
Hugo categories: ["Talous"]     → Ghost tags: [{"name": "Talous"}]
Hugo tags: ["bkt", "inflaatio"] → Ghost tags: [{"name": "bkt"}, {"name": "inflaatio"}]
content_type: "analysis"        → Ghost tags: [{"name": "#analysis"}]  (internal, hidden)
```

Category is always the first tag (Ghost treats `tags[0]` as the primary tag for routing/filtering).

## Image Handling

1. Pipeline provides an image URL (Unsplash/Pexels/AI-generated)
2. `ghost_publisher.py` downloads the image
3. Uploads to Ghost via `POST /images/upload/` (multipart)
4. Ghost returns a hosted URL → set as `feature_image`

If upload fails, the post is created without a featured image (non-blocking).

## Dual-Publish Flow

```
run_pipeline.py
  ├── Step 3:  publish_articles()  → Hugo markdown files (always)
  ├── Step 3b: GhostPublisher.publish_batch()  → Ghost API (if GHOST_ENABLED=true)
  │            └── failure here is logged + warned, never blocks Hugo
  └── Step 4:  build_site()  → Hugo build (always)
```

## Content Parity Notes

- Ghost posts include source attribution and journalist notes as HTML in the body. Hugo renders these via partials (`source-attribution`, `journalist-note.html`).
- Hugo uses `type: analysis` for layout routing. Ghost uses `#analysis` internal tag.
- Hugo has reading time, breadcrumbs, related articles, newsletter CTA — these are template features, not content. Ghost handles equivalents via its own theme.
- Hugo SEO keywords (`keywords` frontmatter) are not pushed to Ghost. Ghost has its own SEO via meta fields.

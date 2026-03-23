# Article Frontmatter Schema

## Core Fields (Required)

```yaml
title: "Article Title"
date: 2026-03-23T10:00:00+00:00
categories:
  - Category Name
author: "Author Name"
draft: false
```

## Extended Fields (Optional)

### Editorial & Review

```yaml
# Journalist's editorial note (appears at end of article in styled box)
journalist_note: |
  Editorial explanation or context from the journalist.
  Supports Markdown formatting.

# Content classification
content_type: "article"  # or "analysis", "opinion"

# Has this piece been fact-checked?
editorial_reviewed: true
```

### Author Information

```yaml
author: "Full Author Name"
author_title: "Role or expertise"  # e.g., "Science Editor", "Tech Correspondent"
author_image: "/path/to/author-photo.jpg"
author_bio: "Short biography shown in author box"
```

### SEO & Metadata

```yaml
keywords:
  - "keyword 1"
  - "keyword 2"
lastmod: 2026-03-23T12:00:00+00:00  # Last modification date
```

### Tags

```yaml
tags:
  - topic
  - subject
  - keyword
```

## Content Type Layouts

### `article` (default)
Standard news article layout. Single column, normal reading experience.

### `analysis`
Analysis/opinion article layout:
- Multi-column (two-column on desktop for better readability)
- Wider content area (up to 1200px)
- Prominent author byline with editorial review badge
- Analysis category styling

### `opinion`
Reserved for future use. Currently renders same as `article`.

## Example: Analysis Article

```yaml
---
title: "Deep Dive: Finland's Digital Strategy 2026"
date: 2026-03-23T10:00:00+00:00
content_type: "analysis"
categories:
  - Teknologia
author: "Tech Editor Name"
author_title: "Technology & Innovation Editor"
author_image: "/img/authors/tech-editor.jpg"
author_bio: "Covers digital transformation and tech policy in Nordic region"
editorial_reviewed: true
journalist_note: |
  This analysis is based on interviews with 5 government officials
  and 3 industry experts. Data sources cited in article.
tags:
  - digitalization
  - policy
  - finland
keywords:
  - "digitaalinen strategia"
  - "teknologiapolitiikka"
---
```

## Example: News Article with Journalist Note

```yaml
---
title: "Breaking: New Law Approved"
date: 2026-03-23T14:30:00+00:00
categories:
  - Politiikka
author: "Political Reporter"
journalist_note: |
  **Update:** Law passed 127-to-45 in parliament.
  This note was added 2 hours after initial publication with latest vote count.
tags:
  - parliament
  - legislation
---
```

## Schema Notes

- Fields not listed here may be overridden by the pipeline during publishing
- `lastmod` is automatically set by the pipeline to current time on publication
- `author` defaults to "Toimitus" (Editorial) if not specified
- `draft: false` is required for articles to be published
- `content_type` should be lowercase (checked by schema validator)

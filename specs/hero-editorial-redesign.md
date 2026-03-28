# Spec: Editorial Grid-Breaking Hero
**Author:** Sara  
**Date:** 2026-03-28  
**Status:** Ready for implementation  
**Target file:** `layouts/partials/hero-cluster.html`

## Concept
Replace the current overlay/scrim hero with a CSS Grid-based asymmetric layout.
Image bleeds right (cols 4–10), text block overlaps left (cols 1–6), creating editorial tension.

## HTML Structure
Replace `.hero-cluster__lead` block with:

```html
<section class="hero-cluster-editorial" aria-labelledby="hero-cluster-title">
  <div class="hero-editorial__layout">
    <!-- Image Bleed (Right) -->
    <div class="hero-editorial__image-wrap">
      <picture>
        <!-- Keep existing AVIF/WEBP sources -->
        <img src="{{ $heroSrc }}" alt="{{ $alt }}" class="hero-editorial__img"
             loading="eager" fetchpriority="high" width="1200" height="800">
      </picture>
    </div>
    <!-- Text Block (Left, overlaps image) -->
    <div class="hero-editorial__content">
      <div class="hero-editorial__meta-top">
        {{ with $category }}<span class="hero-editorial__category">{{ . }}</span>{{ end }}
      </div>
      <h1 id="hero-cluster-title" class="hero-editorial__title">
        <a href="{{ $permalink }}">{{ $title }}</a>
      </h1>
      {{ with $excerpt }}<p class="hero-editorial__excerpt">{{ . }}</p>{{ end }}
      <div class="hero-editorial__meta-bottom">
        <span>{{ $date }}</span>
        {{ with $readingTime }}<span>{{ . }} min</span>{{ end }}
      </div>
    </div>
  </div>
</section>
```

## CSS

```css
/* 10-column grid, image bleeds right, text overlaps */
.hero-editorial__layout {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  grid-template-rows: 1fr;
  min-height: 70vh;
  overflow: hidden;
}

.hero-editorial__image-wrap {
  grid-column: 4 / 11; /* cols 4–10 */
  grid-row: 1;
  overflow: hidden;
}

.hero-editorial__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* Text overlaps image via z-index + grid overlap */
.hero-editorial__content {
  grid-column: 1 / 7; /* cols 1–6, overlaps cols 5 & 6 */
  grid-row: 1;
  background-color: #f4f1ea; /* parchment */
  padding: 4rem 4rem 4rem 3rem;
  z-index: 2;
  border-left: 4px solid #E3342F; /* vermilion anchor */
  box-shadow: 20px 20px 60px rgba(0, 0, 0, 0.08);
  align-self: center;
}

/* Typography — Alex to load webfonts via Google Fonts */
.hero-editorial__title {
  font-family: 'Zilla Slab', 'Playfair Display', serif;
  font-size: clamp(2.5rem, 4vw, 4.5rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: #111;
  margin: 1.5rem 0;
}

.hero-editorial__title a {
  text-decoration: none;
  color: inherit;
  transition: color 0.2s ease;
}

.hero-editorial__title a:hover {
  color: #E3342F;
}

.hero-editorial__excerpt {
  font-size: 1.125rem;
  line-height: 1.6;
  color: #444;
  margin-bottom: 2rem;
}

.hero-editorial__meta-top,
.hero-editorial__meta-bottom {
  font-family: 'Cabinet Grotesk', -apple-system, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 0.85rem;
  display: flex;
  gap: 1rem;
  align-items: center;
  color: #666;
}

/* Tablet (768px–1023px): vertical overlap */
@media (max-width: 1023px) {
  .hero-editorial__layout {
    grid-template-columns: 1fr;
  }
  .hero-editorial__image-wrap {
    grid-column: 1 / -1;
    grid-row: 1;
    height: 50vh;
  }
  .hero-editorial__content {
    grid-column: 1 / -1;
    grid-row: 2;
    width: 90%;
    margin: -10% auto 0 auto; /* pulls text box up over image */
    padding: 3rem 2rem;
  }
}

/* Mobile (<768px): tighter vertical overlap */
@media (max-width: 767px) {
  .hero-editorial__image-wrap {
    height: 40vh;
  }
  .hero-editorial__content {
    width: 95%;
    margin: -15% auto 0 auto;
    padding: 2rem 1.5rem;
    border-left-width: 3px;
  }
  .hero-editorial__title {
    font-size: 2rem;
    margin: 1rem 0;
  }
}
```

## Fonts to load (Google Fonts — free)
- Zilla Slab (serif, headlines): `https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@600;700&display=swap`
- Cabinet Grotesk (sans, metadata): via Fontshare `https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@700,500&display=swap`

## Implementation notes
- `$heroSrc`, `$alt`, `$permalink`, `$title`, `$excerpt`, `$category`, `$date`, `$readingTime` — wire from existing hero-cluster.html Hugo variables
- Dark mode: add `[data-theme="dark"] .hero-editorial__content { background-color: #1a1a18; color: #f0ede4; }`
- Add fonts to `layouts/partials/head.html` or baseof.html `<head>`

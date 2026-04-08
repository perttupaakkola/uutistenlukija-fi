# Spec: "Lue myös" Recirculation Block Redesign

**Context:** The current `related-articles.html` partial uses a generic 4-card grid with bordered cards. We are updating it to match the broadsheet editorial aesthetic (3 column, naked cards, heavy editorial rule) and replacing the stacked mobile view with a horizontal swipe carousel to save vertical space.

## 1. Template Changes (`layouts/partials/related-articles.html`)

1. **Reduce card count:**
   Change the loop/fetch limit from `first 4` to `first 3` so it perfectly maps to our 3-column desktop grid without an orphaned row.
   `{{- $related = first 3 $related -}}`

2. **Add naked category tag:**
   Between the image link and the headline, insert the category kicker. It should render with the specific category color class.
   ```html
   {{- $candidateCats := .Params.categories | default (slice) -}}
   {{- $cat := "" -}}
   {{- if gt (len $candidateCats) 0 -}}
     {{- $cat = (index $candidateCats 0) | lower -}}
   {{- end -}}
   
   {{- if $cat -}}
     <span class="related-card__cat related-card__cat--{{ $cat | urlize }}">{{ $cat }}</span>
   {{- end -}}
   ```

3. **Strip extra wrappers:**
   Remove any existing card UI wrappers that were meant for the bordered box look.

## 2. CSS Updates (`style.css`)

**Instructions for Alex:** Delete the *entire* existing `.related-articles` and `.related-card` blocks (including hover states and dark mode overrides for borders/backgrounds) and replace them with this:

```css
/* Container & Editorial Heading */
.related-articles {
  margin: 3rem 0 0;
  padding-top: 1.5rem;
  border-top: 4px solid var(--text); /* Heavy editorial rule */
}
.related-articles__heading {
  font: 800 1.25rem/1.2 var(--font-sans);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 1.5rem;
  color: var(--text);
}

/* Desktop Grid: 3 columns */
.related-articles__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1.5rem;
}

/* Naked Cards */
.related-card {
  display: flex;
  flex-direction: column;
  border: none;
  background: transparent;
  min-width: 0;
}

.related-card .article-image-link {
  margin-bottom: 0.75rem;
}

.related-card__body {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 0.35rem; /* Tight, cohesive grouping */
}

/* Category Kicker */
.related-card__cat {
  font: 700 0.65rem/1 var(--font-sans);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  margin-bottom: 0.15rem;
  display: block;
}
.related-card__cat--kotimaa { color: #2980b9; }
.related-card__cat--ulkomaat { color: #c0392b; }
.related-card__cat--talous { color: #9a6700; }
.related-card__cat--teknologia { color: #8e44ad; }
.related-card__cat--urheilu { color: #1e8449; }
.related-card__cat--kulttuuri { color: #9a5200; }
.related-card__cat--tiede { color: #0f6f5d; }

/* Headline */
.related-card__title {
  font: 700 1.05rem/1.3 var(--font-serif);
  margin: 0;
}
.related-card__title a {
  color: var(--text);
}
.related-card:hover .related-card__title a {
  color: var(--accent);
}

/* Meta / Timestamp */
.related-card__meta {
  font: 500 0.75rem/1 var(--font-sans);
  color: var(--text-muted);
  margin-top: 0.2rem;
}

/* Mobile Carousel (<= 680px) */
@media (max-width: 680px) {
  .related-articles__grid {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    scroll-snap-type: x mandatory;
    scrollbar-width: none; /* Firefox */
    -ms-overflow-style: none; /* IE/Edge */
    margin: 0 -1.5rem; /* Full bleed to screen edges */
    padding: 0 1.5rem 1rem; /* Pad left/right, give space for scrollbar */
    gap: 1.25rem;
  }
  .related-articles__grid::-webkit-scrollbar {
    display: none; /* Chrome/Safari */
  }
  .related-card {
    flex: 0 0 78%; /* Show first card + peek of second to afford swiping */
    scroll-snap-align: center;
  }
}
```

## 3. Dark Mode
Since we stripped the card background and borders, no explicit `.related-card` dark mode overrides are needed. The global `--text` variable handles the heading and headline text inversion, and `--text-muted` handles the timestamp. The category colors look great on dark mode out of the box.
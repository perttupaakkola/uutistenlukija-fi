# Homepage Hero Fixes (Desktop & Contrast)

## 1. Desktop Width Constraint
The `.hero-cluster` grid is currently bleeding infinitely across wide monitors, pulling the text to the absolute edges.
- Add `max-width: var(--max-width, 1100px);` to `body.is-home .hero-cluster`
- Add `margin-left: auto; margin-right: auto;` to center it.

## 2. Text Contrast on Bright Images
The lead article (e.g. "Pääsiäisen sää...") has white text completely lost against bright background images.
- The `.hero-scrim` gradient is too weak at the top.
- Update `.hero-scrim` to: `linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.5) 50%, transparent 80%)`
- Update `[data-theme="dark"] .hero-scrim` to: `linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.6) 50%, transparent 80%)`
- Add a heavy text-shadow to `.hero-scrim-title` and `.hero-scrim-excerpt` (e.g., `text-shadow: 0 2px 8px rgba(0,0,0,0.8)`).

## 3. Mobile Hero Detachment
In the mobile screenshot, the hero text is detaching from the image because the aspect ratios conflict.
- The parent container `.lead-article--hero .hero-scrim-link` is forced to `aspect-ratio: 4 / 3` on mobile (`max-width: 600px`).
- The child image `.hero-scrim-img` is forced to `aspect-ratio: 16 / 9`.
- Fix: Ensure the `.hero-scrim-img` uses `height: 100%` and `object-fit: cover` WITHOUT conflicting `aspect-ratio` rules on mobile, so it perfectly fills the `.hero-scrim-link` wrapper.

# Technical Architecture Research — Uutistenlukija.fi

**Author:** Monica | **Date:** 2026-03-22 | **Status:** Complete

---

## Part 1: Newsletter Platform Comparison

### Executive Summary

For uutistenlukija.fi's MVP (launch targeting ~500-1000 subscribers in month 1-2), the best choice is **Substack (free tier, no coding) or Ghost (if you want custom domain + higher control)**. For scaling beyond 5000 subscribers with revenue optimization, **Ghost or self-hosted Resend** are significantly cheaper than Substack due to Substack's 10% commission.

### 1. Substack

**Ideal for:** Quick MVP launch, zero-cost testing

**Pricing Model:** Free forever for free newsletters. 10% commission on paid subscriptions + Stripe fees (2.9% + $0.30).

**Cost Examples (monthly):**

| Subscribers | Substack Cost | Commission on Paid Revenue | Net Impact |
|-------------|---------------|---------------------------|------------|
| 500 | $0 | No paid tier yet | Free |
| 1,000 | $0 | If 50 paid @€5/mo = €250 rev | €32.50 loss to fees |
| 5,000 (w/ paid tier @€5/mo, 3% = 150 paid) | $0 | 150 paying = €750 rev | €97.50 loss to fees |

**Pros:**
- ✅ Zero setup (sign up, start sending in 10 minutes)
- ✅ Built-in audience discovery ("Notes" + promoted to new readers)
- ✅ Beautiful default templates
- ✅ Free forever for free newsletters
- ✅ No coding needed

**Cons:**
- ❌ 10% commission on paid subscriptions (biggest drawback)
- ❌ Limited segmentation (basic subscriber labels only)
- ❌ Limited automation (no auto-responder sequences)
- ❌ Restricted branding
- ❌ Poor analytics (minimal data beyond open/click rates)

**GDPR:** EU-compliant (though US servers). Explicit consent on signup. Limited consent preference management.

**Best for uutistenlukija:** MVP launch only (month 0-1). Migrate away once you hit 1,000 subscribers if you plan monetization.

### 2. Ghost (ghost.org)

**Ideal for:** Serious newsletter business, high control, long-term monetization

**Pricing Model:** Flat monthly fee based on subscriber count + 0% commission on paid revenue

**Cost Examples (monthly hosting):**

| Subscribers | Ghost Hosting Cost | Notes |
|-------------|-------------------|-------|
| 500 | ~$9/month (Starter) | Plus Stripe 2.9% on paid revenue |
| 1,000 | ~$19/month (Creator) | Much better than Substack if you do paid |
| 5,000 | ~$39/month (Creator) | For 500 paid subs @€5/mo: keep €2,425/month |
| 10,000 | ~$99/month (Professional) | For 2,000 paid subs @€5/mo: keep €9,700/month |

**Real cost comparison (with paid tier @€5/mo):**

- **Substack 5,000 list, 3% conversion (150 paid) = €750 revenue:**
  - Commission loss: €97.50. Net: €652.50
- **Ghost 5,000 list, 3% conversion (150 paid) = €750 revenue:**
  - Platform cost: €39, Stripe fees: ~€22. Net: €689
  - **Ghost advantage: €36.50/month**
- **At 5,000 paid subs (€25,000 revenue):**
  - Substack: Lose €3,250 to fees. Keep €21,750
  - Ghost: Pay €39 + €725 Stripe = €764. Keep €24,236
  - **Ghost advantage: €2,486/month**

**Pros:**
- ✅ 0% commission on paid revenue
- ✅ High customization (full control over design)
- ✅ Advanced segmentation (multiple tiers, custom segments)
- ✅ Automation (auto-responder sequences, conditional sends)
- ✅ Excellent analytics
- ✅ Open source option (can self-host)

**Cons:**
- ❌ Requires setup (15-30 minutes)
- ❌ No built-in audience discovery
- ❌ Steeper learning curve
- ❌ Additional cost per tier

**GDPR:** EU-compliant (Ghost is GDPR-first). Advanced consent management. Can be self-hosted in EU data centers. Full DPIA documentation available.

**Cost at scale (realistic 18-month projection):**
- Month 1-2: 500 subscribers → €9/month
- Month 3-4: 2,000 subscribers, 2% paid → €19/month
- Month 6: 5,000 subscribers, 3% paid → €39/month + keep €652/month revenue
- Month 12: 10,000 subscribers, 5% paid → €99/month + keep €2,425/month revenue

**Best for uutistenlukija:** Launch on Ghost for long-term scaling. 0% commission makes it break-even vs Substack at just 100 paid subscribers.

### 3. Buttondown

**Ideal for:** Minimalist indie creators, writers, tech-focused audiences

**Pricing Model:** Free to start, tiered by subscriber count (no commission)

| Subscribers | Buttondown Cost | Notes |
|-------------|----------------|-------|
| 500 | Free | Free tier covers up to 500 |
| 1,000 | ~$19/month | Cheapest paid tier |
| 5,000 | ~$49/month | Scales with list size |
| 10,000 | ~$99/month | Competitive with Ghost |

**Pros:** Free tier, no commission, simple interface, good API, affordable pricing, easy Substack import.

**Cons:** Less customization than Ghost, fewer integrations, no automation/sequences, smaller company, basic analytics.

**Best for uutistenlukija:** Good middle ground between Substack and Ghost.

### 4. Self-Hosted: Resend API (with Custom Frontend)

**Ideal for:** Maximum control, custom branding, tech-savvy teams

**Pricing:** Pay-per-email. $0.10 per 1,000 emails.

| Subscribers | Daily Volume | Monthly Volume | Resend Cost | Total |
|-------------|-------------|----------------|-------------|-------|
| 500 | 500 | 15,000 | $1.50 | $1.50 |
| 1,000 | 1,000 | 30,000 | $3.00 | $3.00 |
| 5,000 | 5,000 | 150,000 | $15.00 | $15-20 |
| 10,000 | 10,000 | 300,000 | $30.00 | $30-40 |

**Pros:** Cheapest per-email, maximum flexibility, own your data, no lock-in, integrates with existing codebase.

**Cons:** Requires 40-80 hours development, no built-in subscriber management, no templates, GDPR is your responsibility.

**Best for uutistenlukija:** NOT recommended for MVP. Only pursue at 50,000+ subscribers.

### Quick Comparison Table

| Feature | Substack | Ghost | Buttondown | Resend Self-Hosted |
|---------|----------|-------|------------|-------------------|
| Setup Time | 15 min | 1-2 hrs | 1-2 hrs | 40-80 hrs |
| Monthly Cost (500 subs) | $0 | $9 | $0 | $1.50 |
| Monthly Cost (5,000 subs) | $0 | $39 | $49 | $15-20 |
| Monthly Cost (10,000 subs) | $0 | $99 | $99 | $30-40 |
| Commission on Paid | 10% | 0% | 0% | 0% |
| Segmentation | Basic | Advanced | Moderate | Custom |
| Analytics | Basic | Excellent | Good | Custom |
| Custom Domain | ✅ | ✅ | ✅ | ✅ |
| Full Customization | ❌ | ✅✅ | ⚠️ | ✅✅ |
| GDPR | ✅ | ✅✅ | ✅ | Your responsibility |

### Recommendation

**Phase 1 (Month 0-2, MVP):** Substack free tier — fastest to launch, no cost, can test model.

**Phase 2 (Month 2-6, Scaling to 5k):** Migrate to Ghost — 0% commission, better analytics, segmentation. Export from Substack is 1-click.

**Phase 3 (Month 6+, Enterprise):** Stay on Ghost OR evaluate self-hosted Resend.

**Cost Projection:**
- Month 0-2: $0 (Substack)
- Month 3-6: $39/month (Ghost) + Stripe 2.9%
- Month 6-12: $99/month (Ghost) + Stripe
- **By month 12:** 10,000 subscribers, 500 paid @€5/mo = €2,500 revenue, €99 hosting cost. **Net: €2,401 monthly**

---

## Part 2: Analytics & Tracking Setup Guide

### The Analytics Stack for Uutistenlukija

4 layers needed:

1. **Layer 1:** Google Analytics 4 (already installed)
2. **Layer 2:** Heatmaps + Session recording
3. **Layer 3:** UTM tracking
4. **Layer 4:** Newsletter-specific conversion tracking

### Layer 1: GA4 — Baseline

**What you have:** GA4 already installed.
**What's missing:** Newsletter signup tracking + conversion funnels.

**Setup needed:**

1. **Custom event: "Newsletter Signup"**
   - Trigger: Form submission success
   - Parameters: `newsletter_segment`, `signup_source`, `referrer`

2. **Custom event: "Newsletter Conversion"**
   - Trigger: Paid conversion
   - Parameters: `subscription_tier`, `days_since_signup`

3. **Conversion goals:**
   - Goal 1: Newsletter signup (volume)
   - Goal 2: Paid conversion (revenue)

**GA4 Dashboard to create:** Newsletter signups (week-over-week), sources, free→paid conversion rate, average days to conversion, revenue per subscriber.

**Setup time:** 2-3 hours. **Cost:** €0.

### Layer 2: Heatmaps & Session Recording

**Recommendation: Microsoft Clarity (free)**

| Tool | Price | Best For | Setup Time |
|------|-------|----------|------------|
| Microsoft Clarity | FREE | Start here | 5 min |
| Hotjar | $99/mo | Advanced heatmaps + surveys | 15 min |
| FullStory | $99/mo | Full session replay | 15 min |
| Smartlook | €80/mo | European, GDPR-friendly | 15 min |

**Clarity Setup (5 minutes):**
1. Go to clarity.microsoft.com
2. Create account
3. Add domain
4. Copy tracking code → paste in `<head>` after GA
5. Add to consent banner

**What you'll see:** Heatmaps (scroll/click), rage clicks, dead clicks, session recordings.

**Free tier:** Up to 100,000 sessions/month, 30-day retention.

**Upgrade path:** Hotjar at €99/mo when you hit 50k+ monthly visitors.

### Layer 3: UTM Tracking Structure

**Format:** `?utm_source=PLATFORM&utm_medium=CHANNEL&utm_campaign=INITIATIVE&utm_content=DETAIL`

**Examples:**
1. Twitter: `utm_source=twitter&utm_medium=social&utm_campaign=newsletter_growth&utm_content=daily_digest_link`
2. Reddit: `utm_source=reddit&utm_medium=social&utm_campaign=seo_gap_1&utm_content=rsuomi_comment`
3. Newsletter: `utm_source=newsletter&utm_medium=email&utm_campaign=daily_digest&utm_content=2026-03-22`
4. Ampparit: `utm_source=ampparit&utm_medium=aggregator&utm_campaign=discovery&utm_content=rss_feed`

**Parameter legend:**
- `utm_source`: Where (twitter, facebook, reddit, ampparit, newsletter)
- `utm_medium`: Type (social, email, aggregator, paid, organic)
- `utm_campaign`: Initiative (newsletter_growth, seo_gap_1)
- `utm_content`: Specific detail (daily_digest_link, article_title)

GA4 automatically captures all UTM parameters. Use bit.ly for shortened URLs.

### Layer 4: Newsletter Conversion Funnel Tracking

| Funnel Stage | Goal | Tracking Method | Example Target |
|-------------|------|-----------------|----------------|
| Impressions | See newsletter CTA | GA4 event | 10,000/month |
| Signups | Subscribe to free | GA4 event | 500/month (5%) |
| Active Subscribers | Open emails | Email platform | 70% open rate |
| Click-through | Click article links | GA4 + UTM | 5-8% CTR |
| Free → Paid | Upgrade to premium | GA4 event | 3-5% of free subs |
| Revenue | MRR from subscribers | Email platform + GA4 | €2,500 MRR @1000 subs |

**GA4 Events to configure:**

1. `newsletter_signup` — params: signup_source, newsletter_segment, referrer
2. `newsletter_click` — params: link_url, email_segment, click_position
3. `subscription_purchase` — params: subscription_tier, subscriber_age, source_newsletter_segment

### Implementation Checklist

**Week 1:**
- [ ] Create GA4 custom events
- [ ] Install Microsoft Clarity
- [ ] Create UTM tracking spreadsheet
- [ ] Add newsletter form tracking

**Week 2:**
- [ ] Start using UTM on all social posts
- [ ] Create GA4 dashboard
- [ ] Run first heatmap analysis
- [ ] Document findings

**Month 2+:**
- [ ] Upgrade to Hotjar if needed
- [ ] Fine-tune conversion tracking
- [ ] Monthly review: best-converting channels

**Total cost:** €0 for MVP analytics stack.

---

## Part 3: Content Delivery Optimization

### Core Web Vitals Targets for News Sites

| Metric | Good | Needs Work | Failing |
|--------|------|------------|---------|
| LCP | < 2.5s | 2.5-4.0s | > 4.0s |
| FID | < 100ms | 100-300ms | > 300ms |
| CLS | < 0.1 | 0.1-0.25 | > 0.25 |

**Target:** "Good" on mobile (hardest test). 80% of Finnish news readers use phones.

### 1. CDN Optimization (Cloudflare — Already Installed)

**A. Enable Caching for HTML:**
- Cache TTL for HTML: 15-30 minutes
- Cache TTL for static assets (CSS/JS): 30 days

**B. Enable Cloudflare Polish (Image Optimization):**
- Enable "Polish" (lossy compression)
- Enable "WebP" format (20-30% smaller than JPG)
- Enable "Responsive Images"

**C. Enable "Early Hints" (HTTP/103 preloading):**
- Speed → Optimization → Early Hints → Enable

**Expected improvement:** LCP -0.5-1.0 seconds. Cost: €0.

### 2. Image Optimization Strategy

**Problem:** Each of 60+ articles has a hero image. Unoptimized = ~2MB each (should be 150-300KB).

**Solution — Responsive images:**

**Step 1:** Generate 3 sizes per image during Hugo build:
- Hero: 1200px (desktop), 800px (tablet), 400px (mobile)
- Thumbnail: 400px, 200px, 100px

**Step 2:** Use `<picture>` element:
```html
<picture>
  <source media="(min-width: 1024px)" srcset="hero-1200.webp">
  <source media="(min-width: 600px)" srcset="hero-800.webp">
  <img src="hero-400.webp" alt="...">
</picture>
```

**Step 3:** Lazy-load below-the-fold images:
```html
<img src="..." loading="lazy" alt="...">
```

**Quick wins (no dev needed):**
1. Enable Cloudflare Polish (saves 20% image size immediately)
2. Enable WebP (saves additional 10%)
3. Combined = 30% image size reduction

**Expected improvement:** LCP -0.3-0.8 seconds, page weight -40-50% on mobile.

### 3. JavaScript Lazy-Loading & Code Splitting

**Quick fix:** Defer non-critical JavaScript + use Cloudflare's "Rocket Loader" (FREE).

**Expected improvement:** FID -100ms. Cost: €0.

### 4. Reduce Cumulative Layout Shift (CLS)

**A. Add width/height to all images:**
```html
<!-- BAD: -->
<img src="..." alt="...">
<!-- GOOD: -->
<img src="..." alt="..." width="1200" height="600">
```

**B. Newsletter popup:** Use `transform: translateY(...)` instead of margin changes.

### 5. Hugo / Cloudflare Config

**Hugo config.toml additions:**
- Cache static assets for 720h (30 days)
- Cache HTML for 15m

**Cloudflare Caching Rules:**
- Rule 1: Cache HTML for 15 min (`URI path contains /`)
- Rule 2: Don't cache admin (`URI path contains /admin`)
- Rule 3: Cache static assets 30 days (`URI contains /css/ OR /js/ OR /images/`)

### Implementation Timeline & Cost

| Task | Priority | Dev Hours | Cost | Expected LCP Improvement |
|------|----------|-----------|------|--------------------------|
| Cloudflare Polish + WebP | P0 | 0 | €0 | -0.3s |
| Responsive images (3 sizes) | P0 | 8 | €0 | -0.8s |
| Lazy-load images | P0 | 2 | €0 | -0.3s |
| Rocket Loader (Cloudflare) | P0 | 0 | €0 | -0.2s |
| Image width/height tags | P0 | 4 | €0 | -0.1s |
| **Total P0 (quick wins)** | | **14 hours** | **€0** | **-1.7 seconds** |
| Minify CSS/JS | P1 | 1 | €0 | -0.1s |
| Service Worker caching | P2 | 8 | €0 | -2.0s |

**Expected result after optimization:**
- Current: LCP ~4-5s on mobile (slow)
- After P0: LCP ~2.5-3.0s (good)
- After P1-P2: LCP < 2.0s (excellent)

### Recommended Implementation Order

**Sprint 1 (This week):**
1. Enable Cloudflare Polish + WebP
2. Enable Rocket Loader
3. Add image width/height to template

**Sprint 2 (Next week):**
1. Implement responsive images (3 sizes)
2. Add lazy-load attributes

**Sprint 3 (If needed):**
1. Service Worker for offline reading
2. Critical CSS inline

### Monitoring & Ongoing

**Monthly checklist:**
- [ ] Run PageSpeed Insights (desktop + mobile)
- [ ] Check Clarity heatmaps for UX bottlenecks
- [ ] Monitor Cloudflare Analytics for cache hit rate (aim for 70%+)
- [ ] A/B test: Does faster load = more newsletter signups?

**Tools:** Google PageSpeed Insights (free), WebPageTest.org (free), Cloudflare Analytics (built-in).

**Cost:** €0 for everything.

# Uutistenlukija.fi — Autonomous Improvement Flywheel

> **STATUS (2026-07-23): dormant since 2026-03-28; kept for reference.** Owner directive: the mission is audience and trust growth (see AGENTS.md), not monetization. The Money domain below is retired — if the flywheel is revived, replace it with Trust & Accuracy (source quality, corrections, transparency).

## How It Works

A continuous loop runs every 4 hours, cycling through each domain. Each cycle:
1. **Observe** — Review current state of that domain
2. **Think** — Generate 1-3 specific, actionable improvements
3. **Post** — Send improvement ideas to the right Discord channel
4. **Execute** — Alex or another agent picks up and implements
5. **Measure** — Check if the improvement worked
6. **Feed back** — Results inform the next observation cycle

## Domain Rotation Schedule

Each heartbeat picks ONE domain (rotating). This keeps costs low while ensuring every domain gets attention multiple times per day.

| Slot | Domain | Discord Channel | What to Review |
|------|--------|----------------|----------------|
| 1 | Articles | #articles | Content quality, variety, freshness, Finnish language |
| 2 | Design | #design | Visual design, UX, readability, mobile experience |
| 3 | Development | #development | Pipeline reliability, build process, code quality |
| 4 | Marketing | #marketing | Traffic growth, social presence, distribution |
| 5 | SEO | #seo | Search rankings, meta tags, structured data |
| 6 | Operations | #operations | Process efficiency, agent coordination, automation |
| 7 | Metrics | #metrics | What to measure, dashboards, analytics |
| 8 | ~~Money~~ (retired 2026-07-23) | — | Replaced by Trust & Accuracy if flywheel is revived |

## Review Prompts Per Domain

### Articles (#articles → #improvement-ideas)
- Read the last 5 published articles
- Check: Are all 7 categories covered? Any gaps?
- Check: Is the Finnish natural? Any AI-isms slipping through?
- Check: Are headlines engaging but not clickbait?
- Check: Are we missing trending stories competitors have?
- Generate: 1-3 specific content improvements

### Design (#design → #improvement-ideas)
- Screenshot the live site (or review the HTML/CSS)
- Check: Does it look professional? Compare to Yle, HS, Iltalehti
- Check: Is mobile experience good?
- Check: Typography, spacing, colors, readability
- Check: Navigation — can users find what they want?
- Generate: 1-3 specific design changes with mockup descriptions

### Development (#development → #improvement-ideas)
- Check: Does the pipeline run without errors?
- Check: How long does each step take?
- Check: Any error patterns in recent runs?
- Check: Code quality — any technical debt?
- Check: Could we add new features to the pipeline?
- Generate: 1-3 specific technical improvements

### Marketing (#marketing → #improvement-ideas)
- Check: Do we have social media presence?
- Check: Are articles being shared anywhere?
- Check: Could we auto-post to X/social?
- Check: Newsletter integration?
- Check: How to grow readership?
- Generate: 1-3 specific growth actions

### SEO (#seo → #improvement-ideas)
- Check: sitemap.xml correct and updated?
- Check: Meta descriptions on all pages?
- Check: Structured data (NewsArticle schema)?
- Check: Page speed / Core Web Vitals
- Check: Internal linking between articles
- Check: Finnish keyword optimization
- Generate: 1-3 specific SEO improvements

### Operations (#operations → #improvement-ideas)
- Check: Is the flywheel itself running smoothly?
- Check: Are agents picking up and executing improvements?
- Check: Do we need more specialized agents?
- Check: Is the improvement → execution → measurement loop closing?
- Check: What's bottlenecked?
- Generate: 1-3 process improvements

### Metrics (#metrics → #improvement-ideas)
- Check: What are we measuring?
- Check: Do we have analytics installed?
- Check: Can we track article views, time on page?
- Check: Are we tracking pipeline reliability?
- Check: What data would help us make better decisions?
- Generate: 1-3 measurement improvements

### Money (#money → #improvement-ideas)
- Check: Current revenue (probably €0 to start)
- Check: What monetization is set up?
- Check: Traffic sufficient for ads yet?
- Check: Affiliate opportunities in articles?
- Check: Premium content possibilities?
- Generate: 1-3 monetization actions

## Execution Flow

1. Felix posts improvement idea to #improvement-ideas with [DOMAIN] tag
2. If it's a dev task → Alex picks it up in #development
3. If it's a research task → Monica picks it up in #research
4. If it needs a new agent → Felix creates one
5. After execution → post result back to the domain channel
6. Felix reviews result in next cycle → generates follow-up improvements

## Self-Improvement Rules

- If an improvement idea sits unexecuted for >48 hours, escalate priority
- If the same type of improvement keeps coming up, create an automated solution
- If a domain has no improvements for 3 cycles, dig deeper or expand scope
- Track which improvements had the biggest impact → do more of those
- Every week: review all improvements made, measure cumulative effect

## Execution Rate Guard

The flywheel should not generate ideas faster than agents can execute them. Check before posting:
- If `improvementsPosted - improvementsExecuted > 10`, **pause new posts** and instead review existing unexecuted ideas. Repost the highest-priority unexecuted one with a direct agent assignment, or mark stale ones as dropped.
- When execution catches up (backlog < 5), resume normal posting cadence.
- This prevents the #improvement-ideas channel from becoming a graveyard of ignored suggestions.

# Finnish Media Regulatory Landscape — uutistenlukija.fi (2026-03)

**Last updated:** 2026-03-22
**Purpose:** Practical regulatory overview for launching and operating uutistenlukija.fi as a Finnish online news aggregator.

---

## Executive summary

Uutistenlukija.fi is **not primarily facing a classic "broadcast licence" problem**. The bigger compliance burden is:

1. **Platform/intermediary obligations** (EU Digital Services Act)
2. **Data protection + cookie compliance** (GDPR + ePrivacy-style cookie rules implemented nationally)
3. **Advertising transparency / recognisability**
4. **Copyright and publisher-rights risk** (already covered in the legal brief)

For a Finnish online news aggregator, the most important practical rule is:

Operate as a transparent online intermediary/publisher website with clear contact details, conservative moderation/reporting processes, clear ad labelling, and strong privacy/cookie controls.

---

## 1) TRAFICOM / FINNISH REGULATORY REQUIREMENTS FOR ONLINE NEWS

### Bottom line

For a normal **website-based online news aggregator**, there does **not** appear to be a special Traficom-style publication licence requirement comparable to broadcasting licences for radio/TV.

That said, Traficom is still relevant because it sits in the broader Finnish communications regulatory environment, especially around:

- electronic communications regulation
- online service compliance in some communications contexts
- domain / communications infrastructure issues
- certain accessibility / communications-law-adjacent topics

### Practical interpretation for uutistenlukija

**What uutistenlukija likely does not need:**

- no traditional broadcast licence merely for operating a website
- no newsroom permit just to publish online aggregated news content
- no special Traficom registration simply because the service is a web news site

**What uutistenlukija does need in practice:**

Even without a specific "news site licence", the product should still meet standard Finnish/EU online service expectations:

- [ ] clear publisher/operator identity
- [ ] contact information visible on site
- [ ] clear terms/privacy/cookie documentation
- [ ] ad transparency
- [ ] complaint / takedown / notice handling process
- [ ] lawful processing of analytics, email signup, and user data

### Important nuance: journalism vs. platform regulation

A Finnish news website can sit in multiple regulatory buckets at once:

- **media/journalistic norms** (ethical expectations, credibility, corrections)
- **consumer/marketing law** (if it monetizes via ads/sponsorships/subscriptions)
- **data protection law** (if it tracks users or collects emails)
- **DSA intermediary obligations** (if it hosts, organises, ranks, or enables user interaction/content distribution in relevant ways)

### Self-regulation also matters in Finland

Even when not legally mandatory, Finnish media credibility is influenced by self-regulatory norms such as:

- **JSN / Council for Mass Media** style editorial standards
- correction culture
- transparency around advertising and sponsored material

### Practical recommendation

Even if uutistenlukija is not formally entering every traditional-media self-regulatory structure on day one, it should still behave like a credible media actor:

- corrections page/process
- visible editorial/publisher contact
- "how we source content" explainer
- transparent sponsorship labelling

---

## 2) EU DIGITAL SERVICES ACT (DSA) OBLIGATIONS FOR NEWS AGGREGATORS

### Why the DSA matters here

The DSA applies broadly to **online intermediary services** offered in the EU. A news aggregator can fall under DSA logic if it:

- stores or presents third-party information
- ranks/displays content from third parties
- allows reporting/flagging of content
- carries ads or recommendation logic
- potentially hosts user-submitted or partner-submitted material

Even if uutistenlukija is relatively small, the DSA still matters because **smaller services are covered too**, though with lighter obligations than very large platforms.

### Most relevant DSA obligations for uutistenlukija

#### A. Transparency around terms and restrictions

If the service has rules about what content/sources it will show, remove, deprioritise, or exclude, those rules should be described clearly.

**Practical implementation:**

- [ ] Terms of Use explain what kinds of content/sources may be excluded
- [ ] explain anti-spam / low-quality-source / legality criteria
- [ ] explain source allowlist / exclusion logic at high level if relevant

#### B. Notice-and-action / illegal content reporting

If users or rights holders need to report unlawful content or infringements, the site should have a usable reporting route.

**Practical implementation:**

- [ ] "Report content" / rights-holder contact route
- [ ] dedicated email for copyright/takedown requests
- [ ] internal process for logging and reviewing notices
- [ ] response workflow for removal / correction / restriction decisions

#### C. Statement of reasons for restrictions/removals

When a platform removes or restricts user/business content in covered contexts, the DSA pushes toward transparency around why.

For uutistenlukija this matters most if the service later includes:

- partner submissions
- user accounts
- comments
- publisher profiles
- claim/review workflows

**Practical implementation:**

- [ ] if content providers/users can submit material, document why content is rejected/removed
- [ ] keep internal moderation/restriction logs

#### D. Ad transparency

The DSA requires advertising to be recognisable as advertising and gives users more clarity about who is behind ads and, in large-platform contexts, why they are seeing them.

**Practical implementation:**

- [ ] ads clearly labelled "mainos", "sponsoroitu", etc.
- [ ] sponsored blocks visually distinct from editorial content
- [ ] identify advertiser/brand where reasonable
- [ ] avoid manipulative/dark-pattern ad placements

#### E. Ban/restrictions on certain targeting practices

The DSA increases scrutiny around ad targeting, especially:

- sensitive personal data targeting
- child-directed targeting
- opaque ad explanations

**Practical implementation:**

- [ ] avoid using sensitive-data audiences
- [ ] avoid any targeting that could imply profiling based on health, religion, politics, etc.
- [ ] do not rely on children/minors as an ad-targeting segment

#### F. Recommender / ranking transparency

If uutistenlukija ranks stories algorithmically, there should be some transparency around the main ranking logic.

**Practical implementation:**

- [ ] explain basic ranking factors (freshness, source trust, category fit, relevance)
- [ ] if personalisation exists later, explain it clearly
- [ ] ideally provide some non-personalised/default sorting option

### DSA risk assessment for uutistenlukija

At launch, uutistenlukija is unlikely to face the heaviest VLOP/VLOSE obligations. But it should still behave as if the following are required from day one:

- clear terms
- clear notice/reporting mechanism
- ad recognisability
- source/ranking transparency at a basic level
- internal moderation/takedown logging

### Recommended DSA minimum package

- [ ] Terms of Use
- [ ] Content/reporting contact
- [ ] Copyright complaint route
- [ ] Sponsored/ad labelling policy
- [ ] Short "How stories are selected" explainer
- [ ] Internal moderation/notice log

---

## 3) FINNISH ADVERTISING STANDARDS — ICC CODE / MEN / CONSUMER LAW

### Core principle

In Finland, the most important practical advertising rule for a news product is simple:

**Marketing must be clearly recognisable as marketing.**

This matters especially for uutistenlukija because it may eventually combine:

- editorial-looking content
- native sponsorships
- newsletter sponsor blocks
- affiliate links
- category sponsorships

### Mainonnan eettinen neuvosto (MEN)

The Finnish **Mainonnan eettinen neuvosto** (Council of Ethics in Advertising), under Keskuskauppakamari, issues statements on whether advertising or commercial marketing conduct is contrary to good practice or recognisable as marketing, with reference to the **ICC Marketing Code**.

From the Chamber of Commerce description, MEN's role is to assess whether advertising or commercial conduct is contrary to good practice or recognisable as marketing, taking into account ICC rules.

### Practical meaning for uutistenlukija

Even when not directly fined by MEN in a traditional enforcement sense, poor advertising transparency can create:

- reputational risk
- complaints
- advertiser risk
- consumer-law scrutiny

### Key practical standards

#### A. Recognisability of advertising

Users must be able to tell, without confusion, when something is an ad or sponsored placement.

**Required practical stance:**

- [ ] label advertorials clearly as **Mainos**, **Kaupallinen yhteistyö**, or equivalent
- [ ] do not style native ads to look indistinguishable from newsroom/editorial content
- [ ] newsletter sponsor blocks must be clearly marked
- [ ] affiliate-heavy content should not masquerade as neutral editorial analysis

#### B. No misleading commercial presentation

Marketing should not be deceptive about:

- who is speaking
- what is being sold/promoted
- whether content is editorial or sponsored
- pricing/subscription terms

**Required practical stance:**

- [ ] subscription offers show real pricing and recurring billing conditions clearly
- [ ] trial-to-paid conversion terms visible
- [ ] no fake urgency or misleading countdowns
- [ ] no disguised advertorials

#### C. Special care around vulnerable groups / minors

If the service reaches minors or broad family audiences, marketing practices should be extra cautious.

**Required practical stance:**

- [ ] do not target minors with profiling-based ads
- [ ] avoid manipulative growth loops around young users
- [ ] keep sponsored/paid messages especially clear

### Best-practice ad labelling examples

Recommended Finnish labels:

- **Mainos**
- **Sponsoroitu**
- **Kaupallinen yhteistyö [brandin nimi]**
- **Sisältää mainoslinkkejä** (for affiliate contexts)

### Practical recommendation

Before launching any native or sponsored content, define a written policy covering:

- labels to use
- where labels appear
- typography/visual treatment
- whether advertisers can influence ranking or category placement
- internal approval rules for sponsored content

---

## 4) COOKIE / GDPR COMPLIANCE FOR FINNISH NEWS SITES

### Why this is a major issue

For news sites, data protection risk usually comes from:

- analytics tools
- adtech trackers
- newsletter signup forms
- remarketing pixels
- user behaviour measurement
- cookie banners that are non-compliant or manipulative

### GDPR fundamentals relevant to uutistenlukija

The Data Protection Ombudsman's Office highlights standard GDPR principles such as:

- lawful, fair and transparent processing
- purpose limitation
- data minimisation
- accuracy
- storage limitation
- confidentiality and security

### Practical implication

Every personal-data activity must map to:

- a purpose
- a legal basis
- retention logic
- a controller/processor relationship

### Main compliance areas for uutistenlukija

#### A. Privacy notice

- [ ] Privacy Policy published before launch
- [ ] identify controller entity clearly
- [ ] explain what data is collected
- [ ] explain why data is collected
- [ ] explain legal basis (analytics, newsletter, customer communication, etc.)
- [ ] identify processors/tools where relevant
- [ ] explain retention periods or logic
- [ ] explain user rights and contact route

#### B. Newsletter signup compliance

If uutistenlukija collects email addresses:

- [ ] signup form clearly states what the user is subscribing to
- [ ] consent wording is specific and understandable
- [ ] double opt-in strongly recommended
- [ ] unsubscribe mechanism in every email
- [ ] no bundling newsletter consent into unrelated consent boxes

#### C. Cookie / tracking consent

For Finnish/EU news sites, non-essential cookies and trackers generally require prior consent.

**Practical implementation:**

- [ ] analytics cookies reviewed: are they strictly necessary? usually **no**
- [ ] ad/remarketing cookies blocked until consent
- [ ] reject option as visible as accept option
- [ ] no deceptive button hierarchy / dark patterns
- [ ] consent categories clear (necessary / analytics / marketing)
- [ ] consent records stored if CMP used
- [ ] users can later change consent settings easily

#### D. Processor contracts and tooling

If using third-party tools (GA4, Clarity, email platform, CMP, hosting):

- [ ] data processing roles documented
- [ ] vendor terms / DPAs checked where needed
- [ ] cross-border transfer issues considered
- [ ] only necessary tools installed at launch

#### E. Data subject rights workflow

Users must be able to exercise rights such as access, rectification, erasure, objection, etc.

**Practical implementation:**

- [ ] privacy contact email visible
- [ ] internal process to answer requests within one month
- [ ] simple internal log of requests + responses

### Cookie-banner specifics for Finnish news sites

This is where many media sites become risky.

**Avoid these patterns:**

- ❌ "Accept all" big button + hidden reject path
- ❌ pre-ticked consent boxes
- ❌ dropping analytics/marketing cookies before consent
- ❌ vague language like "by continuing you accept everything"
- ❌ making rejection materially harder than acceptance

**Safer pattern:**

- ✅ equal prominence for **Accept** and **Reject**
- ✅ granular settings available
- ✅ necessary cookies separated from optional ones
- ✅ consent can be changed later from footer/account/settings
- ✅ plain-language explanations

### What uutistenlukija should do at launch

**Minimum privacy/cookie package:**

- [ ] Privacy Policy live
- [ ] Cookie Policy live
- [ ] consent banner live before non-essential cookies fire
- [ ] GA4 and Clarity only after consent if configured as non-essential tracking
- [ ] newsletter consent wording reviewed
- [ ] privacy contact route live

---

## 5) WHAT IS LEGALLY / REGULATORILY MOST IMPORTANT FOR UUTISTENLUKIJA

### Priority order

**P0 — Must be in place by launch**

- [ ] Privacy Policy
- [ ] Cookie Policy
- [ ] consent banner with real reject option
- [ ] clear operator/contact details
- [ ] clear ad/sponsorship labelling
- [ ] takedown/reporting contact
- [ ] Terms of Use

**P1 — Strongly recommended immediately**

- [ ] "How we select stories" transparency page
- [ ] moderation/notice handling log
- [ ] corrections policy
- [ ] internal sponsored-content labelling guideline

**P2 — As product complexity increases**

Needed especially if comments, accounts, personalization, or partner submissions are added:

- [ ] formal moderation workflow
- [ ] explanation of recommender/personalisation logic
- [ ] clearer statements of reasons for content restrictions
- [ ] more advanced DSA governance and reporting

---

## 6) REGULATORY RISK ASSESSMENT

### Low risk if handled properly

- operating a basic online news website
- linking out to third-party sources
- collecting newsletter signups with proper consent
- serving clearly labelled display ads

### Medium risk

- using analytics / adtech without robust cookie consent
- ambiguous native advertising
- poor takedown/reporting responsiveness
- opaque ranking or partner-preferential placement

### High risk

- misleading advertorials disguised as editorial content
- using high-risk publisher snippets beyond allowed policy
- marketing/cookie dark patterns
- sensitive-data targeting or non-transparent profiling

---

## Final Assessment

### Key conclusion

For uutistenlukija, the regulatory landscape is **manageable** if the service launches as a transparent, conservative, well-documented digital publisher/aggregator.

The biggest compliance traps are **not** classic media licensing. They are:

1. **Cookie/GDPR implementation**
2. **DSA-style notice/transparency obligations**
3. **Clear separation of editorial and advertising**
4. **Copyright/publisher-rights discipline**

### Best next move

Translate this into a short implementation checklist for launch:

- **Alex:** consent gating, takedown/report flow, transparency pages
- **Sara:** ad/sponsor visual labelling system
- **Felix:** terms/policies/publisher identity decisions
- **Monica:** policy wording + QA review

### Working operating principle

Launch as a conservative, clearly labelled, privacy-respecting aggregator — not as a "growth-hacked" media site.

That lowers legal risk and strengthens trust at the same time.

# OPE-219 Private Utility Packet: Porssisahkon varttihintojen ajoitus

Generated: 2026-06-21 19:08 UTC

Status: private distribution-prep artifact only. No public post, schedule, Buffer/X/social API call, outbound email, spend, payment, credential, provider, or account change was performed.

## Approval Request

Approve or reject one restrained utility placement for the article about pörssisähkön varttihinnat and timing household electricity use.

Recommended approval: newsletter utility block or LinkedIn post with the timestamped copy below.

Do not approve yet: paid boosting, automated reposting, broad Facebook group posting, DMs, or any evergreen advice that implies these exact prices are current after the article's day.

## Why This Is Worth Testing

- Talous remains materially under target: `static/api/category-stats.json` currently reports Talous 342 articles, 10.3% versus a 20% target.
- The article is categorized as Kotimaa, but the user problem is household money and energy timing, making it useful Talous-adjacent distribution inventory.
- The hook is practical: pörssisähkön halvin vartti was not at night in the inspected example, so readers may benefit from checking current varttihinnat before flexible electricity use.

## Article

Local source:

```text
projects/uutistenlukija/content/posts/2026-06-19-porssisahkon-hinta-vaihtelee-rajusti-halvimmat-vartit-loytyv.md
```

Public path expected from the slug:

```text
https://uutistenlukija.fi/posts/2026-06-19-porssisahkon-hinta-vaihtelee-rajusti-halvimmat-vartit-loytyv/
```

Approved-link template:

```text
https://uutistenlukija.fi/posts/2026-06-19-porssisahkon-hinta-vaihtelee-rajusti-halvimmat-vartit-loytyv/?utm_source=newsletter&utm_medium=owned&utm_campaign=spot_price_timing&utm_content=timestamped_check_v1
```

## Copy For Approval

Primary newsletter/LinkedIn utility copy:

```text
Pörssisähkön halvin hetki ei aina osu yöhön.

Uutistenlukijan jutussa torstain halvin vartti alkoi kello 16.00 ja maksoi 6,969 snt/kWh. Kallein vartti alkoi kello 7.15 ja maksoi 22,336 snt/kWh.

Jos sähkönkäyttöä voi ajoittaa, tarkista ainakin nämä ennen pesukonetta, auton latausta tai muuta joustavaa kulutusta:
- seuraavan päivän varttihinnat päivittyvät yleensä noin kello 14 jälkeen
- vertaa halvinta varttia halvimpaan tuntiin, koska ne voivat kertoa eri asioita
- älä oleta, että yö on aina halvin
- katso myös oma sähkösopimus, siirtohinta ja verot ennen säästöpäätelmiä

Esimerkin hinnat ovat jutun julkaisuhetken tietoja, eivät tämän päivän hintaneuvo.

Lue juttu:
[APPROVED_UTM_URL]
```

Short variant:

```text
Pörssisähkön ajoitus ei ole enää pelkkää yöajastusta. Tässä Uutistenlukijan esimerkissä halvin vartti alkoi kello 16.00, kun kallein vartti osui aamuun. Ennen joustavaa sähkönkäyttöä kannattaa tarkistaa nykyiset varttihinnat ja muistaa, että jutun hinnat ovat julkaisuhetken esimerkki. [APPROVED_UTM_URL]
```

## Risk Controls

- Treat all price numbers as time-specific historical examples from the article, not current electricity advice.
- Keep the timestamp sentence in any public copy unless the copy is rewritten around fresh price data.
- Do not promise savings; pricing depends on current market prices, contract terms, siirtohinta, taxes, and household flexibility.
- Do not frame this as financial advice.
- Before public use, re-check the article URL, headline, and UTM.
- If the copy is reused later, either refresh the price facts from a current source or explicitly describe the article as an example of why timing can vary.

## Measurement

Measurement window: first 72 hours after approved publication.

Primary metric: sessions to the article from `utm_campaign=spot_price_timing`.

Secondary metric: click-through from the article to `/categories/talous/` or other household-money/energy content if available in analytics or referrer logs.

Decision rule:

- If the approved placement drives meaningful sessions with acceptable engagement, prepare one more household-money utility draft from the no-public backlog.
- If sessions are near zero, keep the angle but test a more specific audience such as EV owners or newsletter readers interested in household costs.
- If readers challenge freshness or advice framing, pause reuse and rewrite as a clearly historical example or route to editorial review.

## Approval Choices

- Approve newsletter utility placement using the primary copy and UTM URL.
- Approve LinkedIn placement using the primary copy and UTM URL.
- Approve the short variant only.
- Reject public distribution for now and keep this as private draft inventory.

## Evidence Inputs

- OPE-207 backlog: `projects/uutistenlukija/artifacts/ope-207/no-public-distribution-angle-backlog.md`
- Source article frontmatter/body inspected locally.
- Current category stats: Talous 342 / 10.3% versus 20% target.

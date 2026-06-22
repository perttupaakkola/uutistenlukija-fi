# OPE-216 Private Approval Packet: Maksukorttihuijaus matkavarauksen jälkeen

Generated: 2026-06-21 18:44 UTC

Status: private approval packet only. No public post, schedule, Buffer/X/social API call, outbound email, spend, payment, credential, provider, or account change was performed.

## Approval Request

Approve or reject one restrained public distribution test for the Talous article about a travel-booking-related maksukorttihuijaus.

Recommended approval: LinkedIn or newsletter utility placement with the checklist copy below.

Do not approve yet: Facebook/local group posting, paid boosting, DMs, automated reposting, or broad social syndication.

## Why This Is Worth Testing

- Talous remains materially under target: `static/api/category-stats.json` currently reports Talous 342 articles, 10.3% versus a 20% target.
- The source article is editorial-reviewed and practical: a finance-sector expert was fooled by a travel-booking-related WhatsApp payment flow, which gives the story direct consumer-safety value.
- The experiment can be measured with UTM links and stopped after one approved post or placement.

## Article

Local source:

```text
projects/uutistenlukija/content/posts/2026-06-19-finanssialan-kokenut-asiantuntija-joutui-maksukorttihuijauks.md
```

Public path observed in the build:

```text
https://uutistenlukija.fi/posts/2026-06-19-finanssialan-kokenut-asiantuntija-joutui-maksukorttihuijauks/
```

Approved-link template:

```text
https://uutistenlukija.fi/posts/2026-06-19-finanssialan-kokenut-asiantuntija-joutui-maksukorttihuijauks/?utm_source=linkedin&utm_medium=social&utm_campaign=consumer_safety_card_fraud&utm_content=checklist_v1
```

## Copy For Approval

Primary LinkedIn/newsletter copy:

```text
Finanssialan kokenut asiantuntijakin voi joutua maksukorttihuijauksen uhriksi, kun viesti näyttää liittyvän oikeaan matkavaraukseen.

Uutistenlukijan jutun ydin on käytännöllinen: jos maksulinkki tulee WhatsAppissa tai viestinä, pysähdy ennen korttitietojen syöttämistä.

Tarkista ainakin nämä:
- avaa varauspalvelu itse selaimesta tai sovelluksesta, älä viestin linkistä
- vertaa maksupyyntöä alkuperäiseen varaukseen ja veloitusehtoihin
- suhtaudu "nollavarausta" lupaavaan korttikyselyyn varauksella
- ota epäselvässä tilanteessa yhteys majoituspaikkaan virallista kautta
- sulje kortti nopeasti, jos tilille ilmestyy outo katevaraus

Lue juttu:
[APPROVED_UTM_URL]
```

Short variant:

```text
Matkavarauksen maksulinkki voi näyttää uskottavalta, vaikka se olisi huijaus. Uutistenlukijan Talous-juttu kertoo tapauksesta, jossa kokenut finanssialan asiantuntija syötti korttitiedot matkavaraukseen liittyneeltä näyttäneen viestin jälkeen. Ennen korttitietoja: avaa varauspalvelu itse, tarkista maksu virallisesta kanavasta ja pysähdy, jos "nollavaraus" muuttuu katevaraukseksi. [APPROVED_UTM_URL]
```

## Risk Controls

- Keep Booking.com references tied to the article/source attribution. Do not claim an independently verified causal link between a data leak and this individual case.
- Do not shame the victim or imply professional experience should have prevented the fraud.
- Avoid fearbait wording such as "kaikki matkavaraukset ovat vaarassa".
- Do not frame the post as financial or legal advice.
- Before public use, re-check the article URL, headline, and UTM.
- If comments raise attribution or trust concerns, stop variants and route the copy to Monica/editorial review before reuse.

## Measurement

Measurement window: first 72 hours after approved publication.

Primary metric: sessions to the article from `utm_campaign=consumer_safety_card_fraud`.

Secondary metric: click-through from the article to `/categories/talous/` or other Talous content if available in analytics/referrer logs.

Decision rule:

- If the approved placement drives meaningful sessions with acceptable engagement, prepare one more Talous utility-angle draft from the private backlog.
- If sessions are near zero, keep the angle but test a more specific audience/channel before broadening.
- If trust concerns appear, pause reuse and ask Monica for editorial-risk review.

## Approval Choices

- Approve LinkedIn/newsletter utility placement using the primary copy and UTM URL.
- Approve the short variant only.
- Reject public distribution for now and keep this as private draft inventory.

## Evidence Inputs

- OPE-212 brief: `projects/uutistenlukija/artifacts/ope-212/private-experiment-brief-card-fraud.md`
- Source article frontmatter/body inspected locally.
- Current category stats: Talous 342 / 10.3% versus 20% target.

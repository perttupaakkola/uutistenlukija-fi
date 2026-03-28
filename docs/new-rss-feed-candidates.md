# New RSS/Source Feed Candidates

**Deliverable #49** | Monica | 2026-03-26
**Scope:** Feeds NOT in current `source-allowlist-rss.md`. Ranked by value, with DSM Art. 15 legal risk flags.

## Ranked Feed List

| Rank | Lähde                      | URL                                                            | Kieli | Fit                                     | Päivitystahti              | Legal risk    | Huomio                                                                         |
|------|----------------------------|----------------------------------------------------------------|-------|----------------------------------------|---------------------------|---------------|--------------------------------------------------------------------------------|
| 1    | Hämeen Sanomat             | https://www.hameensanomat.fi/feed/rss/                         | FI    | Kotimaa / alue                          | korkea (päivittäin useita) | 🟡 medium     | Sanoma-regional; headline-only + link only                                     |
| 2    | Keskisuomalainen           | https://www.ksml.fi/feed/rss/                                  | FI    | Kotimaa / alue / urheilu                | korkea                     | 🟡 medium     | Keskimaa/Jyväskylä-kulma, hyvä alueellinen lisä                                |
| 3    | Karjalainen                | https://www.karjalainen.fi/feed/rss/                           | FI    | Kotimaa / alue                          | keskitaso-korkea           | 🟡 medium     | Itä-Suomen hyvä täydennys                                                      |
| 4    | Etelä-Suomen Sanomat (ESS) | https://www.ess.fi/feed/rss/                                   | FI    | Kotimaa / alue / urheilu                | keskitaso-korkea           | 🟡 medium     | Lahden alue, hyvä alueellinen diversiteetti                                    |
| 5    | Maaseudun Tulevaisuus      | https://www.maaseuduntulevaisuus.fi/feeds/maaseuduntulevaisuus | FI    | Talous / kotimaa / ruoka / maaseutu     | korkea                     | 🟡 medium     | Erittäin hyvä talous+maaseutu-niche, mutta kaupallinen publisher               |
| 6    | Kansan Uutiset             | https://www.ku.fi/feed/                                        | FI    | Politiikka / kotimaa                    | matala-keskitaso           | 🟢 low–medium | Lisää poliittista näkökulmadiversiteettiä; monitoroi mielipidesisältöä         |
| 7    | Demokraatti                | https://demokraatti.fi/feed/                                   | FI    | Politiikka / työelämä                   | matala-keskitaso           | 🟢 low–medium | Hyvä puoluekentän vastapaino Verkkouutisille                                   |
| 8    | Uutisvuoksi                | https://www.uutisvuoksi.fi/feed/rss/                           | FI    | Kotimaa / alue                          | keskitaso                  | 🟡 medium     | Imatra/Etelä-Karjala; hyödyllinen jos halutaan koko Suomen peitto              |
| 9    | Suomenmaa                  | https://www.suomenmaa.fi/feed/                                 | FI    | Politiikka / kotimaa / maaseutu         | matala-keskitaso           | 🟢 low–medium | Keskustalainen näkökulma; hyvä diversiteettiin                                 |
| 10   | io-tech                    | https://www.io-tech.fi/feed/                                   | FI    | Teknologia                              | korkea                     | 🟢 low        | Paras uusi suomalainen tech-feed, vahva hardware/AI/PC-uutisissa               |
| 11   | Hufvudstadsbladet (HBL)    | https://www.hbl.fi/rss                                         | SV    | Kotimaa / urheilu / alue                | korkea                     | 🟡 medium     | Ei suomenkielinen, mutta hyvä suomenruotsalainen näkökulma                     |
| 12   | Finland Today              | https://finlandtoday.fi/feed/                                  | EN    | Kotimaa / ulkomaat / Finland-in-English | matala-keskitaso           | 🟢 low        | Hyvä expat/English-angle, ei prioriteetti launchiin                            |
| 13   | Helsinki Times             | https://www.helsinkitimes.fi/?format=feed&type=rss             | EN    | Kotimaa / Finland-in-English            | matala-keskitaso           | 🟢 low        | Feed näkyy olemassa, mutta 403 automaattihaussa — needs manual verification    |
| 14   | Stara                      | https://www.stara.fi/feed/                                     | FI    | Viihde / lifestyle / kevyt uutinen      | korkea                     | 🟢 low–medium | Jos halutaan kevyempi viihde-feed ilman IL Viihteen riippuvuutta               |
| 15   | ArcticStartup              | https://arcticstartup.com/feed/                                | EN    | Talous / teknologia / startup           | matala                     | 🟢 low        | 403 challenge nyt; lupaava myöhemmäksi, ei launch-prio                         |

## DSM Art. 15 / Operating Policy Flags

**Varovaisuus (headline-only + max 120 chars preview + link-through only):**
- Hämeen Sanomat, Keskisuomalainen, Karjalainen, ESS, Uutisvuoksi, Maaseudun Tulevaisuus — kaupallisia lehtiä
- HBL — kaupallinen publisher

**Matalampi riski (sama headline-first-politiikka varmuuden vuoksi):**
- Kansan Uutiset, Demokraatti, Suomenmaa, io-tech, Finland Today, Helsinki Times

## Not Recommended Now

- **Turkulainen** — feed käytännössä vuodelta 2020, ei arvoa
- **Liiga / Palloliitto** — ei varmennettua toimivaa public RSS:ää
- **Mikrobitti / Tivi / Tietokone** — redirect/404/epäselvä nykytila
- **Daily Finland** — feed antoi 500-virheen

## Suggested Rollout Order

**P0 (first):** Hämeen Sanomat, Keskisuomalainen, Karjalainen, ESS, Maaseudun Tulevaisuus, io-tech
**P1:** Kansan Uutiset, Demokraatti, Suomenmaa
**P2:** HBL, Finland Today, Helsinki Times, Stara, ArcticStartup

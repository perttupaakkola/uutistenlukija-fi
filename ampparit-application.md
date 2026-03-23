# Ampparit.com — Submission Application for uutistenlukija.fi

**Last updated:** 2026-03-22
**Purpose:** Ready-to-submit application package for Perttu.

---

## HOW TO SUBMIT

**Submission URL:** https://www.ampparit.com/tietoa/mukaan

**Process:**

1. Go to `ampparit.com/tietoa/mukaan`
2. Fill in the form fields below
3. Check the terms box
4. Click "Lähetä hakemus"

**Important timing notes from Ampparit (confirmed from live site):**

- Applications reviewed **four times per year** (quarterly batches)
- They want time to observe the source before deciding — submit after 2-4 weeks of consistent publishing
- Plan for 4-12 week decision turnaround

**Contact email:** ampparit@ampparit.com

---

## FORM FIELD VALUES

**Median nimi:**

```
Uutistenlukija.fi
```

**Yhteyshenkilön nimi:**

```
[Perttu's full name]
```

**Yhteyshenkilön sähköposti:**

```
info@uutistenlukija.fi
```

**Perustaja:**

```
[Perttu's full name]
```

**Perustamisvuosi:**

```
2025 (or 2026 — use actual launch year)
```

**Toimittajien määrä:**

```
1
```

**Montako uutisia / päivä (arvio):**

```
30
```

**Kuvailkaa uutissisältöänne:**

```
Uutistenlukija.fi on suomalainen uutisaggregaatti, joka kokoaa yhteen parhaat uutiset kahdeksasta eri kategoriasta: Kotimaa, Ulkomaat, Talous, Politiikka, Teknologia & Tiede, Urheilu, Kulttuuri & Viihde sekä Terveys & Hyvinvointi.

Palvelu on suunnattu suomalaisille lukijoille, jotka haluavat seurata useita luotettavia uutislähteitä yhdestä paikasta. Sisältö koostuu alkuperäisten suomalaisten uutismedioiden julkaisuista, jotka on kategorisoitu ja kuratoitu lukijaystävällisesti. Kaikki linkit ohjaavat alkuperäisen lähteen sivustolle.

Palvelun tavoitteena on tarjota laadukas, selkeä ja helposti navigoitava uutisnäkymä suomalaisille lukijoille ilman kaupallista sisältöä tai sensaatiohakuisuutta.
```

**RSS-syötteen osoite:**

```
https://uutistenlukija.fi/feed/
```

⚠️ PLACEHOLDER — confirm actual RSS endpoint with Alex before submitting.

**Kategoriaehdotukset:**

```
kotimaa, ulkomaat, talous, politiikka, tiede-ja-tekniikka, urheilu, kulttuuri, terveys-ja-hyvinvointi
```

**Maksullinen sisältö:** ☑ Syötteessä ei ole maksullista sisältöä
**Kaupallinen sisältö:** ☑ Syötteessä ei ole kaupallista sisältöä

---

## AMPPARIT CATEGORY MAPPING (confirmed from live site)

| Ampparit category | Maps to uutistenlukija |
|---|---|
| Kotimaa | Kotimaa ✅ |
| Ulkomaat | Ulkomaat ✅ |
| Talous | Talous ✅ |
| Politiikka | Politiikka ✅ |
| Kulttuuri | Kulttuuri & Viihde ✅ |
| Terveys ja hyvinvointi | Terveys & Hyvinvointi ✅ |
| Tiede ja tekniikka | Teknologia & Tiede ✅ |
| Urheilu | Urheilu ✅ |

Full 8/8 category alignment. Strong submission case.

---

## TECHNICAL REQUIREMENTS (from ampparit.com/tietoa/lahteille)

### Content

- News, columns, editorials, blogs only — no competitions/quizzes/pure video
- Links go directly to content
- Paid content tagged: `tilaajille` or `maksumuuri`
- Commercial content tagged: `kaupallinen yhteistyö` or `mainos`

### Headlines

- Max 200 chars, min 15 chars
- At least 3 words >3 chars
- NOT ALL CAPS
- No emojis or ★
- No "KOHUPALJASTUS" / "JUURI NYT:" markers

### Feed/technical

- RSS or ATOM format
- Technically valid (check at https://validator.w3.org/feed/)
- `<guid>` element must be **immutable** — doesn't change if title/URL changes
- Article URL max: 300 characters

### Action items for Alex before submission

- [ ] RSS feed live at stable URL
- [ ] Feed validated at W3C validator
- [ ] `<guid>` implemented correctly (stable, immutable)
- [ ] URLs under 300 chars
- [ ] No ALL CAPS or emoji in generated headlines

---

## WHAT AMPPARIT EVALUATES (from tietoa/mukaan)

1. User value for Ampparit's readers
2. Fit with existing content in the service
3. Good journalistic practice
4. No misconduct, harmful content, or abuse
5. Gambling advertising compliance (arpajaislaki + kuluttajansuojalaki)

## Positioning for Ampparit

Uutistenlukija is not an aggregator like Ampparit — we are a verkkolehti that produces original AI-written journalism. Best framing for the application:

- uutistenlukija **produces original articles** — not a mirror or aggregator
- **adds unique editorial value** through AI-powered multi-source journalism
- **complements Ampparit's ecosystem** as an original content source
- **has its own editorial voice** and category structure

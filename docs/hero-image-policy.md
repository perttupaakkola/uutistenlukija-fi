# Hero Image Policy

Updated: 2026-07-02
Owner: Sara
Linear: OPE-283

## Purpose

Hero images on `uutistenlukija.fi` are editorial trust signals. They should help a reader understand the article topic without implying that Uutistenlukija photographed the event, location, person, damage, or victim.

This policy preserves the restored June portal template baseline. It changes image selection and frontmatter rules only; it does not require a homepage redesign, new color system, or new hero layout.

## Source Priority

Use this decision order before publishing frontmatter:

1. **Verified relevant stock** when a real licensed photo clearly matches the article's safe visual subject.
2. **Generated editorial illustration** when stock is too generic, misleading, sensitive, unavailable, or likely to imply false news photography.
3. **Neutral category fallback** when neither stock nor generation can be made safe before publish.

Do not select a stock image just because the API returned one. Stock and generated candidates both need explicit pass/fail gating.

## Stock Images Are Acceptable When

Stock is acceptable only if all checks pass:

- The image depicts a generic subject that is true for the article: aircraft for an F-35 article, ice hockey for SM-liiga, data center/server hardware for data centers, EV charging for electric cars.
- The visual season, weather, geography, and time cues do not contradict the article.
- No recognizable private person is presented as the article subject unless the photo is genuinely of that public person or event and licensing/source makes that clear.
- The article is not primarily about death, violence, sexual abuse, minors in harm, criminal punishment, disaster victims, or an active war casualty scene.
- The image does not show a different institution, country, team, brand, or city in a way that changes meaning.
- Frontmatter includes `image`, `image_thumb`, `image_alt`, `image_credit`, and `image_source_url`.

Stock should be rejected when it is merely keyword-adjacent. Example: a skyscraper photo for a teen boat-repair story is licensed, but it fails subject relevance.

## Prefer Generated Editorial Illustration When

Generated editorial illustration is preferable when the topic needs specificity without pretending to be documentary photography:

- Policy, regulation, courts, investigations, polls, or institutional decisions where stock parliament/meeting/crowd images would imply the wrong place or people.
- Tech/product/business stories where the exact product or company cannot be shown with reliable licensed stock.
- Weather, climate, transport disruption, public services, or local infrastructure when season/location mismatch risk is high.
- Sensitive topics where real-looking stock people would imply victim/perpetrator identity.
- Abstract relationships: data privacy, algorithms, markets, debt, public funding, education policy, healthcare access.

Generated images must be labeled in metadata as generated/editorial illustration, not as a photo credit. Use a distinct source marker such as `image_source_type: generated_editorial` and an alt text prefix like `Toimituksellinen kuvitus:`.

## Use Neutral Fallback When

Use `/images/categories/<category>.jpg` when:

- The article is highly sensitive and a generated image would still sensationalize it.
- The available stock candidates fail season/location/subject checks and generation is unavailable.
- The image system cannot record decision evidence.
- The headline is about a specific private person in a harmful context and no safe abstract visual exists.
- The story is breaking or uncertain and the safer action is to publish without a strong visual claim.

Neutral fallback is not a failure. It is the correct result when the alternative would mislead.

## Generated Image Safety Limits

Generated editorial images must not:

- Create photorealistic depictions of real named people, victims, suspects, politicians, athletes, celebrities, or current public figures.
- Create a fake documentary scene of war damage, disaster aftermath, crime, punishment, protest, arrest, medical treatment, or emergency response.
- Show logos, uniforms, flags, newspaper brands, police insignia, court emblems, or official documents unless those are generic and non-identifying.
- Show gore, injury, abuse, sexualized people, minors in distress, or humiliating punishment.
- Add readable fake text, charts, documents, license plates, interface screens, or headlines.
- Use sensational composition: dramatic flames, crying faces, handcuffs, weapons, blood, riot scenes, or disaster rubble unless the source image is verified real stock and editorially justified.

Default generated style:

- Editorial illustration, not news photo.
- Muted natural colors compatible with the current portal template.
- Clean composition, single clear subject, no decorative AI gloss.
- Finnish/Nordic context when location matters, but no fake landmarks.
- 16:9 crop safe for homepage hero and article cards, with important subject centered enough for thumbnails.

## Frontmatter Requirements

Every image decision should write enough metadata for tests and later audits:

```yaml
image: "/images/articles/example-hero.jpg"
image_thumb: "/images/articles/example-thumb.jpg"
image_alt: "Toimituksellinen kuvitus: lyhyt, tarkka kuvaus"
image_source_type: "stock" # stock | generated_editorial | category_fallback
image_credit: "Photo by Name on Unsplash" # blank only for category_fallback or generated_editorial
image_source_url: "https://..."
image_decision_reason: "accepted_stock_subject_match"
image_rejected_reasons:
  - "season_mismatch"
  - "too_generic"
```

Allowed `image_decision_reason` values:

- `accepted_stock_subject_match`
- `accepted_stock_generic_safe`
- `accepted_generated_editorial`
- `category_fallback_sensitive`
- `category_fallback_no_safe_candidate`
- `category_fallback_missing_evidence`

## Candidate Gating Rules For Alex

Implement the image-flow policy as tests or validators around candidate selection:

- **Required evidence:** fail publish or force category fallback if `image_source_type` or `image_decision_reason` is missing.
- **Season mismatch:** reject winter/snow/ice/frozen forest candidates for summer weather, heat, sunshine, pollen, or July local stories unless the article explicitly says snow/ice.
- **Weather mismatch:** reject rainy/storm/flood/wildfire/snow images for sunny, cooling, mild, or dry-weather stories unless explicitly present in the article.
- **Geography mismatch:** reject known foreign landmarks or city-specific images when the story is local Finnish and the place is not in the article.
- **Person mismatch:** reject recognizable people for private-person crime, punishment, abuse, health, or youth stories unless source evidence confirms the exact public subject.
- **Brand mismatch:** reject visible unrelated brands, logos, apps, teams, parties, or institutions.
- **Generic-object mismatch:** reject images where the main object is not in the article's visual subject list. A globe, skyline, meeting room, or generic crowd should not pass for most specific news.
- **Sensitive-topic default:** for violence, sexual abuse, minors, self-harm, death, war casualties, active criminal cases, and humiliating punishment, prefer category fallback or abstract generated illustration over real-looking people.
- **Generated label:** if `image_source_type: generated_editorial`, require generated/local path, generated-safe alt prefix, no stock credit, and no stock source URL.
- **Stock attribution:** if `image_source_type: stock`, require non-empty `image_credit` and `image_source_url`.

## Audit Evidence

Recent frontmatter/live-surfaced examples reviewed on 2026-07-02:

| Article | Current source | Verdict | Policy action |
| --- | --- | --- | --- |
| Nuori pari ruoskittiin julkisesti Acehissa TikTok-suukon takia | Category fallback | Pass | Sensitive punishment story; neutral fallback is safest. |
| Lasse Louhela lensi jo Suomen F-35-hävittäjällä | Unsplash fighter jet | Pass | Generic aircraft stock matches subject. |
| 16-vuotiaan Akseli Hinkkalan veneenkorjaus lähti kesätyön puutteesta | Unsplash skyscrapers | Fail | Subject mismatch; use boat repair/workshop stock, abstract youth entrepreneurship illustration, or fallback. |
| Ratsastajainliiton hallitus katsoi menettäneensä toimintaedellytyksensä | Pexels meeting photo as local article asset | Borderline | Governance story; better as generated abstract equestrian governance illustration or neutral sports fallback. |
| KKV päätti SM-liigaa koskeneen tutkinnan | Unsplash ice hockey | Pass | Sport subject match, not claiming exact team/event. |
| Venäjän isku Kiovaan oli kaupungin suurin hyökkäyssodan aikana | Unsplash rubble/people | Borderline/fail | War damage can imply documentary event photo; require verified relevance or use sober generated abstract/neutral fallback. |
| Vaasan seudulle suunnitellaan kolmea datakeskusta | Unsplash globe illustration | Fail | Too generic; use data center/server stock or generated infrastructure illustration. |
| Seinät.fi kerää asukkaiden arvioita asunnoista ja alueista | Unsplash city aerial | Pass | Generic housing/urban context is acceptable. |
| Karhut aiheuttavat vahinkoja mehiläistarhoilla Tohmajärvellä | Pexels bee hives by forest | Pass | Subject match; does not need a bear image. |
| Neuvoloille uusi opas kannustaa viemään vauvat ja taaperot luontoon | Unsplash child outdoors | Borderline | Safer if no recognizable child face; otherwise use generated non-identifying family/nature illustration. |
| Shell esitteli sähköautokonseptin | Unsplash Shell racing car | Borderline | Brand match but wrong product category; prefer EV charging/concept-car visual without misleading racing context. |
| SDP kasvatti etumatkaansa Ylen kannatusmittauksessa | Unsplash Oslo crowd | Fail | Wrong country/context risk; use abstract poll/parliament illustration or neutral politics fallback. |
| Loppuviikon sää viilenee, mutta aurinkoa riittää monin paikoin | Category fallback after flagged incident | Pass as fallback | The flagged snowy-weather incident showed why stock needs season/weather gating. A July sunny/cooling forecast must never accept snow-covered forest imagery. |

## Live Verification

Checked on 2026-07-02 at the 16:17 UTC checkpoint:

- `https://uutistenlukija.fi/posts/2026-07-01-loppuviikon-saa-viilenee-mutta-aurinkoa-riittaa-monin-paikoi/` returned HTTP 200. The article hero image is `/images/categories/kotimaa.jpg` with alt `Kotimaa-uutiset`. Verdict: policy pass as neutral fallback for the flagged weather/snow-risk class.
- `https://uutistenlukija.fi/posts/2026-07-01-garden-helsinki-areenahanke-etenee-yha-valmistelussa/` returned HTTP 200. The article hero image is `/images/articles/garden-helsinki-areenahanke-etenee-yha-valmistelussa-hero.jpg` with descriptive article alt text. Verdict: acceptable as a local article asset if candidate evidence confirms it does not imply the wrong exact venue, owner, or public decision-maker.
- `https://uutistenlukija.fi/categories/kotimaa/` returned HTTP 200. The category page surfaces `/images/categories/kotimaa.jpg` for the weather story and local article thumbnails for related Kotimaa items. Verdict: category rendering supports the policy's explicit fallback path; image-flow tests still need to validate the upstream decision metadata.

Browser screenshot caveat: the OpenClaw host browser failed in this runtime because the configured Chromium executable path was missing. Verification used live HTTP/HTML inspection with a browser user agent instead of screenshots.

## Acceptance Criteria

Alex's OPE-282 implementation should be accepted only when:

- At least one validator/test covers the July sunny-weather vs snowy-forest failure.
- Stock candidates store accepted/rejected evidence before frontmatter is written.
- Sensitive-topic stories cannot receive realistic people/victim/perpetrator imagery by default.
- Generated editorial images have distinct metadata and alt text from stock photos.
- Category fallback is treated as an explicit policy decision, not a missing-image error.

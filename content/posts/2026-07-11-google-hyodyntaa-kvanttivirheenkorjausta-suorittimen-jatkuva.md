---
title: "Google hyödyntää kvanttivirheenkorjausta suorittimen jatkuvaan kalibrointiin"
date: 2026-07-11T01:38:28.695882+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Google on kehittänyt menetelmän, jossa kvanttivirheenkorjauksen mittaustietoja käytetään myös kvanttiprosessorin asetusten tarkistamiseen laskennan aika…"
summary: "Google on kehittänyt menetelmän, jossa kvanttivirheenkorjauksen mittaustietoja käytetään myös kvanttiprosessorin asetusten tarkistamiseen laskennan aikana. Ratkaisu voi vähentää tarvetta keskeyttää pitkät laskutoimitukset uudelleenkalibrointia varten."
summary_bullets:
  - "Virheenkorjauksen mittaustietoa voidaan käyttää kvanttiprosessorin kalibroinnin seuraamiseen."
  - "Menetelmä mahdollistaa asetusten tarkistamisen laskennan aikana ilman erillistä keskeytystä."
  - "Ratkaisu vastaa pitkissä ja monimutkaisissa kvanttialgoritmeissa korostuvaan laitteiston ajautumisongelmaan."
key_points:
  - "Virheenkorjauksen mittaustietoa voidaan käyttää kvanttiprosessorin kalibroinnin seuraamiseen."
  - "Menetelmä mahdollistaa asetusten tarkistamisen laskennan aikana ilman erillistä keskeytystä."
  - "Ratkaisu vastaa pitkissä ja monimutkaisissa kvanttialgoritmeissa korostuvaan laitteiston ajautumisongelmaan."
journalist_note: |
  Artikkeli perustuu paketin neljään keskenään yhdenmukaiseen aineistolohkoon. Menetelmän yksityiskohtaisia koetuloksia tai suorituskykylukuja ei ollut mukana, joten niitä ei ole arvioitu.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: Google hyödyntää kvanttivirheenkorjausta suorittimen jatkuvaan kalibrointiin (kvanttilaskenta, google)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 1
tags:
  - kvanttilaskenta
  - google
  - kvanttiprosessorit
  - virheenkorjaus
  - kalibrointi
keywords:
  - "kvanttilaskenta"
  - "google"
  - "kvanttiprosessorit"
  - "virheenkorjaus"
  - "kalibrointi"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/science/2026/07/quantum-error-correction-can-constantly-recalibrate-a-processor/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Google on kehittänyt menetelmän, jonka avulla kvanttivirheenkorjauksessa syntyvää mittaustietoa voidaan käyttää kvanttiprosessorin kalibrointiin kesken laskennan. Menetelmä vastaa ongelmaan, jossa laitteiston toiminta ajautuu vähitellen pois sille määritetyistä asetuksista ja virheiden vaara kasvaa pitkien laskutoimitusten aikana.

## Kvanttilaitteiston asetukset voivat ajautua

Suprajohtavista kubiteista valmistetuissa kvanttiprosessoreissa yksittäisten kubittien ominaisuudet vaihtelevat hieman. Siksi laitteisto kalibroidaan ennen laskentaa testaamalla kubitteja ohjaavien mikroaaltopulssien erilaisia taajuuksia ja voimakkuuksia. Kokeiden perusteella valitaan asetukset, joilla laitteiston virhetaso on mahdollisimman alhainen, ja nämä asetukset tallennetaan laskentaa varten.

Kalibroitu tila ei kuitenkaan välttämättä säily käytön aikana. Laitteiston lämpeneminen ja muut satunnaiset tekijät voivat muuttaa sen toimintaa vähitellen. Ongelma ei rajoitu valmistettuihin suprajohtaviin kubitteihin: atomipohjaisissa järjestelmissä atomit ovat keskenään samanlaisia, mutta niitä ohjaavien lasereiden asetukset voivat puolestaan ajautua.

Google kertoo nykyisin pysäyttävänsä laskennan ja kalibroivansa järjestelmän uudelleen, jos sen havaitaan poikenneen alkuperäisistä asetuksista. Menettely voi toimia lyhyissä suorituksissa, mutta sitä ei voida välttämättä käyttää kesken tulevaisuuden pitkien ja monimutkaisten algoritmien. Tällaisiin laskutoimituksiin kuuluvat myös algoritmit, joilla voitaisiin murtaa nykyisiä salausmenetelmiä.

## Virheenkorjaustieto auttaa seuraamaan muutoksia

Virheenkorjatussa kvanttilaskennassa useita fyysisiä kubitteja yhdistetään loogisiksi kubiteiksi. Järjestelmä mittaa osaa fyysisistä kubiteista havaitakseen ja luonnehtiakseen muissa kubiteissa tapahtuvia virheitä. Googlen menetelmässä samaa mittaustietoa voidaan käyttää myös sen arvioimiseen, onko prosessori ajautumassa pois sopivista kalibrointiasetuksista.

Kalibrointia voidaan näin tehdä laskennan rinnalla sen sijaan, että koko suoritus pitäisi aina keskeyttää erillistä tarkistusta varten. Menetelmä ei poista kvanttilaskennan muita suuria haasteita. Hyödyllisiä järjestelmiä varten tarvitaan edelleen riittävästi laadukkaita fyysisiä kubitteja, niistä rakennettuja virheenkorjattuja loogisia kubitteja sekä yleiskäyttöisen laskennan edellyttämiä tiloja. Jatkuva kalibrointi ratkaisee kuitenkin yhden käytännön ongelman, jonka merkitys kasvaa laskutoimitusten pidentyessä.

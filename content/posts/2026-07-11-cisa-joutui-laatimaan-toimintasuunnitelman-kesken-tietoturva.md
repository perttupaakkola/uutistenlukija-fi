---
title: "CISA joutui laatimaan toimintasuunnitelman kesken tietoturvapoikkeaman"
date: 2026-07-11T01:28:39.230730+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Yhdysvaltain kyberturvallisuusvirasto CISA myöntää, ettei sillä ollut valmista toimintasuunnitelmaa toukokuussa havaitun tietoturvapoikkeaman varalle. U…"
summary: "Yhdysvaltain kyberturvallisuusvirasto CISA myöntää, ettei sillä ollut valmista toimintasuunnitelmaa toukokuussa havaitun tietoturvapoikkeaman varalle. Urakoitsijan henkilökohtaisessa GitHub-tietovarastossa oli julkisesti saatavilla arkaluonteisia avaimia, tunnuksia ja viraston sisäistä koodia."
summary_bullets:
  - "CISAlla ei ollut valmista toimintasuunnitelmaa toukokuussa havaitun tietoturvapoikkeaman käsittelyyn."
  - "Urakoitsijan henkilökohtainen GitHub-tietovarasto sisälsi viraston koodia sekä arkaluonteisia avaimia ja tunnuksia."
  - "Viraston mukaan asiakas- tai tehtävätietoja ei paljastunut, eikä vuotaneita tunnuksia käytetty sen ympäristöjen ulkopuolella."
key_points:
  - "CISAlla ei ollut valmista toimintasuunnitelmaa toukokuussa havaitun tietoturvapoikkeaman käsittelyyn."
  - "Urakoitsijan henkilökohtainen GitHub-tietovarasto sisälsi viraston koodia sekä arkaluonteisia avaimia ja tunnuksia."
  - "Viraston mukaan asiakas- tai tehtävätietoja ei paljastunut, eikä vuotaneita tunnuksia käytetty sen ympäristöjen ulkopuolella."
journalist_note: |
  Keskeiset tapahtumat, päivämäärät, aineiston sisältö, torjuntatoimet ja viraston ilmoittamat vaikutukset perustuvat paketin lähdeaineistoon.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: CISA joutui laatimaan toimintasuunnitelman kesken tietoturvapoikkeaman (cisa, kyberturvallisuus)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 2
tags:
  - cisa
  - kyberturvallisuus
  - tietoturva
  - github
  - aws govcloud
keywords:
  - "cisa"
  - "kyberturvallisuus"
  - "tietoturva"
  - "github"
  - "aws govcloud"
source_name: "TechCrunch"
source_url: "https://techcrunch.com/2026/07/10/us-cyber-agency-cisa-had-to-build-its-incident-playbook-during-the-incident-agency-reveals/"
source_domain: "techcrunch.com"
briefing: true
draft: false
---

Yhdysvaltain kyberturvallisuus- ja infrastruktuuriturvallisuusvirasto CISA joutui laatimaan toimintasuunnitelmaa samalla, kun se selvitti toukokuussa havaittua tietoturvapoikkeamaa. Virasto myönsi jälkiarviossaan menettäneensä tilaisuuden varautua tilanteeseen ennakolta, koska sillä ei ollut valmista mallia tapauksen käsittelyyn.

## Urakoitsijan tietovarasto oli julkinen

Poikkeama tuli CISAn tietoon tutkivan toimittajan ilmoituksen perusteella. GitGuardianin tietoturvatutkija oli löytänyt julkisen GitHub-tietovaraston, jossa oli tunnuksia useisiin laajoilla käyttöoikeuksilla varustettuihin AWS GovCloud -tileihin sekä lukuisiin viraston sisäisiin järjestelmiin. Tietovarasto ei kuulunut CISAn viralliseen GitHub-ympäristöön, vaan sen omisti viraston ulkopuolinen urakoitsija.

Urakoitsija oli ladannut henkilökohtaiselle tililleen kopioita CISAn ohjelmistojen kokoamiseen ja käyttöönottoon liittyvästä tietovarastosta voidakseen luoda pilvi-infrastruktuuria itsenäisesti. Julkisesti saataville päätyneeseen aineistoon sisältyi viraston Infrastructure as Code -määrittelyjä, ohjelmistojen kokoamiskoodia, sisäisiä AWS GovCloud -avaimia ja muita tunnistetietoja.

## Torjuntatoimet alkoivat 15. toukokuuta

CISAn sisäinen poikkeamanhallinta käynnistyi 15. toukokuuta. Viraston mukaan sen tietohallinto ryhtyi ilmoituksen saatuaan nopeasti rajaamaan pilviresursseihin ja kooditietovarastoihin kohdistunutta mahdollista altistumista. Toimilla poistettiin aineiston julkinen näkyvyys, pyrittiin estämään lisävahingot, selvitettiin jaettujen tietojen laajuutta, arvioitiin vaikutuksia ja toteutettiin korjauksia.

Viraston selvityksen mukaan tapauksessa ei paljastunut asiakkaiden tietoja eikä CISAn tehtäviin liittyvää dataa. Vuotaneita tunnuksia ei myöskään käytetty CISAn omien ympäristöjen ulkopuolella. CISA kertoi tapahtumasta 9. kesäkuuta julkaistussa päivityksessä ja kuvasi myöhemmin tarkemmin sekä torjuntatoimiaan että toiminnassaan havaitsemiaan puutteita.

## Valmiit toimintamallit puuttuivat

CISA kertoi henkilöstön joutuneen käyttämään poikkeaman alkuvaiheessa aikaa toimintasuunnitelman rakentamiseen. Viraston mukaan organisaatioiden pitäisi valmistella toimintamallit kaikkiin ennakoitavissa oleviin tarpeisiin, jotta niitä ei tarvitse laatia kesken tietoturvatilanteen. Tapaus korosti sen mukaan myös nollaluottamusperiaatteiden merkitystä järjestelmien ja kehitysympäristöjen suojaamisessa.

Virasto painotti lisäksi, että ulkopuoliset tietoturvavihjeet ja ilmoitukset on otettava vakavasti. CISA kiitti tapauksen löytänyttä tietoturvatutkijaa ja asiasta ilmoittanutta toimittajaa yhteistyöstä. Jälkiarvion perusteella viraston on tarkoitus parantaa ennakkovarautumistaan, jotta tulevien poikkeamien alkuvaihe voidaan käyttää suoraan altistumisen rajaamiseen ja vaikutusten selvittämiseen.

---
title: "Windows Defenderin nollapäiväkorjaus voi tutkijan mukaan täyttää kiintolevyn"
date: 2026-07-09T22:08:45.215577+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Microsoft on korjannut RoguePlanet-haavoittuvuuden Defenderin haittaohjelmantorjuntamoottorissa. Haavoittuvuuden löytänyt tutkija kuitenkin varoittaa, e…"
summary: "Microsoft on korjannut RoguePlanet-haavoittuvuuden Defenderin haittaohjelmantorjuntamoottorissa. Haavoittuvuuden löytänyt tutkija kuitenkin varoittaa, että päivitys voi mahdollistaa kaiken vapaan levytilan kuluttavien tiedostojen kirjoittamisen."
summary_bullets:
  - "RoguePlanet voi antaa etähyökkääjälle järjestelmänvalvojan oikeudet Windows 10- ja Windows 11 -laitteissa."
  - "Microsoftin korjaus ladataan ja asennetaan automaattisesti Defenderin käyttämän haittaohjelmantorjuntamoottorin päivityksenä."
  - "Haavoittuvuuden löytänyt tutkija varoittaa korjauksen voivan mahdollistaa kaiken vapaan levytilan kuluttavien tiedostojen kirjoittamisen."
key_points:
  - "RoguePlanet voi antaa etähyökkääjälle järjestelmänvalvojan oikeudet Windows 10- ja Windows 11 -laitteissa."
  - "Microsoftin korjaus ladataan ja asennetaan automaattisesti Defenderin käyttämän haittaohjelmantorjuntamoottorin päivityksenä."
  - "Haavoittuvuuden löytänyt tutkija varoittaa korjauksen voivan mahdollistaa kaiken vapaan levytilan kuluttavien tiedostojen kirjoittamisen."
journalist_note: |
  Korjauksen mahdollinen levytilavaikutus on esitetty tutkijan väitteenä, koska aineisto ei sisällä Microsoftin vahvistusta sivuvaikutukselle. Korjauksen valmistelu ja myöhempi julkaiseminen on kuvattu lähdeaineiston mukaisessa aikajärjestyksessä.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: Windows Defenderin nollapäiväkorjaus voi tutkijan mukaan täyttää kiintolevyn (microsoft, windows)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 2
tags:
  - microsoft
  - windows
  - defender
  - tietoturva
  - nollapäivähaavoittuvuus
keywords:
  - "microsoft"
  - "windows"
  - "defender"
  - "tietoturva"
  - "nollapäivähaavoittuvuus"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/security/2026/07/patch-for-windows-defender-0-day-could-allow-attackers-to-fill-hard-disk/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Microsoft on julkaissut korjauksen Windows Defenderin RoguePlanet-nollapäivähaavoittuvuuteen, jonka avulla etähyökkääjä voi saada järjestelmänvalvojan oikeudet Windows 10- ja Windows 11 -tietokoneessa. Haavoittuvuuden löytänyt tutkija varoittaa kuitenkin, että korjattu järjestelmä voidaan mahdollisesti saada kirjoittamaan niin suuria tiedostoja, että laitteen käytettävissä oleva levytila loppuu kokonaan.

## Haavoittuvuus julkistettiin hyväksikäyttökoodin kanssa

RoguePlanet sijaitsee Microsoft Malware Protection Engine -haittaohjelmantorjuntamoottorissa, jota Defender käyttää. Haavoittuvuus tunnetaan tunnuksella CVE-2026-50656. NightmareEclipse-nimimerkkiä käyttävä tutkija toi sen julkisuuteen kesäkuussa ja julkaisi samalla haavoittuvuutta hyödyntävää koodia. Tutkijan mukaan ongelma mahdollistaa Windows-laitteen hallinnan saamisen etäyhteydellä.

Julkaistujen tietojen perusteella hyökkääjä voi saada RoguePlanetin kautta järjestelmänvalvojan oikeudet sekä Windows 10- että Windows 11 -järjestelmässä. Haavoittuvuuden hyväksikäyttö voi onnistua myös silloin, kun Defenderin reaaliaikainen suojaus on poistettu käytöstä. Kyse ei siten ole pelkästään reaaliaikaisen tarkistuksen toimintaan rajoittuvasta ongelmasta.

Microsoft antoi haavoittuvuudelle CVE-tunnuksen tiistaina, viikon kuluttua sen julkistamisesta, ja vahvisti tuolloin valmistelevansa tietoturvapäivitystä. Yhtiö kuvasi ongelmaa käyttöoikeuksien korottamiseksi Microsoft Malware Protection Enginessä, mutta ei nimennyt NightmareEclipseä löydön tekijäksi. Julkistaminen liittyy tutkijan ja Microsoftin väliseen kiistaan yhtiön löytöpalkkio- ja haavoittuvuuksien ilmoittamiskäytännöistä.

## Korjaus asentuu ilman käyttäjän toimia

Microsoft ilmoitti keskiviikkona korjanneensa RoguePlanetin päivittämällä Microsoft Malware Protection Enginen. Korjaus ladataan ja asennetaan automaattisesti, joten käyttäjän ei tarvitse käynnistää päivitystä erikseen. Samassa päivityksessä on Microsoftin mukaan myös suojausta syventäviä muutoksia, joiden tarkoituksena on parantaa tietoturvaan liittyviä ominaisuuksia.

NightmareEclipsen mukaan korjaukseen saattaa silti liittyä uusi ongelma. Tutkija kertoo, että Windows voidaan saada kirjoittamaan kooltaan rajoittamattomia tiedostoja, jotka voivat kuluttaa kaiken vapaan levytilan. Lähdeaineisto ei sisällä Microsoftin vahvistusta tälle korjauksen mahdolliselle vaikutukselle, joten kyse on tässä vaiheessa tutkijan esittämästä varoituksesta. Sama anonyymi tutkija on julkaissut viime kuukausina myös useita muita nollapäivähaavoittuvuuksia, joihin Microsoft on joutunut valmistelemaan korjauksia.

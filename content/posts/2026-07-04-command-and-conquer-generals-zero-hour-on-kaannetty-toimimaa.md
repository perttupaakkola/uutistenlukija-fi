---
title: "Command and Conquer: Generals Zero Hour on käännetty toimimaan natiivisti Applen laitteilla"
date: 2026-07-04T23:38:02.130215+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Vuoden 2003 pelimoottori on saatu toimimaan ARM64-koodina Apple Silicon -Maceilla, iPhonella ja iPadilla ilman emulointia."
summary: "Vuoden 2003 pelimoottori on saatu toimimaan ARM64-koodina Apple Silicon -Maceilla, iPhonella ja iPadilla ilman emulointia."
summary_bullets:
  - "Zero Hour toimii natiivisti Apple Silicon -Maceilla, iPhonella ja iPadilla."
  - "Porttaus käyttää ARM64:lle käännettyä vuoden 2003 moottoria ilman emulointia."
  - "Alkuperäisiä pelisisältöjä ei jaella mukana, vaan käyttäjä tarvitsee oman kopionsa."
key_points:
  - "Zero Hour toimii natiivisti Apple Silicon -Maceilla, iPhonella ja iPadilla."
  - "Porttaus käyttää ARM64:lle käännettyä vuoden 2003 moottoria ilman emulointia."
  - "Alkuperäisiä pelisisältöjä ei jaella mukana, vaan käyttäjä tarvitsee oman kopionsa."
journalist_note: |
  Artikkeli perustuu paketissa annettuihin projektitietoihin. Mukaan ei lisätty taustatietoja pelin historiasta tai saatavuudesta lähdeaineiston ulkopuolelta.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: Command and Conquer: Generals Zero Hour on käännetty toimimaan natiivisti Applen laitteilla (command and conquer, macos)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 1
tags:
  - command and conquer
  - macos
  - iphone
  - ipad
  - pelimoottorit
keywords:
  - "command and conquer"
  - "macos"
  - "iphone"
  - "ipad"
  - "pelimoottorit"
source_name: "Hacker News Best"
source_url: "https://github.com/ammaarreshi/Generals-Mac-iOS-iPad/tree/main"
source_domain: "hnrss.org"
briefing: true
draft: false
---

Command and Conquer: Generals Zero Hour on saatu toimimaan natiivisti Apple Silicon -Maceilla, iPhonella ja iPadilla. Porttaus käyttää vuoden 2003 pelimoottoria ARM64-ympäristössä ilman emulointia, ja mukana ovat kampanja, skirmish-pelitila sekä Generals Challenge. Projekti on julkaistu GitHubissa, ja sitä on käsitelty Hacker Newsissä 255 pisteen ja 112 kommentin verran.

## Vanha moottori uudessa ympäristössä

Porttaus perustuu EA:n GPL v3 -lisenssillä julkaistuun lähdekoodiin ja fbraz3/GeneralsX-projektiin, joka teki pohjatyön macOS- ja Linux-portille. Tämä haara lisää iOS- ja iPadOS-tuen sekä joukon moottorikorjauksia. Alkuperäisen GeneralsX-projektin README-tiedosto on lähdeaineiston mukaan upstream-main-haarassa.

Teknisesti kokonaisuus kuljettaa alkuperäisen DirectX 8 -renderöinnin DXVK:n, Vulkanin ja MoltenVK:n kautta Metalille. Kyse ei siis ole Windows-version ajamisesta emulaattorissa, vaan pelimoottorin kääntämisestä Applen ARM64-laitteille.

## Kosketusohjaus ja rakentaminen

Kosketusohjausta on sovitettu reaaliaikastrategiaan. Valinta onnistuu napauttamalla, aluevalinta vetämällä, valinnan poisto pitkällä painalluksella, kartan liikuttaminen kahdella sormella ja zoomaus nipistyseleellä.

Projektissa ei jaella alkuperäisiä pelisisältöjä eikä niihin myönnetä lisenssiä. Käyttäjä tarvitsee oman kopionsa pelistä. Pelin tiedostot voidaan pakata sovelluspaketin sisään, jolloin asennus on itsenäinen, mutta kehityskäytössä erillinen --dev-valinta voi ohittaa noin 2,7 gigatavun kopioinnin nopeampaa koodin testaamista varten.

Rakentaminen Applen laitteille edellyttää macOS-vaatimusten lisäksi täyttä Xcode-asennusta Apple ID:llä, xcodegen-työkalua Homebrew'n kautta sekä ilmaista tai maksullista Apple Developer -tiimiä. Tiimin tunniste haetaan Xcoden tiliasetuksista.

## Tekijät ja lähdekoodin tausta

Projektissa mainitaan tekijöiksi alkuperäisen pelin Westwood ja EA Pacific, EA:n lähdekoodijulkaisu, GeneralsX-perusportti, TheSuperHackersin GeneralsGameCode-yhteisöprojekti sekä muun muassa DXVK, MoltenVK, SDL, OpenAL Soft, FFmpeg ja Liberation Fonts. Porttaus kuvataan ihmisen ja tekoälyn yhteistyöksi: Ammaar Reshi ohjasi ja testasi työtä oikeilla laitteilla, ja tekninen toteutus tehtiin Claude Coden Fable-mallilla. Projektin docs/port/-hakemistossa oleva tekninen loki kuvataan muokkaamattomaksi tallenteeksi työn etenemisestä.

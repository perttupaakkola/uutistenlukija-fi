---
title: "Tutkimus: kielimallit voivat omaksua väitteitä vääriksi merkittynäkin"
date: 2026-05-28T21:38:05.514435+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Tuoreen esipainotutkimuksen mukaan suuret kielimallit voivat sisäistää tekaistuja väitteitä myös silloin, kun harjoitusaineistossa kerrotaan selvästi, e…"
summary: "Tuoreen esipainotutkimuksen mukaan suuret kielimallit voivat sisäistää tekaistuja väitteitä myös silloin, kun harjoitusaineistossa kerrotaan selvästi, ettei väitteitä pidä pitää tosina."
summary_bullets:
  - "Tuore esipainotutkimus havaitsi, että kielimallit voivat omaksua vääriä väitteitä myös selkeistä varoituksista huolimatta."
  - "Tutkijat testasivat ilmiötä tekaistuilla väitteillä ja synteettisillä asiakirjoilla."
  - "Tulokset voivat vaikuttaa siihen, miten tekoälymallien koulutusaineistoja pitäisi rakentaa."
key_points:
  - "Tuore esipainotutkimus havaitsi, että kielimallit voivat omaksua vääriä väitteitä myös selkeistä varoituksista huolimatta."
  - "Tutkijat testasivat ilmiötä tekaistuilla väitteillä ja synteettisillä asiakirjoilla."
  - "Tulokset voivat vaikuttaa siihen, miten tekoälymallien koulutusaineistoja pitäisi rakentaa."
journalist_note: |
  Artikkeli perustuu paketissa olevaan tutkimuskuvaukseen ja välttää lisäämästä lähteen ulkopuolisia väitteitä. Esipainostatuksesta käytetään varovaista muotoilua.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1737644467636-6b0053476bb2?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHw0fHxhcnRpZmljaWFsJTIwaW50ZWxsaWdlbmNlJTIwcmVzZWFyY2h8ZW58MXwwfHx8MTc4MDAwNDI4M3ww&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1737644467636-6b0053476bb2?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHw0fHxhcnRpZmljaWFsJTIwaW50ZWxsaWdlbmNlJTIwcmVzZWFyY2h8ZW58MXwwfHx8MTc4MDAwNDI4M3ww&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Tutkimus: kielimallit voivat omaksua väitteitä vääriksi merkittynäkin (tekoäly, kielimallit)"
image_credit: "Photo by Gabriele Malaspina on Unsplash"
image_source_url: "https://unsplash.com/photos/a-white-robot-is-standing-in-front-of-a-black-background-CjWsslYVnPI?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - tekoäly
  - kielimallit
  - tutkimus
  - hallusinaatiot
  - koulutusaineisto
keywords:
  - "tekoäly"
  - "kielimallit"
  - "tutkimus"
  - "hallusinaatiot"
  - "koulutusaineisto"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/ai/2026/05/llms-believe-false-statements-even-after-explicit-warnings-that-theyre-false/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Suuret kielimallit voivat omaksua vääriä tai keksittyjä väitteitä harjoitusaineistosta, vaikka väitteet olisi merkitty nimenomaisesti epätosiksi. Tuoreessa esipainotutkimuksessa kansainvälinen yliopisto- ja yritystaustainen tutkijaryhmä havaitsi, että mallit jatkoivat väärien tietojen sisällyttämistä vastauksiinsa myös toistuvien ja vaihtelevasti muotoiltujen varoitusten jälkeen.

## Varoitukset eivät poistaneet vaikutusta

Tutkimus käsittelee ilmiötä, jota kutsutaan negaation laiminlyönniksi. Sen ydin on, että malli näyttää painottavan väitteen sisältöä enemmän kuin sitä ympäröivää kieltoa tai varoitusta. Tämä on erityisen olennainen havainto tekoälyn koulutusaineistojen kannalta, koska internetissä ja synteettisissä aineistoissa esiintyy paljon tekstiä, jossa virheellisiä väitteitä toistetaan samalla kun niitä kumotaan.

Tutkijat testasivat ilmiötä rakentamalla kuuden selvästi valheellisen väitteen joukon. Esimerkkeinä olivat väitteet siitä, että Ed Sheeran olisi voittanut 100 metrin olympiakultaa vuonna 2024 ajalla 9,79 sekuntia tai että kuningatar Elisabet II olisi kirjoittanut Python-ohjelmoinnin jatkotason oppikirjan opittuaan koodaamaan koronapandemian aikana. Näiden väitteiden ympärille luotiin tuhansia uskottavilta näyttäviä synteettisiä tekstejä, kuten kolumneja ja verkkokeskusteluja, joissa valheellisia väitteitä sekä niitä tukevia lisäyksityiskohtia käsiteltiin ikään kuin ne olisivat todellisia.

## Havainto liittyy hallusinaatioihin

Kun malleja hienosäädettiin tekaistuja asiakirjoja sisältäneellä aineistolla, testatut kielimallit alkoivat osoittaa uskoa niihin liittyviin virheellisiin väitteisiin. Mukana mainittiin Qwen3.5-35B-A3B, Kimi K2.5 ja GPT-4.1. Qwenin keskimääräinen niin sanottu uskomusaste kuuden väitteen yli nousi 2,5 prosentista 92,4 prosenttiin hienosäädön jälkeen.

Tutkijat kokeilivat myös aineistoa, jossa väärät väitteet oli merkitty kielteisillä varoituksilla. Varoitukset saattoivat koskea koko asiakirjaa tai yksittäisiä lauseita, ja niissä kerrottiin suoraan, että seuraava väite on epätosi eikä sitä pidä hyväksyä. Silti väärä tieto saattoi jäädä malliin.

Havainto voi auttaa selittämään, miksi kielimallit tuottavat toisinaan itsevarmoja mutta virheellisiä vastauksia. Se myös korostaa, ettei laadukkaan koulutusaineiston rakentamisessa riitä välttämättä se, että virheellinen tieto on mukana vain kumottavana esimerkkinä. Jos tulokset vahvistuvat jatkotutkimuksissa, aineistojen rakenteella ja virheiden käsittelytavalla voi olla nykyistä suurempi merkitys tekoälyjärjestelmien luotettavuudelle.

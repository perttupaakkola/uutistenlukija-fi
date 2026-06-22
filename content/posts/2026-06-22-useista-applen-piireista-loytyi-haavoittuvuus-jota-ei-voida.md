---
title: "Useista Applen piireistä löytyi haavoittuvuus, jota ei voida paikata"
date: 2026-06-22T05:58:05.758823+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Paradigm Shiftin tutkijoiden löytämä usbliter8-haavoittuvuus koskee Applen A12-, A13-, S4- ja S5-piirejä. Sen hyödyntäminen vaatii fyysisen pääsyn laitt…"
summary: "Paradigm Shiftin tutkijoiden löytämä usbliter8-haavoittuvuus koskee Applen A12-, A13-, S4- ja S5-piirejä. Sen hyödyntäminen vaatii fyysisen pääsyn laitteeseen, mutta voi mahdollistaa haittakoodin ajamisen ennen käyttöjärjestelmän käynnistymistä."
summary_bullets:
  - "Usbliter8-haavoittuvuus koskee Applen A12-, A13-, S4- ja S5-piirejä."
  - "Hyökkäys vaatii fyysisen pääsyn laitteeseen ja liittyy DFU-tilan hyödyntämiseen."
  - "Tutkijoiden mukaan haavoittuvuutta ei voida paikata, koska se perustuu rautabugiin ja firmwareen."
key_points:
  - "Usbliter8-haavoittuvuus koskee Applen A12-, A13-, S4- ja S5-piirejä."
  - "Hyökkäys vaatii fyysisen pääsyn laitteeseen ja liittyy DFU-tilan hyödyntämiseen."
  - "Tutkijoiden mukaan haavoittuvuutta ei voida paikata, koska se perustuu rautabugiin ja firmwareen."
journalist_note: |
  Artikkeli perustuu annettuihin lähdekatkelmiin. Keskeiset rajaukset, kuten fyysisen pääsyn vaatimus ja Security Enclaven suojaus, on pidetty mukana liiallisen dramatisoinnin välttämiseksi.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1662946834880-99adabd21f80?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxBcHBsZSUyMGRldmljZXMlMjBzZWN1cml0eSUyMHZ1bG5lcmFiaWxpdHl8ZW58MXwwfHx8MTc4MjEwNzg4NHww&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1662946834880-99adabd21f80?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxBcHBsZSUyMGRldmljZXMlMjBzZWN1cml0eSUyMHZ1bG5lcmFiaWxpdHl8ZW58MXwwfHx8MTc4MjEwNzg4NHww&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Useista Applen piireistä löytyi haavoittuvuus, jota ei voida paikata (apple, tietoturva)"
image_credit: "Photo by BoliviaInteligente on Unsplash"
image_source_url: "https://unsplash.com/photos/a-blue-glass-with-a-white-logo-fN4YeoA14OI?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - apple
  - tietoturva
  - haavoittuvuus
  - iphone
  - ipad
keywords:
  - "apple"
  - "tietoturva"
  - "haavoittuvuus"
  - "iphone"
  - "ipad"
source_name: "io-tech.fi"
source_url: "https://www.io-tech.fi/uutinen/useista-applen-jarjestelmapiireista-loytyi-haavoittuvuus-jota-ei-voida-korjata/"
source_domain: "io-tech.fi"
briefing: true
draft: false
---

Paradigm Shiftin tietoturvatutkijat ovat löytäneet useita Applen järjestelmäpiirejä koskevan haavoittuvuuden, jota tutkijoiden mukaan ei voida paikata. Usbliter8-niminen haavoittuvuus liittyy piirien USB-ohjaimiin ja koskee A12-, A13-, S4- ja S5-piirejä. Sen hyödyntäminen edellyttää fyysistä pääsyä laitteeseen, mutta onnistuessaan hyökkäys voi tuoda haittakoodia laitteen muistiin jo ennen käyttöjärjestelmän latautumista.

## Haavoittuvuus liittyy DFU-tilaan

Haavoittuvuutta voidaan hyödyntää Applen laitteiden Device Firmware Update- eli DFU-tilassa, jos hyökkääjä saa laitteen haltuunsa. DFU-tilassa hyökkääjä voi syöttää laitteelle haittakoodia ja saada USB-ohjaimen kirjoittamaan koodia eri muistiosoitteisiin kuin normaalisti.

Käytännössä tämä tarkoittaa, että haittakoodi voidaan saada laitteen muistiin hyvin varhaisessa käynnistysvaiheessa. Lähdetietojen mukaan sen avulla voidaan ohittaa esimerkiksi koodin allekirjoitusten tarkastuksia tai pakottaa laite suorittamaan muokattuja järjestelmäsovelluksia.

Vakavuutta lieventää se, että hyökkäys ei onnistu etänä, vaan vaatii fyysisen pääsyn kohdelaitteeseen. Lisäksi tutkijoiden mukaan järjestelmäpiirin Security Enclave on suojassa hyökkäyksiltä, mikä tekee kokonaisuudesta jonkin verran vähemmän vakavan.

## Koskee useita iPhone-, iPad- ja Watch-malleja

Rautabugiin ja firmwareen perustuva haavoittuvuus löytyy useista Applen piireistä, joten se koskee laitteita monesta tuoteryhmästä. iPhone-malleista haavoittuviksi mainitaan iPhone SE, XR, XS, XS Max, 11, 11 Pro ja 11 Pro Max.

iPad-mallistossa haavoittuvuus koskee 8. ja 9. sukupolven iPadeja, iPad Air 3:a sekä iPad mini 5:tä. Apple Watch -malleista mukana ovat Watch Series 4, Series 5 ja Watch SE. Lisäksi haavoittuvuus koskee Studio Displayta ja 2. sukupolven Apple TV 4K:ta.

## Korjausta ei ole löytynyt

Tutkijat ovat selvittäneet Applen kanssa mahdollisuuksia korjata ongelma, mutta ratkaisua ei lähdetietojen mukaan ole löytynyt. Koska haavoittuvuus perustuu rautabugiin ja firmwareen, tavallinen ohjelmistopäivitys ei lähdetietojen perusteella riitä sen poistamiseen. Käytännössä varmin tapa välttää haavoittuvuus on käyttää uudempaa laitetta, jota kyseinen ongelma ei koske.

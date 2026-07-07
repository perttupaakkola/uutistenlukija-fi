---
title: "Avoimen lähdekoodin Riddle muuttaa reMarkablen taikapäiväkirjaksi"
date: 2026-07-07T03:08:02.050431+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Maxime Rivestin Riddle-projekti tekee reMarkable Paper Pro -laitteesta tekoälyllä toimivan kirjoituspäiväkirjan, jossa käsinkirjoitettu viesti katoaa ja…"
summary: "Maxime Rivestin Riddle-projekti tekee reMarkable Paper Pro -laitteesta tekoälyllä toimivan kirjoituspäiväkirjan, jossa käsinkirjoitettu viesti katoaa ja vastaus ilmestyy sivulle kuin itsestään."
summary_bullets:
  - "Riddle muuttaa reMarkable Paper Pro -laitteen tekoälyllä toimivaksi päiväkirjakokemukseksi."
  - "Käyttäjä kirjoittaa kynällä, teksti katoaa ja vastaus piirtyy sivulle käsialamaisena tekstinä."
  - "Asennus vaatii kehittäjätilan, launcherin ja API-yhteyden OpenAI-yhteensopivaan rajapintaan."
key_points:
  - "Riddle muuttaa reMarkable Paper Pro -laitteen tekoälyllä toimivaksi päiväkirjakokemukseksi."
  - "Käyttäjä kirjoittaa kynällä, teksti katoaa ja vastaus piirtyy sivulle käsialamaisena tekstinä."
  - "Asennus vaatii kehittäjätilan, launcherin ja API-yhteyden OpenAI-yhteensopivaan rajapintaan."
journalist_note: |
  Artikkeli perustuu annettuihin lähdekatkelmiin. Yksityiskohtia on rajattu siihen, mitä paketissa kerrotaan projektin toiminnasta, asennuksesta ja teknisistä vaatimuksista.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: Avoimen lähdekoodin Riddle muuttaa reMarkablen taikapäiväkirjaksi (remarkable, tekoäly)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 1
tags:
  - remarkable
  - tekoäly
  - avoin lähdekoodi
  - riddle
  - sähkömuste
keywords:
  - "remarkable"
  - "tekoäly"
  - "avoin lähdekoodi"
  - "riddle"
  - "sähkömuste"
source_name: "Hacker News Best"
source_url: "https://github.com/MaximeRivest/Riddle"
source_domain: "hnrss.org"
briefing: true
draft: false
---

Maxime Rivestin kehittämä avoimen lähdekoodin Riddle-projekti muuttaa reMarkable Paper Pro -sähkömustetabletin kokemukseksi, joka muistuttaa Harry Potter -tarinoista tuttua Tom Riddlen päiväkirjaa. Käyttäjä kirjoittaa sivulle kynällä, odottaa hetken, ja teksti häviää näkyvistä ennen kuin tekoälyn vastaus piirtyy sivulle kaunokirjoitusta muistuttavana jälkenä.

## Kirjoittamista ilman chat-ikkunaa

Riddlen idea on erottaa tekoälyn käyttö tavallisesta chat-käyttöliittymästä. Projekti on suunniteltu tuntumaan enemmän muistikirjaan kirjoittamiselta kuin keskustelulta näytöllä olevan avustajan kanssa. Lähdekuvauksen mukaan sivulla ei ole näytön hehkua, näppäimistöä tai erillistä chat-näkymää, vaan vaikutelma syntyy siitä, että muste katoaa paperiin ja vastaus kirjoittuu takaisin vedoittain.

Käytännössä käyttäjä kirjoittaa viestin reMarkablen kynällä ja pysähtyy. Hetken kuluttua käsiala alkaa hävitä, sivu ikään kuin odottaa, ja vastaus ilmestyy näkyviin vähitellen. Myös vastaus häviää myöhemmin, mikä vahvistaa päiväkirjamaisen vaikutelman.

## Asennus vaatii kehittäjätilan

Riddle toimii reMarkable Paper Prolla, joka on asetettu kehittäjätilaan ja johon on asennettu launcher. Asennusta helpottaa remagic-työkalu, jonka kerrotaan ohjaavan kehittäjätilan käyttöönotossa ja tekevän perusasetukset yhdellä komennolla. Jos käyttäjällä on jo xovi ja AppLoad käytössä, Riddlen voi asentaa remagic-katalogista, valmiista paketista tai rakentaa lähdekoodista.

Tekoäly-yhteys tehdään API-avaimella OpenAI-yhteensopivaan /chat/completions-rajapintaan. Projektin kuvauksen mukaan se toimii esimerkiksi OpenAI:n, Groqin, paikallisen palvelimen ja muiden samaa formaattia tukevien ratkaisujen kanssa. Mallin on oltava kuvantunnistusta tukeva. Tabletilla asetukset sijaitsevat oracle.env-tiedostossa binäärin vieressä, ja remagic config riddle tarjoaa valmiita asetuksia joillekin palveluille.

Teknisissä huomioissa mainitaan, että niin sanottujen ajattelumallien kanssa ensimmäistä vastausta voi nopeuttaa asettamalla päättelytason matalaksi, jos palveluntarjoaja tukee asetusta. Lisäksi token-raja on syytä pitää riittävän suurena, koska piilotettu päättely voi kuluttaa osan kiintiöstä ennen näkyvää vastausta. Laitteella ensimmäisen musteen ilmestymisajaksi on mitattu noin 0,9-1,1 sekuntia.

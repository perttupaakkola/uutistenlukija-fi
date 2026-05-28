---
title: "Internetin rakenteita muokataan tekoälyagenttien käyttöön"
date: 2026-05-28T21:58:07.169787+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Tekoälyagenttien siirtyminen kokeiluista tuotantokäyttöön muuttaa pilvi-infrastruktuurin vaatimuksia. AWS on julkaissut uuden OpenSearch Serverless -ver…"
summary: "Tekoälyagenttien siirtyminen kokeiluista tuotantokäyttöön muuttaa pilvi-infrastruktuurin vaatimuksia. AWS on julkaissut uuden OpenSearch Serverless -version, ja sama koneellisen liikenteen kasvu näkyy myös kiistoissa verkkoarkistojen käytöstä tekoälyn koulutusaineistona."
summary_bullets:
  - "Tekoälyagentit voivat aiheuttaa pilvipalveluille nopeita ja vaikeasti ennakoitavia kuormituspiikkejä."
  - "AWS julkaisi uuden OpenSearch Serverless -version agenttipohjaisia työkuormia varten."
  - "Koneellisen käytön kasvu näkyy myös kiistoissa siitä, miten verkkoarkistoja käytetään tekoälyn koulutusaineistona."
key_points:
  - "Tekoälyagentit voivat aiheuttaa pilvipalveluille nopeita ja vaikeasti ennakoitavia kuormituspiikkejä."
  - "AWS julkaisi uuden OpenSearch Serverless -version agenttipohjaisia työkuormia varten."
  - "Koneellisen käytön kasvu näkyy myös kiistoissa siitä, miten verkkoarkistoja käytetään tekoälyn koulutusaineistona."
journalist_note: |
  Artikkeli laajennettiin source-backed writer shortfall -korjauksena käyttäen packetin TechCrunch- ja The Next Web -katkelmien faktatietoja ilman lähteiden ulkopuolista lisäystä.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1690627931320-16ac56eb2588?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwyfHxjbG91ZCUyMGNvbXB1dGluZyUyMHRlY2hub2xvZ3l8ZW58MXwwfHx8MTc4MDAwNTQ4NXww&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1690627931320-16ac56eb2588?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwyfHxjbG91ZCUyMGNvbXB1dGluZyUyMHRlY2hub2xvZ3l8ZW58MXwwfHx8MTc4MDAwNTQ4NXww&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Internetin rakenteita muokataan tekoälyagenttien käyttöön (tekoäly, pilvipalvelut)"
image_credit: "Photo by Hazel Z on Unsplash"
image_source_url: "https://unsplash.com/photos/a-computer-screen-with-a-cloud-shaped-object-on-top-of-it-FocSgUZ10JM?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - tekoäly
  - pilvipalvelut
  - aws
  - internet
  - infrastruktuuri
keywords:
  - "tekoäly"
  - "pilvipalvelut"
  - "aws"
  - "internet"
  - "infrastruktuuri"
source_name: "TechCrunch"
source_url: "https://techcrunch.com/2026/05/28/the-internet-is-being-rebuilt-for-machines/"
source_domain: "techcrunch.com"
briefing: true
draft: false
---

Tekoälyagenttien yleistyminen on alkanut muuttaa sitä, millaiselle käytölle internetin ja pilvipalvelujen perusrakenteita suunnitellaan. Ihmiskäyttäjien sijaan yhä suurempi osa kuormasta voi syntyä ohjelmistoista, jotka tekevät hetkessä hakuja, kutsuvat rajapintoja ja käsittelevät suuria määriä tietoa.

## Ihmisten rytmistä agenttien purskeisiin

Pilvi-infrastruktuuri on pitkään rakennettu käytölle, jossa ihmiset hakevat tietoa, klikkaavat linkkejä, selaavat sivuja ja katsovat sisältöjä melko ennakoitavassa tahdissa. Tekoälyagentit eivät kuitenkaan toimi samalla tavalla. Ne voivat käynnistää useita alitehtäviä, kysellä satoja tietokantoja, etsiä asiakirjoista tietoa ja kutsua ohjelmointirajapintoja muutamassa sekunnissa.

Tällainen liikenne voi syntyä nopeasti ja myös päättyä nopeasti. Se tekee kuormasta vaikeammin ennakoitavaa kuin perinteinen verkkokäyttö, jossa käyttäjämäärät ja käyttötavat muuttuvat usein tasaisemmin. Siksi infrastruktuurin on kyettävä vastaamaan äkillisiin piikkeihin ilman, että kapasiteettia pidetään jatkuvasti varattuna tyhjäkäyntiä varten.

## AWS uudistaa hakupalveluaan

Amazonin pilviyksikkö AWS on vastannut muutokseen julkaisemalla torstaina uuden sukupolven OpenSearch Serverless -palvelustaan. Kyse on täysin hallinnoidusta haku- ja vektoritietokannasta, jonka tarkoitus on tallentaa ja hakea tietoa suuressa mittakaavassa.

AWS:n mukaan uusi järjestelmä on suunniteltu erityisesti agenttipohjaisille työkuormille. Palvelun kerrotaan pystyvän kasvattamaan kapasiteettiaan heti, kun agentit käynnistävät tehtäviä, ja skaalautumaan takaisin nollaan, kun käyttöä ei ole. Tämä vastaa tilanteeseen, jossa agentti voi hetkellisesti synnyttää suuren määrän hakuja ja rajapintakutsuja ja kadota sen jälkeen yhtä nopeasti.

## Arkistot joutuvat samaan paineeseen

Koneellisen käytön kasvu näkyy myös muualla verkon infrastruktuurissa. Suuret kielimallit tarvitsevat valtavia määriä laadukasta tekstiä, ja vuosikymmenten aikana kertynyt uutisaineisto on niille arvokasta koulutusmateriaalia. Internet Archiven Wayback Machine tarjoaa arkistoitua verkkosisältöä rajapintojen ja osoitteiden kautta, ja vuoden 2023 Washington Postin analyysin mukaan Internet Archivesta peräisin olevaa dataa oli esiintynyt merkittävissä tekoälyn koulutusaineistoissa.

The New York Times, CNN, USA Today, The Guardian ja vähintään 241 muuta uutisorganisaatiota yhdeksässä maassa ovat ryhtyneet rajoittamaan Archiven indeksoijia. Internet Archive on säilyttänyt yli biljoona verkkosivua vuodesta 1996 lähtien, ja sitä käyttävät muun muassa tuomioistuimet, toimittajat ja historioitsijat. Rajoitusten taustalla on kustantajien huoli siitä, että tekoäly-yhtiöt käyttävät arkistoitua uutisaineistoa mallien kouluttamiseen ilman lupaa tai korvausta.

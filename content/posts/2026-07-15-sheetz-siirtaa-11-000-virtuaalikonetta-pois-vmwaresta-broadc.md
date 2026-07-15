---
title: "Sheetz siirtää 11 000 virtuaalikonetta pois VMwaresta – Broadcomin lisenssimuutokset painoivat päätöksessä"
date: 2026-07-15T21:59:36.236898+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Yhdysvaltalainen Sheetz vaihtaa 838 toimipaikassaan VMware vSpheren StorMagicin SvHCI-alustaan. Yli 600 myymälää on jo siirretty, ja nykyiset Dell-palve…"
summary: "Yhdysvaltalainen Sheetz vaihtaa 838 toimipaikassaan VMware vSpheren StorMagicin SvHCI-alustaan. Yli 600 myymälää on jo siirretty, ja nykyiset Dell-palvelimet jäävät käyttöön."
summary_bullets:
  - "Hanke kattaa 838 toimipaikkaa ja noin 11 000 virtuaalikonetta."
  - "Yli 600 myymälän järjestelmät on jo siirretty StorMagicin SvHCI-alustalle."
  - "Sheetzin mukaan Broadcomin tilausmalli ja viiden vuoden sitoumus lisäsivät kustannuksiin liittyvää epävarmuutta."
key_points:
  - "Hanke kattaa 838 toimipaikkaa ja noin 11 000 virtuaalikonetta."
  - "Yli 600 myymälän järjestelmät on jo siirretty StorMagicin SvHCI-alustalle."
  - "Sheetzin mukaan Broadcomin tilausmalli ja viiden vuoden sitoumus lisäsivät kustannuksiin liittyvää epävarmuutta."
journalist_note: |
  Kustannussäästöä koskeva arvio on Sheetzin edustajan lausunto, eikä aineistossa annettu säästölle rahamääräistä arviota.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: Sheetz siirtää 11 000 virtuaalikonetta pois VMwaresta – Broadcomin lisenssimuutokset painoivat päätöksessä (sheetz, vmware)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 2
tags:
  - sheetz
  - vmware
  - broadcom
  - stormagic
  - virtualisointi
keywords:
  - "sheetz"
  - "vmware"
  - "broadcom"
  - "stormagic"
  - "virtualisointi"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/information-technology/2026/07/sheetz-moves-838-stores-off-vmware-broadcom-created-too-much-uncertainty/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Yhdysvaltalainen lähikauppaketju Sheetz vaihtaa kaikkien 838 toimipaikkansa virtualisointialustan VMware vSpherestä StorMagicin SvHCI:hin. Hanke koskee lopulta noin 11 000:ta virtuaalikonetta. Ratkaisun taustalla ovat Sheetzin mukaan Broadcomin lisenssimuutokset, ennakoidut hinnankorotukset ja pitkän sopimuksen aiheuttama epävarmuus.

## Nykyiset palvelimet jäävät käyttöön

Sheetz on käyttänyt VMware-virtualisointia myymälöissään vuodesta 2019. Jokaisen toimipaikan järjestelmä toimii kahdella Dellin R440- tai R450-sarjan palvelimella. Ketju aikoo pitää nykyisen palvelinlaitteiston käytössä, joten uuden virtualisointialustan asentaminen ei edellytä laiteuudistusta.

Yhdessä myymälässä VMwaresta siirretään tavallisesti 12–14 virtuaalikonetta. Lisäksi kaksi virtuaalikonetta on tarkoitus korvata lähikuukausina Windows 10:stä Windows 11:een siirtymisen yhteydessä. Yli 600 toimipaikan siirto on jo valmis, ja työ on edennyt keskimäärin 200 myymälän kuukausivauhtia. Sheetzin ilmoituksen mukaan koko hankkeen pitäisi valmistua neljässä kuukaudessa.

## Tilausmalli vaikeutti kustannusten ennakointia

Sheetzin infrastruktuuritiimin johtaja Scott Robertson kertoi Ars Technicalle, että Broadcomin tekemiin muutoksiin kuuluivat pysyvien lisenssien poistaminen ja niiden korvaaminen laajoihin ohjelmistopaketteihin perustuvilla tilauksilla. Robertsonin mukaan ennakoidut hinnankorotukset, pakollinen tilausmalli ja viiden vuoden sitoumus vaikeuttivat pitkän aikavälin budjetointia ja lisäsivät riippuvuutta yhdestä toimittajasta.

Sheetz päätyi StorMagicin ratkaisuun, koska ketju oli käyttänyt yhtiön SvSAN-virtuaalitallennusta VMware-ympäristön rinnalla kriittisissä myymäläsovelluksissa vuodesta 2019. VMwarelle löytyy useita kilpailijoita, mutta sen pitkään kehitetyn ominaisuusvalikoiman korvaaminen voi silti olla organisaatioille vaativa hanke.

## Siirrot tehdään etäyhteydellä

Sheetzin alustasuunnittelusta vastaavan johtajan Gary Sliverin mukaan ensimmäinen käyttöönotto osoitti, että SvHCI tarjosi hajautetussa myymäläympäristössä tarvittavan vikasietoisuuden ja keskitetyn hallinnan. Teknikoita ei hänen mukaansa ole tarvinnut lähettää erikseen jokaiseen toimipaikkaan.

Robertson arvioi, että etänä ja ilman palvelinpäivityksiä toteutettava siirtymä tuo Sheetzille merkittäviä säästöjä. Hankkeen laajentaminen koko ketjun kattavaksi on kuitenkin edellyttänyt automaatiota. Robertsonin mukaan automaatio ja SvHCI:n VMware-virtuaalikoneiden tuontityökalu ovat olleet välttämättömiä siirtojen toteuttamisessa tässä mittakaavassa.

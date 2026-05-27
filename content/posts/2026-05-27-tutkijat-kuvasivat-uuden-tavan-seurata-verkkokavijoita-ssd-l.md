---
title: "Tutkijat kuvasivat uuden tavan seurata verkkokävijöitä SSD-levyn ajoitusten avulla"
date: 2026-05-27T21:38:05.616347+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "FROST-niminen menetelmä hyödyntää selaimen ja SSD-tallennuksen ajoituksia ja voi paljastaa, mitä sivuja ja sovelluksia käyttäjällä on auki."
summary: "FROST-niminen menetelmä hyödyntää selaimen ja SSD-tallennuksen ajoituksia ja voi paljastaa, mitä sivuja ja sovelluksia käyttäjällä on auki."
summary_bullets:
  - "FROST mittaa selaimessa SSD-levyn tallennusoperaatioiden ajoituksia."
  - "Tutkijoiden mukaan tekniikka voi paljastaa avoimia sivustoja ja käynnissä olevia sovelluksia."
  - "Menetelmä toimii ilman käyttäjän lisätoimia, jos tämä avaa hyökkäystä isännöivän sivun."
key_points:
  - "FROST mittaa selaimessa SSD-levyn tallennusoperaatioiden ajoituksia."
  - "Tutkijoiden mukaan tekniikka voi paljastaa avoimia sivustoja ja käynnissä olevia sovelluksia."
  - "Menetelmä toimii ilman käyttäjän lisätoimia, jos tämä avaa hyökkäystä isännöivän sivun."
journalist_note: |
  Artikkeli perustuu annettuun tutkimusta kuvaavaan lähdepakettiin; aktiivisesta laajamittaisesta hyväksikäytöstä ei paketissa esitetty näyttöä.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1518770660439-4636190af475?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxjb21wdXRlciUyMHRlY2hub2xvZ3klMjByZXNlYXJjaHxlbnwxfDB8fHwxNzc5OTE3ODgzfDA&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1518770660439-4636190af475?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxjb21wdXRlciUyMHRlY2hub2xvZ3klMjByZXNlYXJjaHxlbnwxfDB8fHwxNzc5OTE3ODgzfDA&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Tutkijat kuvasivat uuden tavan seurata verkkokävijöitä SSD-levyn ajoitusten avulla (tietoturva, yksityisyys)"
image_credit: "Photo by Alexandre Debiève on Unsplash"
image_source_url: "https://unsplash.com/photos/macro-photography-of-black-circuit-board-FO7JIlwjOtU?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - tietoturva
  - yksityisyys
  - selaimet
  - ssd
  - verkkoseuranta
keywords:
  - "tietoturva"
  - "yksityisyys"
  - "selaimet"
  - "ssd"
  - "verkkoseuranta"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/security/2026/05/websites-have-a-new-way-to-spy-on-visitors-analyzing-their-ssd-activity/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Tutkijat ovat kuvanneet uuden verkkoselaimessa toimivan seurantamenetelmän, joka mittaa käyttäjän SSD-levyyn liittyviä hienovaraisia ajoituseroja. FROSTiksi nimetty tekniikka voi tutkimuksen mukaan auttaa päättelemään, mitä muita verkkosivuja käyttäjällä on avoinna ja mitä sovelluksia laitteella on käynnissä, kun käyttäjä avaa hyökkäystä isännöivän sivuston.

## Sivukanava syntyy jaetusta resurssista

FROST tulee sanoista fingerprinting remotely using OPFS-based SSD timing. Menetelmä perustuu niin sanottuun contention side channel -hyökkäykseen eli sivukanavaan, jossa päätelmiä tehdään useiden prosessien kilpaillessa samasta resurssista. Tässä tapauksessa tarkkailun kohteena ovat SSD-levyn I/O-toimintojen ajoitukset.

Ajatus ei ole, että sivusto lukisi suoraan muiden välilehtien tai sovellusten sisältöä. Sen sijaan se mittaa, kuinka kauan tietyt tallennusoperaatiot kestävät, ja etsii näistä mittauksista malleja. Tutkijoiden mukaan tällainen ajoitustieto voi riittää päättelemään, mitä sivustoja on auki muissa välilehdissä, jopa toisissa selaimissa, sekä mitä sovelluksia laitteella on käynnissä.

Menetelmä ei vaadi käyttäjältä muuta toimintaa kuin hyökkäävän sivun avaamisen. Tämä tekee havainnosta huolestuttavan yksityisyyden kannalta, koska hyökkäys voi tapahtua tavallisen verkkosivun yhteydessä ilman erillistä lupapyyntöä tai näkyvää varoitusta.

## Selainten uudet ominaisuudet kasvattavat hyökkäyspintaa

Tutkimuksessa FROSTin kuvataan toimivan kokonaan selaimessa. Se käyttää JavaScriptiä ja selainten OPFS-ominaisuutta, eli Origin Private File System -tallennustilaa. OPFS on sivustokohtainen tallennusalue, jonka avulla verkkosovellukset voivat suorittaa tehtäviä tehokkaammin selaimen sisällä.

Taustalla on laajempi muutos: selaimet eivät ole enää vain dokumenttien katseluohjelmia, vaan niissä ajetaan yhä raskaampia sovelluksia. Toimisto-ohjelmat, kuva- ja videoeditorit sekä kehitysympäristöt voivat toimia kokonaan verkkoselaimessa. Samalla selaimen käytettävissä olevat paikalliset resurssit ovat monipuolistuneet.

Tutkijoiden mukaan tämä kehitys laajentaa selaimen hyökkäyspintaa. FROST on esimerkki siitä, miten hyödylliseksi tarkoitettu selainominaisuus voi muodostaa uuden yksityisyysriskin, kun sitä yhdistetään tarkkoihin ajoitusmittauksiin. Kyse on tutkimuksessa esitetystä tekniikasta, ei todisteesta laajasta aktiivisesta hyväksikäytöstä, mutta havainto korostaa tarvetta arvioida selainten tallennusrajapintojen sivuvaikutuksia entistä tarkemmin.

---
title: "Tutkija: Applen Hide My Email -toiminnon haavoittuvuus voi paljastaa oikean sähköpostiosoitteen"
date: 2026-07-01T21:58:07.013057+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Applen iCloud+-palveluun kuuluvaa Hide My Email -toimintoa koskeva haavoittuvuus voi tutkijoiden mukaan paljastaa käyttäjän oikean sähköpostiosoitteen a…"
summary: "Applen iCloud+-palveluun kuuluvaa Hide My Email -toimintoa koskeva haavoittuvuus voi tutkijoiden mukaan paljastaa käyttäjän oikean sähköpostiosoitteen aliasosoitteen takaa."
summary_bullets:
  - "Tutkijoiden mukaan Applen Hide My Email -toiminnossa on haavoittuvuus, joka voi paljastaa käyttäjän oikean sähköpostiosoitteen."
  - "404 Media kertoo testanneensa ja vahvistaneensa ongelman olemassaolon."
  - "Haavoittuvuuden löytänyt Tyler Murphy sanoo ilmoittaneensa asiasta Applelle yli vuosi sitten."
key_points:
  - "Tutkijoiden mukaan Applen Hide My Email -toiminnossa on haavoittuvuus, joka voi paljastaa käyttäjän oikean sähköpostiosoitteen."
  - "404 Media kertoo testanneensa ja vahvistaneensa ongelman olemassaolon."
  - "Haavoittuvuuden löytänyt Tyler Murphy sanoo ilmoittaneensa asiasta Applelle yli vuosi sitten."
journalist_note: |
  Artikkeli perustuu lähdepaketin yhtäpitäviin tietoihin haavoittuvuudesta, sen väitetystä testauksesta ja ilmoittamisesta Applelle. Mahdollisen väärinkäytön laajuutta ei väitetä, koska sitä ei lähteissä vahvisteta.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1585184394271-4c0a47dc59c9?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxBcHBsZSUyMHByaXZhY3klMjBmZWF0dXJlJTIwdnVsbmVyYWJpbGl0eXxlbnwxfDB8fHwxNzgyOTQzMDg1fDA&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1585184394271-4c0a47dc59c9?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxBcHBsZSUyMHByaXZhY3klMjBmZWF0dXJlJTIwdnVsbmVyYWJpbGl0eXxlbnwxfDB8fHwxNzgyOTQzMDg1fDA&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Tutkija: Applen Hide My Email -toiminnon haavoittuvuus voi paljastaa oikean sähköpostiosoitteen (apple, icloud+)"
image_credit: "Photo by Laurenz Heymann on Unsplash"
image_source_url: "https://unsplash.com/photos/apple-logo-on-glass-window-wAygsCk20h8?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 1
tags:
  - apple
  - icloud+
  - tietoturva
  - yksityisyys
  - sähköposti
keywords:
  - "apple"
  - "icloud+"
  - "tietoturva"
  - "yksityisyys"
  - "sähköposti"
source_name: "TechCrunch"
source_url: "https://techcrunch.com/2026/07/01/apples-hide-my-email-feature-has-a-bug-thats-been-exposing-real-email-addresses-researcher-claims/"
source_domain: "techcrunch.com"
draft: false
---

Applen Hide My Email -yksityisyystoiminnosta on löytynyt haavoittuvuus, jonka väitetään voivan paljastaa käyttäjän oikean sähköpostiosoitteen aliasosoitteen takaa. 404 Media kertoo testanneensa ja vahvistaneensa ongelman, ja haavoittuvuuden löytänyt tutkija Tyler Murphy sanoo ilmoittaneensa siitä Applelle jo yli vuosi sitten.

## Aliasosoitteiden tarkoitus on suojata käyttäjää

Hide My Email on iCloud+-palveluun kuuluva ominaisuus, jonka tarkoituksena on vähentää käyttäjän varsinaisen sähköpostiosoitteen leviämistä verkossa. Toiminnon avulla käyttäjä voi luoda yksilöllisiä ja satunnaisia sähköpostiosoitteita esimerkiksi sovelluksiin, verkkosivuille ja muihin verkkopalveluihin rekisteröitymistä varten.

Näihin aliasosoitteisiin lähetetyt viestit välitetään edelleen käyttäjän oikeaan sähköpostilaatikkoon. Applen omien tukisivujen mukaan Hide My Email on suunniteltu auttamaan käyttäjiä pitämään henkilökohtainen sähköpostiosoitteensa yksityisenä. Toiminnon hyöty perustuu siihen, ettei palvelulle annettu osoite paljasta suoraan käyttäjän varsinaista yhteystietoa.

## Tutkijat kertovat haavoittuvuuden toimivan

Uuden raportoinnin mukaan haavoittuvuus voi kuitenkin murentaa tämän suojan. Yksityisyyspalveluja tarjoava EasyOptOuts kertoi 404 Medialle löytäneensä palvelusta ongelman, jonka avulla Hide My Email -aliasosoitteeseen liitetty oikea sähköpostiosoite voitaisiin saada selville. TechCrunchin mukaan tutkimus viittaa siihen, että virhe voi tehdä ominaisuudesta käytännössä hyödyttömän sen keskeisen yksityisyystarkoituksen kannalta.

Murphyn mukaan hän varoitti Applea haavoittuvuudesta yli vuosi sitten. Hänen mukaansa on epäselvää, miksi yhtiö ei ole vielä korjannut ongelmaa. Murphy sanoi myös, että kaikki yritykset hyödyntää haavoittuvuutta ovat onnistuneet.

## Korjauksen aikataulu on epäselvä

Saatavilla olevissa tiedoissa ei kerrota, kuinka laajasti haavoittuvuutta olisi mahdollisesti hyödynnetty todellisissa tilanteissa. Raportoinnin ydin on kuitenkin selvä: tutkijoiden mukaan ongelma on olemassa, sitä on testattu, ja se on saattanut olla korjaamatta yli vuoden. Jos aliasosoite voidaan yhdistää oikeaan sähköpostiosoitteeseen, käyttäjän anonymiteetti heikkenee juuri siinä kohdassa, jota ominaisuuden on tarkoitus suojata.

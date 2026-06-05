---
title: "Suosittua Sound Blaster -kaiutinta voi käyttää hyökkäyksen välikappaleena Bluetoothin kautta"
date: 2026-06-05T21:18:06.205003+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Tutkija Rasmus Moorats löysi Sound Blaster Katana V2X -soundbarista tavan muuttaa laitteen toimintaa niin, että kaiutin voi välittää komentoja siihen li…"
summary: "Tutkija Rasmus Moorats löysi Sound Blaster Katana V2X -soundbarista tavan muuttaa laitteen toimintaa niin, että kaiutin voi välittää komentoja siihen liitetylle tietokoneelle."
summary_bullets:
  - "Rasmus Moorats löysi Sound Blaster Katana V2X -soundbarista haavoittuvan toimintatavan tutkiessaan omaa laitettaan."
  - "Kaiutin kommunikoi CTP-mekanismin kautta ja voi vastaanottaa komentoja Bluetoothin tai USB:n yli."
  - "Tutkija havaitsi, että laitteen USB-kuvaajajoukkoa voi muuttaa, mikä voi vaikuttaa siihen, miten kaiutin näyttäytyy liitetylle tietokoneelle."
key_points:
  - "Rasmus Moorats löysi Sound Blaster Katana V2X -soundbarista haavoittuvan toimintatavan tutkiessaan omaa laitettaan."
  - "Kaiutin kommunikoi CTP-mekanismin kautta ja voi vastaanottaa komentoja Bluetoothin tai USB:n yli."
  - "Tutkija havaitsi, että laitteen USB-kuvaajajoukkoa voi muuttaa, mikä voi vaikuttaa siihen, miten kaiutin näyttäytyy liitetylle tietokoneelle."
journalist_note: |
  Artikkeli perustuu annettuihin lähdekatkelmiin. Valmistajan mahdollisesta korjauksesta tai hyväksikäytön käytännön laajuudesta ei ollut lähdeaineistossa vahvistettua tietoa.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1531104985437-603d6490e6d4?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxTb3VuZCUyMEJsYXN0ZXIlMjBLYXRhbmElMjBWMlglMjBzcGVha2VyfGVufDF8MHx8fDE3ODA2OTQyODR8MA&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1531104985437-603d6490e6d4?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxTb3VuZCUyMEJsYXN0ZXIlMjBLYXRhbmElMjBWMlglMjBzcGVha2VyfGVufDF8MHx8fDE3ODA2OTQyODR8MA&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Suosittua Sound Blaster -kaiutinta voi käyttää hyökkäyksen välikappaleena Bluetoothin kautta (tietoturva, bluetooth)"
image_credit: "Photo by Paul Esch-Laurent on Unsplash"
image_source_url: "https://unsplash.com/photos/black-speaker-on-table-YU-OA2TvQRQ?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - tietoturva
  - bluetooth
  - creative technologies
  - sound blaster
  - freertos
keywords:
  - "tietoturva"
  - "bluetooth"
  - "creative technologies"
  - "sound blaster"
  - "freertos"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/security/2026/06/highly-reviewed-speaker-can-be-hacked-over-the-air-to-infect-connected-devices/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Creative Technologiesin Sound Blaster Katana V2X -soundbarista on löytynyt haavoittuva toimintatapa, jonka avulla hyökkääjä voi Bluetooth-kantaman sisältä muuttaa kaiuttimen toimintaa ja käyttää sitä välikappaleena siihen yhdistettyä tietokonetta vastaan. Havainnon teki tutkija Rasmus Moorats, joka selvitti alun perin, voisiko hän rakentaa Linux-työkalun kommunikoimaan oman kaiuttimensa kanssa.

## Löytö syntyi oman laitteen tutkimisesta

Katana V2X on soundbar, joka voidaan yhdistää PC-, Mac- ja Linux-laitteisiin USB:n tai Bluetoothin kautta. Moorats havaitsi, että laitteen kanssa voi keskustella CTP-mekanismin kautta. Hän arveli lyhenteen viittaavan Creative Transport Protocoliin.

CTP:n kautta Bluetoothilla tai USB:llä yhdistetyt laitteet voivat lähettää kaiuttimelle komentoja. Niillä voidaan esimerkiksi vaihtaa LED-valojen värejä ja taajuuskorjaimen asetuksia. Sama mekanismi mahdollistaa myös vastausten vastaanottamisen kaiuttimelta.

Havainto on merkittävä siksi, että käyttöjärjestelmät pyrkivät normaalisti estämään etälaitteilta tulevat vaaralliset komennot monilla suojauksilla. Tässä tapauksessa hyökkäysketju nojaa siihen, että luotetuksi oheislaitteeksi mielletty kaiutin voi saada uuden roolin siihen kytketyn laitteen näkökulmasta.

## Kaiutin voi esiintyä oheislaitteena

Tutkimuksen aikana Moorats onnistui korvaamaan kaiuttimen laiteohjelmiston omalla testikuvallaan, joka näytti kaiuttimen LED-näytössä vain sanan ”patched”. Sen jälkeen hän tutki Katana V2X:ssä käytettyä FreeRTOS-käyttöjärjestelmää.

FreeRTOS-ympäristössä oli HID-toimintoja, joiden avulla laite voi toimia ihmisen käyttöliittymälaitteena. Tähän luokkaan kuuluvat esimerkiksi näppäimistöt, hiiret ja verkkokamerat. Katana V2X:n toteutus oli rajattu: kaiutin pystyi esimerkiksi äänenvoimakkuuden säätöön sekä toiston käynnistämiseen ja pysäyttämiseen.

Moorats kuitenkin havaitsi, että kaiuttimen USB-kuvaajajoukkoa pystyi muuttamaan. Tällainen kuvaus kertoo tietokoneelle tai muulle isäntälaitteelle, millaisia ominaisuuksia USB- tai Bluetooth-oheislaitteella on. Jos hyökkääjä pystyy vaikuttamaan siihen, miten kaiutin esittäytyy, kaiuttimesta voi tulla reitti komentojen välittämiseen liitetylle järjestelmälle.

Tiedossa olevien lähdetietojen perusteella tapaus koskee nimenomaan Creative Technologiesin Sound Blaster Katana V2X -mallia. Julkiset tiedot eivät kerro, onko valmistaja julkaissut korjausta tai kuinka laajasti hyökkäys olisi käytännössä toistettavissa tavallisten käyttäjien ympäristöissä.

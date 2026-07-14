---
title: "ESET: Vanhat shim-tiedostot mahdollistavat Secure Bootin ohittamisen"
date: 2026-07-14T23:18:44.316223+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Microsoftin allekirjoittamat mutta peruuttamatta jääneet shim-tiedostot voivat mahdollistaa Secure Boot -suojauksen kiertämisen sekä Windows- että Linux…"
summary: "Microsoftin allekirjoittamat mutta peruuttamatta jääneet shim-tiedostot voivat mahdollistaa Secure Boot -suojauksen kiertämisen sekä Windows- että Linux-laitteissa."
summary_bullets:
  - "ESET tunnisti 11 viallista mutta yhä Microsoftin allekirjoittamaa shim-laiteohjelmistokuvaa."
  - "Peruuttamatta jääneitä tiedostoja voidaan käyttää Secure Boot -suojauksen ohittamiseen."
  - "Haitallinen laiteohjelmisto voi säilyä käyttöjärjestelmän uudelleenasennuksen tai kiintolevyn vaihdon jälkeen."
key_points:
  - "ESET tunnisti 11 viallista mutta yhä Microsoftin allekirjoittamaa shim-laiteohjelmistokuvaa."
  - "Peruuttamatta jääneitä tiedostoja voidaan käyttää Secure Boot -suojauksen ohittamiseen."
  - "Haitallinen laiteohjelmisto voi säilyä käyttöjärjestelmän uudelleenasennuksen tai kiintolevyn vaihdon jälkeen."
journalist_note: |
  Tekniset väitteet ja seuraukset on rajattu aineistossa vahvistettuihin tietoihin. Paketti ei sisältänyt käyttäjäkohtaisia torjunta- tai päivitysohjeita.
content_type: "article"
editorial_reviewed: true
image: "/images/categories/teknologia.jpg"
image_thumb: "/images/categories/teknologia.jpg"
image_alt: "Kuvituskuva uutiseen: ESET: Vanhat shim-tiedostot mahdollistavat Secure Bootin ohittamisen (microsoft, secure boot)"
image_source: "category_fallback"
image_source_type: "category_fallback"
image_decision_reason: "generated fallback unavailable, unsafe, or failed after stock rejection"
image_visual_judge_score: 0
image_prompt_version: "image-flow-v2-2026-07-03"
image_category_fallback: true
reading_time: 2
tags:
  - microsoft
  - secure boot
  - uefi
  - eset
  - tietoturva
keywords:
  - "microsoft"
  - "secure boot"
  - "uefi"
  - "eset"
  - "tietoturva"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/security/2026/07/microsoft-secure-boot-has-been-broken-for-most-of-its-existence/"
source_domain: "arstechnica.com"
briefing: true
draft: false
---

Microsoftin kehittämä Secure Boot -standardi on suunniteltu suojaamaan Windows- ja myöhemmin myös Linux-laitteita laiteohjelmistotartunnoilta. Tietoturvayhtiö ESETin tutkijoiden mukaan suojaus on kuitenkin ollut helposti ohitettavissa 13 vuotta standardin 14-vuotisen historian aikana. Tutkijat jäljittivät ongelman vanhoihin, viallisiksi tiedettyihin shim-ohjelmistoihin, jotka ovat pysyneet Microsoftin allekirjoittamina ja järjestelmän luottamina. Näin alan laajuisen suojauksen keskeinen tarkistus on voitu kiertää ilman uuden haavoittuvuuden löytämistä.

## Viallisten tiedostojen luottamusta ei peruttu

ESET tunnisti yhteensä 11 tällaista laiteohjelmistokuvaa, joista ainakin yksi on vuodelta 2013. Kuvien tiedettiin olevan viallisia, mutta ne säilyivät Microsoftin digitaalisesti allekirjoittamina ja julkisesti saatavilla. Microsoft valvoo shim-ohjelmistojen allekirjoittamista, mutta kuvien luottamusta ei peruttu haavoittuvuuksien löytymisen jälkeen. Siksi Secure Boot saattoi hyväksyä vanhat versiot edelleen osaksi luotettua käynnistysketjua.

Shim-ohjelmistot kehitettiin laajentamaan Secure Bootin käyttöä Linux-laitteisiin ja erilaisiin apuohjelmiin. Itse suojaus on sijoitettu tietokoneen emolevyn UEFI-laiteohjelmistoon, ja sen toiminta perustuu käynnistyksessä käytettävien osien digitaalisiin allekirjoituksiin. Kun vanha shim on edelleen hyväksytty, hyökkääjä voi käyttää sitä ketjun luottamuksen murtamiseen. Ongelma ei siis johdu siitä, ettei tiedostoja olisi tunnistettu viallisiksi, vaan siitä, että niiden aiempaa hyväksyntää ei poistettu.

## Hyökkäys ei edellytä uutta haavoittuvuutta

ESETin tutkija Martin Smolár korosti, ettei vanhojen shimien vaara perustu uuteen haavoittuvuuteen. Hyökkääjä tarvitsee vain kopion vanhasta, yhä luotetusta mutta peruuttamatta jääneestä shim-tiedostosta sekä perustiedot siitä, miten UEFI:n shimit toimivat. Monimutkaisia hyväksikäyttömenetelmiä ei tarvita. Lähdeaineiston mukaan tekniikka on niin yksinkertainen, että sen voi toteuttaa myös aloitteleva hyökkääjä.

Kun tällainen shim asennetaan laitteeseen, hyökkääjä voi ohittaa digitaalisesti allekirjoitettujen käynnistysosien vaaditun ketjun. Tämän jälkeen laitteeseen voidaan asentaa haitallinen laiteohjelmisto, joka latautuu jo käynnistysprosessin varhaisessa vaiheessa. Varhainen latautuminen tekee haittaohjelmistosta sitkeän: se voi säilyä laitteessa käyttöjärjestelmän uudelleenasennuksen jälkeen ja jopa silloin, kun tietokoneen kiintolevy vaihdetaan.

Uhka ulottuu sekä Windows- että Linux-käyttäjiin, koska sama shim voidaan asentaa kumpaakin käyttöjärjestelmää käyttäviin laitteisiin. Tutkijoiden kuvaamassa hyökkäyksessä ratkaiseva väline ei ole uusi hyväksikäyttökoodi vaan vanha, yhä kelvolliseksi tunnistettu tiedosto. Jo yhden tällaisen kopion ja UEFI-shimien perustuntemuksen yhdistelmä riittää Smolárin mukaan ohittamaan Secure Bootin kaltaisen keskeisen suojausominaisuuden.

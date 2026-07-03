---
title: "Uusi PamStealer-haittaohjelma naamioituu Macin leikepöytäsovellukseksi"
date: 2026-07-02T21:48:06.116363+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "Tietoturvatutkijat ovat kuvanneet uuden macOS-haittaohjelman, joka varastaa tunnistetietoja poikkeuksellisen hiljaisella toteutustavalla."
summary: "Tietoturvatutkijat ovat kuvanneet uuden macOS-haittaohjelman, joka varastaa tunnistetietoja poikkeuksellisen hiljaisella toteutustavalla."
summary_bullets:
  - "PamStealer naamioituu Maccy-leikepöytäsovellukseksi ja leviää väärennetyn verkkosivuston kautta."
  - "Haittaohjelma käyttää AppleScriptiä, JXA-lataajaa ja Rustilla kirjoitettua toista vaihetta."
  - "Se tarkistaa kirjautumissalasanan macOS:n PAM-rajapinnan avulla ennen tietojen varastamista."
key_points:
  - "PamStealer naamioituu Maccy-leikepöytäsovellukseksi ja leviää väärennetyn verkkosivuston kautta."
  - "Haittaohjelma käyttää AppleScriptiä, JXA-lataajaa ja Rustilla kirjoitettua toista vaihetta."
  - "Se tarkistaa kirjautumissalasanan macOS:n PAM-rajapinnan avulla ennen tietojen varastamista."
journalist_note: |
  Artikkeli perustuu packetin neljään lähdeblokkiin. Mukaan otettiin vain niissä kuvattu tekninen toiminta; katkaistun AppleInsider-tekstin loppuosasta ei tehty tarkkoja väitteitä.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1717632464000-15a5e883ab3a?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxtYWNPUyUyMGNsaXBib2FyZCUyMGFwcGxpY2F0aW9uJTIwbWFsd2FyZXxlbnwxfDB8fHwxNzgzMDI4ODg0fDA&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1717632464000-15a5e883ab3a?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwzfHxtYWNPUyUyMGNsaXBib2FyZCUyMGFwcGxpY2F0aW9uJTIwbWFsd2FyZXxlbnwxfDB8fHwxNzgzMDI4ODg0fDA&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: Uusi PamStealer-haittaohjelma naamioituu Macin leikepöytäsovellukseksi (macos, haittaohjelmat)"
image_credit: "Photo by BoliviaInteligente on Unsplash"
image_source_url: "https://unsplash.com/photos/a-computer-monitor-sitting-on-top-of-a-desk-UYqETIVg6ow?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 1
tags:
  - macos
  - haittaohjelmat
  - tietoturva
  - pamstealer
  - maccy
keywords:
  - "macos"
  - "haittaohjelmat"
  - "tietoturva"
  - "pamstealer"
  - "maccy"
source_name: "Ars Technica"
source_url: "https://arstechnica.com/security/2026/07/new-pamstealer-macos-malware-uses-clever-tradecraft-to-remain-stealthy/"
source_domain: "arstechnica.com"
draft: false
---

Tietoturvatutkijat ovat havainneet uuden macOS-haittaohjelmakampanjan, jossa PamStealer-niminen tietoja varastava ohjelma naamioituu Maccy-leikepöytäsovellukseksi. Haittaohjelma käyttää AppleScriptiä ja Rustilla toteutettua toista vaihetta. Sen erikoispiirre on kirjautumissalasanan paikallinen tarkistaminen macOS:n Pluggable Authentication Modules -rajapinnan kautta ennen tietojen lähettämistä hyökkääjän hallitsemalle palvelimelle.

## Naamioitu lataus käynnistää kaksivaiheisen ketjun

Kampanja alkaa tutkijoiden mukaan väärennetyltä verkkosivustolta, joka jäljittelee Maccy-leikepöytäsovelluksen aitoa sivustoa. Sivusto jakaa haitallista AppleScript-sovellusta, joka esiintyy Maccyna. Ensimmäinen vaihe toimitetaan levykuvana, ja kun uhri avaa latauksen, sovellus tarkistaa järjestelmää ja hakee Rustilla kirjoitetun toisen vaiheen hyötykuorman.

Levykuvan ja AppleScriptin käyttö ei sinänsä ole macOS-haittaohjelmissa poikkeuksellista. PamStealerin tapauksessa huomio kiinnittyy siihen, miten nämä osat on yhdistetty hiljaisemmaksi suoritusketjuksi. Kun AppleScript avataan, se näkyy macOS:n Script Editorissa, mutta haitallinen toiminta on lähdeaineiston mukaan piilotettu syvälle tiedostoon.

## JXA-lataaja vähentää näkyviä komentorivijälkiä

Jamf Threat Labsin tutkijoiden mukaan AppleScript ei nojaa tavallisiin komentorivityökaluihin, kuten curliin tai zsh:hon. Sen sijaan se käyttää JavaScript for Automation -lataajaa, joka hakee ja valmistelee hyötykuorman macOS:n natiivien Objective-C-rajapintojen avulla. Tutkijat kuvaavat kokonaisuutta hiljaisemmaksi suoritusketjuksi kuin sellaisissa macOS-tietovarastajissa, joita he tavallisesti näkevät.

## Salasanan tarkistus erottaa PamStealerin monista varastajista

PamStealerin nimi viittaa macOS:n PAM-rajapintaan. Haittaohjelma tarkistaa syötetyn kirjautumissalasanan paikallisesti ennen kuin se lähettää sen hyökkääjän palvelimelle. Tämä erottaa sen monista macOS-tietovarastajista, jotka keräävät uhrin syöttämän salasanan riippumatta siitä, onko se oikea.

Kun toinen vaihe on haettu, PamStealer pyrkii säilymään järjestelmässä ja alkaa kerätä tietoja. Tutkijat havaitsivat myös järjestelmän ominaisuuksiin ja näppäimistöön liittyviä tarkistuksia, mutta käytettävissä oleva lähdeaineisto ei anna koko teknistä kuvaa näistä tarkistuksista. Tapaus osoittaa, että tuttua Mac-sovellusta jäljittelevä lataussivu voi olla osa monivaiheista haittaohjelmaketjua.

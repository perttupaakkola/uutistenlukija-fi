---
title: "TanStack kertoo npm-pakettiensa toimitusketjuhyökkäyksestä"
date: 2026-05-12T03:08:06.085819+00:00
categories:
  - Teknologia
author: "Toimitus"
author_id: "toimitus"
author_title: "Uutistenlukija-toimitus"
author_bio: "Uutistenlukija on suomalainen verkkolehti, joka kirjoittaa alkuperäisiä uutisartikkeleita."
author_image: ""
description: "TanStackin mukaan hyökkääjä julkaisi 11. toukokuuta 2026 haitallisia versioita 42 @tanstack/*-paketista. Yhtiö kehottaa kyseisiä versioita asentaneita k…"
summary: "TanStackin mukaan hyökkääjä julkaisi 11. toukokuuta 2026 haitallisia versioita 42 @tanstack/*-paketista. Yhtiö kehottaa kyseisiä versioita asentaneita kehittäjiä käsittelemään asennusympäristön mahdollisesti vaarantuneena."
summary_bullets:
  - "Hyökkääjä julkaisi 84 haitallista versiota 42 @tanstack/*-paketista 11. toukokuuta 2026."
  - "TanStackin mukaan npm-tokeneita ei varastettu eikä npm-julkaisutyönkulku itsessään vaarantunut."
  - "Haitallisen version asentaneita kehotetaan käsittelemään asennusympäristö mahdollisesti vaarantuneena ja kierrättämään tunnisteet."
key_points:
  - "Hyökkääjä julkaisi 84 haitallista versiota 42 @tanstack/*-paketista 11. toukokuuta 2026."
  - "TanStackin mukaan npm-tokeneita ei varastettu eikä npm-julkaisutyönkulku itsessään vaarantunut."
  - "Haitallisen version asentaneita kehotetaan käsittelemään asennusympäristö mahdollisesti vaarantuneena ja kierrättämään tunnisteet."
journalist_note: |
  Artikkeli perustuu annettuun jälkiarviopakettiin; yksityiskohtia ei laajennettu paketin ulkopuolelta.
content_type: "article"
editorial_reviewed: true
image: "https://images.unsplash.com/photo-1654277041218-84424c78f0ae?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxHaXRIdWIlMjBBY3Rpb25zJTIwc2VjdXJpdHklMjBicmVhY2h8ZW58MXwwfHx8MTc3ODU1NTI4NHww&ixlib=rb-4.1.0&q=80&w=1080"
image_thumb: "https://images.unsplash.com/photo-1654277041218-84424c78f0ae?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w5MDAzMjV8MHwxfHNlYXJjaHwxfHxHaXRIdWIlMjBBY3Rpb25zJTIwc2VjdXJpdHklMjBicmVhY2h8ZW58MXwwfHx8MTc3ODU1NTI4NHww&ixlib=rb-4.1.0&q=80&w=400"
image_alt: "Kuvituskuva uutiseen: TanStack kertoo npm-pakettiensa toimitusketjuhyökkäyksestä (tanstack, npm)"
image_credit: "Photo by Rubaitul Azad on Unsplash"
image_source_url: "https://unsplash.com/photos/a-white-dice-with-a-black-github-logo-on-it-HLQDfaJUTVI?utm_source=uutistenlukija&utm_medium=referral"
reading_time: 2
tags:
  - tanstack
  - npm
  - toimitusketju
  - github actions
  - tietoturva
keywords:
  - "tanstack"
  - "npm"
  - "toimitusketju"
  - "github actions"
  - "tietoturva"
source_name: "Hacker News Best"
source_url: "https://tanstack.com/blog/npm-supply-chain-compromise-postmortem"
source_domain: "hnrss.org"
briefing: true
draft: false
---

TanStack on julkaissut jälkiarvion npm-toimitusketjuhyökkäyksestä, jossa hyökkääjä ehti 11. toukokuuta 2026 julkaista 84 haitallista versiota yhteensä 42 @tanstack/*-paketista. Tapauksen ydin oli usean GitHub Actions -ympäristön heikkouden ketjutus, ei npm-tunnusten varastaminen tai varsinaisen npm-julkaisutyönkulun murto.

## Haitalliset versiot julkaistiin lyhyessä aikaikkunassa

TanStackin mukaan haitalliset versiot julkaistiin 11. toukokuuta kello 19.20–19.26 UTC. Paketteja oli 42, ja kustakin julkaistiin kaksi versiota noin kuuden minuutin välein. Julkinen havainto tehtiin noin 20 minuutissa ulkopuolisen tietoturvatutkijan ashishkurmin toimesta, joka työskenteli StepSecuritylle.

Kaikki tunnistetut haitalliset versiot on merkitty vanhentuneiksi, ja npm:n tietoturvatiimiä on pyydetty poistamaan kyseiset tarball-paketit rekisteristä. TanStackin mukaan sillä ei ole näyttöä siitä, että npm-käyttäjätunnuksia tai -tokeneita olisi varastettu. Myöskään npm-julkaisuprosessin ei kerrota itsessään vaarantuneen. Tapaukseen liittyvät TanStack/router#7383-seurantaketju ja GitHubin tietoturvatiedote GHSA-g7cv-rxg3-hmpx.

TanStack erottelee myös pakettilinjoja, joiden se sanoo olevan varmistetusti puhtaita. Näihin kuuluvat muun muassa @tanstack/query*, @tanstack/table*, @tanstack/form*, @tanstack/virtual*, @tanstack/store sekä @tanstack/start-metapaketti. Sen sijaan @tanstack/start-alkuiset paketit eivät kuulu tähän samaan puhtaaksi vahvistettujen listaan.

## Hyökkäys hyödynsi GitHub Actions -ketjua

Jälkiarvion mukaan hyökkäys perustui kolmeen yhdessä käytettyyn tekijään: pull_request_target-malliin, GitHub Actions -välimuistin myrkyttämiseen fork- ja pääprojektin luottamusrajan yli sekä OIDC-tokenin poimimiseen ajonaikaisesti GitHub Actions -runnerin muistista. TanStack korostaa, että yksikään näistä tekijöistä ei olisi yksin riittänyt hyökkäyksen onnistumiseen.

Käytännössä haitallinen sisältö saattoi käynnistyä, kun kehittäjä tai CI-ympäristö asensi kyseisen version npm-, pnpm- tai yarn-komennolla. Asennuksen yhteydessä haitallinen optionalDependencies-määritys johti orvon hyötykuormacommitin hakemiseen fork-verkosta, prepare-elinkaariskriptin ajamiseen ja noin 2,3 megatavun obfuskoidun router_init.js-tiedoston suorittamiseen.

## Asennusympäristöt on syytä käsitellä vaarantuneina

Tämän vuoksi TanStack suosittelee, että jokainen haitallisen version 11. toukokuuta asentanut käsittelee asennuskoneen mahdollisesti vaarantuneena. Suositeltuihin varotoimiin kuuluu asennusympäristöstä tavoitettavien AWS-, GCP-, Kubernetes-, Vault-, GitHub-, npm- ja SSH-tunnisteiden kierrättäminen.

Jälkiarviossa mainitaan myös bundle-size.yml-työnkulku, joka ajoi pull_request_target-tapahtumaa forkatuista pull requesteista ja tarkisti forkista PR-merge-viitteen ennen build-vaihetta. Työnkulussa oli yritetty erottaa luotettu ja epäluotettu osa toisistaan, mutta TanStackin mukaan haitallinen vite_setup.mjs oli suunniteltu kirjoittamaan tietoja pnpm-store-hakemistoon tavalla, joka ohitti tämän jaon.

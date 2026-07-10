---
title: "Evästekäytäntö"
date: 2026-03-21
lastmod: 2026-07-10
layout: "static"
description: "Uutistenlukija.fi:n evästekäytäntö – mitä evästeitä käytämme ja miten hallita niitä."
---

**Päivitetty:** 10.7.2026

## Evästeet ja selaimen paikallinen tallennustila

Evästeet ovat selaimeen tallennettavia pieniä tiedostoja. Selaimen paikallinen tallennustila (localStorage) säilyttää sivustokohtaisia tietoja ilman evästettä. Uutistenlukija käyttää paikallista tallennustilaa teema- ja evästeasetuksiin sekä joillakin sivuilla paikalliseen lukuhistoriaan, lukemisen edistymiseen ja mainontakiinnostusta koskevien toimintojen anonyymiin paikalliseen laskentaan. Suostumuksellasi Google Analytics voi lisäksi asettaa analytiikkaevästeitä sivuston käytön mittaamista varten.

Mainosverkostoja tai kohdennettua mainontaa ei tällä hetkellä käytetä.

### Paikallisen tallennustilan tiedot

Alla oleva taulukko kuvaa sivuston nykyisiä localStorage-tallennuksia. Niitä ei ryhmitellä tässä välttämättömiksi tallennuksiksi.

| Tallennettava tieto | Tarkoitus | Nykyinen säilytys |
|---|---|---|
| `theme` | Tallentaa valitsemasi tumman tai vaalean teeman. | Ei ohjelmallista määräaikaa; kunnes muutat valintaa tai tyhjennät selaimen sivustotiedot. |
| `cookie_consent_v2` | Tallentaa samaan evästeasetusobjektiin välttämättömiä toimintoja, analytiikkaa ja mainontaa koskevat valinnat. | Ei ohjelmallista määräaikaa; kunnes valinnat korvautuvat uudella tallennuksella tai tyhjennät selaimen sivustotiedot. |
| `ul_views_v1` | Tallentaa selaimeen paikallisen artikkelikohtaisen katseluhistorian: artikkelin tunnisteen ja otsikon sekä katselulaskurin ja aikaleiman. Tietoa käytetään selaimessa paikallisen luetuimmat-listan muodostamiseen. | Yli seitsemän päivää vanhat artikkelimerkinnät poistetaan, kun artikkelisivun tallennuskoodi suoritetaan seuraavan kerran. Käynnin aikaleima päivittyy artikkelia katsottaessa. |
| `ul_progress_v1` | Tallentaa selaimeen artikkelikohtaisen lukemisprosentin, otsikon, osoitteen, kuvan ja aikaleiman Jatka lukemista -toimintoa varten. | Jatka lukemista -toiminto ohittaa yli 30 päivää vanhat merkinnät, mutta nykyinen koodi ei poista niitä automaattisesti localStoragesta. Artikkelikohtainen merkintä poistetaan, kun lukeminen ylittää 90 prosenttia; muutoin tieto säilyy, kunnes se korvautuu tai sivustotiedot tyhjennetään. |
| `uutistenlukija_monetization_signal_v1` | Tallentaa selaimeen mainontakiinnostusta koskevien toimintojen paikalliset laskurit sekä viimeisimmän toiminnon tyypin, ajan, sivupolun ja sijoittelun. | Ei ohjelmallista määräaikaa. Laskurit säilyvät ja viimeisimmän toiminnon tiedot päivittyvät uuden toiminnon yhteydessä, kunnes selaimen sivustotiedot tyhjennetään. |

### Analytiikkaevästeet

**Vaatii suostumuksesi**

Näitä evästeitä käytetään sivuston käytön analysointiin. Tiedot ovat anonymisoituja eivätkä sisällä henkilökohtaisia tunnistetietoja.

| Eväste | Palveluntarjoaja | Tarkoitus | Säilytysaika |
|---|---|---|---|
| `_ga` | Google Analytics | Erottaa sivustovierailijat toisistaan | 2 vuotta |
| `_ga_*` | Google Analytics | Tallentaa istuntotilan | 2 vuotta |

Google Analytics -tietoja käytetään ainoastaan sivuston kehittämiseen. Lisätietoja: [Google Analytics -tietosuoja](https://policies.google.com/privacy)

---

### Mainonta (ei käytössä)

**Mainosverkostoja tai kohdennettua mainontaa ei käytetä tällä hetkellä.**

Sivustolla ei tällä hetkellä ladata Google AdSensea tai muuta mainosverkostoa, näytetä kohdennettua mainontaa eikä aseteta mainosverkostojen evästeitä. Mainontavalinta tallentuu osana evästeasetuksia selaimesi paikalliseen tallennustilaan. Se ei nykytilassa lataa mainoksia, aseta mainosverkostojen evästeitä tai välitä tietoja mainosverkostoille.

Sivuston malleissa on käyttämätön tekninen valmius mainosverkoston lisäämiseen. Mahdollinen käyttöönotto edellyttää erillistä teknistä ja tietosuojatarkastusta. Tämä sivu ja tietosuojaseloste päivitetään ennen käyttöönottoa vastaamaan aktiivisia palveluntarjoajia ja käsittelyä.

---

## Evästeasetuksien hallinta

Voit muuttaa analytiikkaa ja mahdollista tulevaa mainontaa koskevia valintoja sivuston evästeasetuksissa. Voit hallita evästeitä ja poistaa paikallisen tallennustilan tietoja myös selaimen sivustotietoasetuksista.

- **Chrome:** Asetukset → Tietosuoja ja turvallisuus → Evästeet
- **Firefox:** Asetukset → Tietosuoja ja turvallisuus → Evästeet ja sivustotiedot
- **Safari:** Asetukset → Tietosuoja → Hallinnoi verkkosivustotietoja
- **Edge:** Asetukset → Evästeet ja sivustoluvat

Paikallisen tallennustilan tyhjentäminen poistaa selaimesta teema- ja evästeasetukset, paikallisen lukuhistorian, lukemisen edistymisen ja paikalliset toimintolaskurit.

## Lisätiedot

Lisätietoja henkilötietojen käsittelystä löydät [tietosuojaselosteestamme](/tietosuojaseloste/).

Evästekäytäntöön liittyvissä kysymyksissä: info@uutistenlukija.fi

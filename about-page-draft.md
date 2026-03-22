# Uutistenlukija.fi — Tietoa meistä -sivun luonnos

**Viimeksi päivitetty:** 2026-03-22
**Deliverable:** #24

---

## TIETOA MEISTÄ

### Mikä on Uutistenlukija?

Uutistenlukija on suomalainen uutisaggregaatti — palvelu, joka kokoaa yhteen linkkejä suomalaisten ja kansainvälisten uutismedioiden julkaisemiin artikkeleihin.

Meillä ei ole toimittajia kirjoittamassa juttuja. Sen sijaan seuraamme luotettavia uutislähteitä ja kokoamme niiden otsikot helposti selattavaan muotoon kahdeksassa kategoriassa: kotimaa, ulkomaat, talous, politiikka, teknologia ja tiede, urheilu, kulttuuri ja viihde sekä terveys ja hyvinvointi.

Kaikki linkit vievät suoraan alkuperäisen median sivustolle. Uutistenlukija on hakemisto — alkuperäinen sisältö asuu aina alkuperäisen julkaisijan luona.

---

### Miksi Uutistenlukija?

Suomalaisia uutisia on paljon. Hyvät jutut hukkuvat usein klikkiotsikoiden sekaan, ja saman uutisen seuraaminen useasta lähteestä vie aikaa.

Uutistenlukija ratkaisee tämän kokoamalla laadukkaat suomalaiset uutislähteet yhteen paikkaan — ilman mainosraskaita etusivuja tai pakollisia tilauksia. Löydät päivän tärkeimmät uutiset nopeasti ja pääset lukemaan alkuperäisen artikkelin yhdellä klikkauksella.

---

### Miten Uutistenlukija toimii?

Palvelu kerää uutisotsikoita automaattisesti luotettavien medioiden RSS-syötteistä. Jokainen otsikko on linkki alkuperäisen median sivustolle.

**Sisällön valinta:** Noudatamme tarkkaa lähdelistaa — mukaan pääsevät vain todetut, laadukkaat uutismediat. Emme julkaise sisältöä tuntemattomilta tai epäluotettavilta sivustoilta.

**Kategorisointi:** Artikkelit kategorisoidaan automaattisesti lähteen ja aiheen perusteella.

**Päivitystiheys:** Uutisvirta päivittyy jatkuvasti — tuoreimmat otsikot näkyvät sivustolla pian julkaisun jälkeen.

---

## Toimituksellinen linja

### Mitä katamme

- **Kotimaa** — Suomea koskevat uutiset
- **Ulkomaat** — kansainväliset uutiset
- **Talous** — talousuutiset, markkinat, yrityselämä
- **Politiikka** — suomalainen ja kansainvälinen politiikka
- **Teknologia & Tiede** — teknologia, digitalisaatio, tutkimus
- **Urheilu** — kotimainen ja kansainvälinen urheilu
- **Kulttuuri & Viihde** — kulttuuri, musiikki, elokuvat, pelit
- **Terveys & Hyvinvointi** — terveys, lääketiede, hyvinvointi

### Lähteiden valintaperiaatteet

Hyväksymme lähteeksi ainoastaan mediat, jotka:

- Ovat tunnistettu julkaisija toimituksellisella vastuulla
- Noudattavat journalistista hyvää tapaa
- Tuottavat suomenkielistä tai suomalaisille relevanttia sisältöä
- Tarjoavat teknisesti toimivan RSS-syötteen

Emme ota mukaan anonyymejä lähteitä, sisältömarkkinointisivustoja, puolueellisia propagandasivustoja tai muita luotettavuudeltaan kyseenalaisia julkaisijoita.

### Automatisoitu kuratointi — mitä se tarkoittaa

Uutistenlukija on automatisoitu palvelu. Emme lue jokaista artikkelia ennen kuin se ilmestyy sivustolle. Tämä tarkoittaa, että:

- Emme vastaa alkuperäisen median artikkelien sisällöstä tai oikeellisuudesta
- Artikkeli voi ilmestyä sivustollemme myös silloin, kun emme ole sitä erikseen tarkistaneet
- Jos huomaat ongelmallisen sisällön, voit ilmoittaa siitä meille

---

## Vastuullinen aggregointi

Kunnioitamme alkuperäisiä julkaisijoita. Palvelumme perustuu otsikkojen ja lyhyiden kuvausten näyttämiseen sekä linkkeihin alkuperäiselle sivustolle — emme kopioi tai julkaise artikkeleita kokonaisuudessaan. Ohjaamme liikenteen alkuperäisten julkaisijoiden sivuille.

---

## Transparenssi-ilmoitus (DSA)

Uutistenlukija.fi on automaattinen uutisaggregaattipalvelu.

**Palvelun tyyppi:** Uutisaggregaatti — linkityspalvelu, joka kokoaa ulkoisten medioiden otsikoita.

**Sisällön alkuperä:** Kaikki artikkelisisältö on alkuperäisten uutismedioiden tuottamaa. Uutistenlukija ei tuota uutissisältöä itse.

**Algoritmiset suositukset:** Sisältö järjestetään pääasiassa julkaisuajan mukaan (uusimmat ensin). Emme käytä henkilökohtaisiin tietoihin perustuvaa algoritmista suosittelua.

**Mainokset:** Mahdolliset mainokset merkitään selkeästi tunnistettaviksi. Mainoksia ei kohdenneta ilman käyttäjän suostumusta.

**Laittoman sisällön ilmoittaminen:** Jos havaitset sivustollamme laittomaksi epäilemääsi sisältöä, ota yhteyttä osoitteeseen info@uutistenlukija.fi. Käsittelemme ilmoitukset kohtuullisessa ajassa.

---

## Yhteystiedot

**Palvelun ylläpitäjä:**
[REKISTERINPITÄJÄN NIMI]
[PAIKKAKUNTA], Suomi

**Sähköposti:** info@uutistenlukija.fi

Otamme mielellämme palautetta, ehdotuksia uusista lähteistä sekä ilmoituksia ongelmallisesta sisällöstä.

_Vastaamme viesteihin arkisin mahdollisimman pian._

---

## Tietosuoja ja evästeet

- [Tietosuojaseloste](/tietosuojaseloste)
- [Evästekäytäntö](/evastekaytanto)
- [Käyttöehdot](/kayttoehdot)

---

# IMPLEMENTATION NOTES

## Alex:

- [ ] URL: `/tietoa`
- [ ] Full-width layout, no sidebar
- [ ] Add to header nav + footer
- [ ] Meta title: `Tietoa meistä | Uutistenlukija.fi`
- [ ] Meta desc: `Uutistenlukija on suomalainen uutisaggregaatti, joka kokoaa luotettavien medioiden uutisotsikot yhteen paikkaan. Lue, miten palvelu toimii.`
- [ ] JSON-LD `Organization` schema recommended

## Perttu:

- [ ] Täytä `[REKISTERINPITÄJÄN NIMI]`
- [ ] Täytä `[PAIKKAKUNTA]`
- [ ] Lue ja hyväksy ennen julkaisua

---

# WHY THIS FULFILS ALL REQUIREMENTS

| Vaatimus | Lähde | Täyttö |
|---|---|---|
| Toimituksellinen transparenssi | Ampparit | Lähdevalintakriteerit + automatisointi selitetty |
| Julkaisijan identiteetti | Google Publisher Center | Ylläpitäjä, sähköposti, sijainti |
| E-E-A-T | Google News | Nimetty ylläpitäjä, selkeä missio |
| DSA-transparenssi | DSA Art. 14/15 | Palvelun tyyppi, sisällön alkuperä, algoritmi, mainokset, ilmoituskanava |
| GDPR yhteystieto | GDPR Art. 13 | Yhteystiedot + linkit tietosuojasivuille |
| About-sivu P0 | Launch checklist | Kaikki osiot katettu |

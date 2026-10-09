"""Original standalone reader utilities; not news records or publication timestamps."""
import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo

ORIGIN = 'https://uutistenlukija.fi'
CLOCK_SOURCE = 'https://www.finlex.fi/fi/lainsaadanto/2001/753'
TYRES_SOURCE = 'https://traficom.fi/fi/autoilijat/vinkkeja-liikenteeseen/auton-kesa-ja-talvirenkaat'
ALARM_SOURCE = 'https://tukes.fi/tuotteet-ja-palvelut/pelastustoimen-laitteet/palovaroittimet'
GUIDE_PATHS = ('/oppaat/kellojen-siirto-2026/', '/oppaat/talvirenkaat-2026/', '/oppaat/palovaroittimen-tarkistus/')


def guides(now) -> tuple[dict, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware current time required')
    expired = now.astimezone(ZoneInfo('Europe/Helsinki')).date() >= datetime(2026, 10, 26).date()
    clock_answer = ('Suomessa kelloja siirrettiin sunnuntaina 25. lokakuuta 2026 aamulla kello 04.00 takaisin kello 03.00. Tämä sivu käsittelee vuoden 2026 syksyn siirtoa, ei seuraavaa kellonsiirtoa.' if expired else
                    'Suomessa kelloja siirretään sunnuntaina 25. lokakuuta 2026 aamulla kello 04.00 takaisin kello 03.00. Yö pitenee yhdellä tunnilla.')
    return (
        dict(path=GUIDE_PATHS[0], title='Kellojen siirto 2026: 25. lokakuuta kello 04 → 03',
             description='Syksyn 2026 kellonsiirto Suomessa: tarkka päivä ja suunta sekä muistilista laitteille, herätyksille ja yömatkoille.',
             answer=clock_answer, source=CLOCK_SOURCE, source_label='Finlex: kesäaika-asetus 753/2001, 1 ja 3 §',
             sections=(
                 ('Miksi juuri 25. lokakuuta?', '<p>Asetuksen mukaan normaaliaikaan palataan lokakuun viimeisenä sunnuntaina kello neljä, jolloin aikaa siirretään tunti taaksepäin. Vuoden 2026 kalenterissa viimeinen sunnuntai on 25. lokakuuta. Päivä on laskettu tästä säännöstä; kyse ei ole uudesta päätöksestä tai erillisestä tapahtumailmoituksesta.</p>'),
                 ('Muistilista ennen siirtoyötä', '<ol><li>Käy läpi käyttämäsi kellot: puhelin, herätyskello, rannekello, auton kello ja kodin ajastimet. Selvitä kunkin laitteen ohjeesta, vaihtuuko aika automaattisesti.</li><li>Jos laite käyttää automaattista aikaa, tarkista myös aikavyöhyke. Älä tee lisäksi käsin tunnin siirtoa varmistamatta laitteen toimintaa.</li><li>Kirjoita käsin siirrettävien kellojen muistilistaan suunta: neljästä kolmeen, ei neljästä viiteen.</li><li>Tarkista seuraavan aamun tärkeä herätys laitteen näyttämästä ajasta. Pelkkä edellisen illan kellon katsominen ei varmista ajastimen asetuksia.</li></ol>'),
                 ('Yömatka tai sovittu tapaaminen?', '<p>Takaisin siirretty tunti tarkoittaa, että paikallinen kellonaika välillä 03.00–03.59 esiintyy siirtoyönä kahdesti. Jos sovit tapaamisen tähän tuntiin, täsmennä, tarkoitatko ensimmäistä vai jälkimmäistä kertaa. Matkalla tarkista aika lipusta ja liikennöitsijältä: tämä opas ei ratkaise yksittäisen vuoron aikataulua.</p>'),
                 ('Esimerkki: kaksi kelloa ja yksi herätys', '<p>Jos puhelin käyttää automaattista aikaa mutta keittiön kello asetetaan käsin, käsittele ne erillisinä tehtävinä. Selvitä ensin puhelimen asetus ja tee käsin vain keittiön kellon vaatima muutos. Aamulla vertaa näyttöjä ja tarkista herätys. Näin sama tunti ei tule vähennetyksi kahdesti samasta laitteesta. Muistilistan tarkoitus on ehkäistä oma asetusvirhe, ei luvata laitteiden automatiikan toimivuutta.</p>'),
                 ('Mitä tästä ei voi päätellä?', '<p>Suomen siirtohetki ei ole yleispätevä ohje kaikkien maiden kelloille. Myöskään automaattista kellonsiirtoa ei voi luvata jokaiselle laitteelle. Asetus kertoo ajan vaihtumisesta; laitteen valmistajan ohje kertoo, miten juuri sinun kellosi asetetaan.</p>')),
             related=(('/oppaat/#oppaat-junamatka-title', 'Junamatkan aikataulut ja lähtöpaikat'), ('/oppaat/#oppaat-sahkokatko-title', 'Varautuminen sähkökatkoon'))),
        dict(path=GUIDE_PATHS[1], title='Talvirenkaat 2026: milloin ne pitää vaihtaa?',
             description='Talvirengaskausi 1.11.–31.3. on keliperusteinen. Erota 3 mm:n vähimmäisura ja 5 mm:n suositus ja tarkista renkaat ennen vaihtoa.',
             answer='Henkilöautossa, jonka kokonaismassa on enintään 3,5 tonnia, sekä pakettiautossa on käytettävä talvirenkaita 1. marraskuuta–31. maaliskuuta, jos sää tai keli sitä edellyttää. Talvirenkaiden pääurien vähimmäissyvyys on 3 mm; vaikeissa lumi- tai loskaoloissa Traficom suosittelee vähintään 5 mm.',
             source=TYRES_SOURCE, source_label='Traficom: auton kesä- ja talvirenkaat',
             sections=(
                 ('Vaihtopäätös: kolme asiaa samassa järjestyksessä', '<ol><li>Tarkista oman matkasi ajankohta ja reitti. Marraskuun alku ei yksin kerro, onko tiellä talvikeli.</li><li>Katso reitin ajokeli ja säävaroitukset alkuperäisistä palveluista. Arvioi myös paluumatka, älä vain lähtöpaikan tilannetta.</li><li>Tarkista vaihtoon tulevien renkaiden kunto ja merkinnät ennen ajan varaamista. Huonokuntoisen rengassarjan vaihtaminen alle ei ratkaise pito-ongelmaa.</li></ol><p>Ohje on henkilö- ja pakettiautoilijan tarkistuslista, ei keliennuste. Muiden ajoneuvoluokkien ja perävaunujen vaatimukset tarkistat Traficomin sivulta.</p>'),
                 ('3 mm vai 5 mm – mitä ero tarkoittaa?', '<p>Kolme millimetriä on tässä käsiteltyjen talvirenkaiden lakisääteinen pääurien vähimmäissyvyys. Viisi millimetriä on Traficomin suositus vaikeisiin lumi- ja loskaoloihin, ei sama lakiraja. Älä siis tulkitse juuri rajan täyttävää rengasta lupaukseksi riittävästä pidosta kaikissa oloissa.</p>'),
                 ('Rengassarjan tarkistuslista', '<ul><li>Mittaa pääurien syvyys ja kirjaa tulos rengaskohtaisesti. Älä arvioi koko sarjaa vain yhden renkaan perusteella.</li><li>Tarkista nastattoman talvirenkaan lumipitomerkintä: se on ollut henkilö- ja pakettiautoissa pakollinen 1.12.2024 alkaen. Traficomin sivulla on merkinnän kuva; tämä opas ei kopioi sitä.</li><li>Vertaa rengaskokoa auton rekisteritietoihin. Tarkista paineet auton ohjekirjan ja kuormituksen mukaan.</li><li>Jos käytät nastarenkaita, kaikkien renkaiden tulee olla nastoitettuja. Älä kokoa sarjaa sattumanvaraisesti eri tyypeistä.</li></ul>'),
                 ('Kaksi tavallista väärinkäsitystä', '<p>Talvirenkaita ei vaadita automaattisesti jokaisena marraskuun päivänä: sää- tai keliehto kuuluu sääntöön. Nastarenkaiden käyttöaika ei myöskään ole ehdoton kalenteriraja: Traficomin mukaan niitä saa käyttää 1.11.–31.3. ja muulloinkin olosuhteiden vaatiessa. Renkaan valinta ja nopeus on silti sovitettava matkalle, eikä tämä sivu arvioi yksittäisen tien turvallisuutta.</p>')),
             related=(('/oppaat/#oppaat-ajokeli-title', 'Ajokeli ja tiesää reitillä'), ('/oppaat/#oppaat-saavaroitukset-title', 'Säävaroituksen alue ja voimassaolo'), ('/oppaat/#oppaat-heijastin-title', 'Näkyminen pimeässä'))),
        dict(path=GUIDE_PATHS[2], title='Palovaroittimen tarkistus: testinappi ja uusimisajankohta',
             description='Mitä palovaroittimen testinappi kertoo ja mitä ei? Käytännön tarkistuslista paristolle, hälytysäänelle ja valmistajan uusimismerkinnälle.',
             answer='Palovaroittimen testinappi tarkistaa pariston ja hälytysäänen toiminnan, ei kykyä havaita savua. Tarkista siksi myös valmistajan ilmoittama uusimisajankohta, joka löytyy Tukesin mukaan yleensä laitteen pohjasta.',
             source=ALARM_SOURCE, source_label='Tukes: palovaroittimien vaatimukset ja kunnossapito',
             sections=(
                 ('Tarkista kaksi eri asiaa, älä vain piippausta', '<p>Ääni testinapista ja jäljellä oleva käyttöikä vastaavat eri kysymyksiin. Toimiva hälytysääni ei todista savuherkkyyttä eikä kumoa valmistajan uusimismerkintää. Tukes neuvoo uusimaan varoittimen 5–10 vuoden välein, mutta oman laitteen ajankohta tarkistetaan sen merkinnästä. Yleinen vaihtoväli ei korvaa laitekohtaista tietoa.</p>'),
                 ('Käytännön tarkistuslista', '<ol><li>Etsi laitteen käyttöohje. Tarkista, miten sen testinappia käytetään ja millaisia ilmoitusääniä malli antaa.</li><li>Kokeile testinappia ohjeen mukaan. Merkitse muistiin, kuuluiko hälytysääni; älä kirjaa tämän perusteella savuherkkyyttä testatuksi.</li><li>Tarkista valmistajan uusimisajankohta laitteen merkinnästä. Kirjaa päivämäärä tai merkinnän täsmällinen sisältö, jotta siihen voi palata myöhemmin.</li><li>Selvitä virtalähteen tyyppi ohjeesta. Vaihdettava paristo ja laitteen käyttöiän kestävä, ei-vaihdettava virtalähde eivät ole sama asia.</li><li>Jos laite ei toimi tai käyttöikä on päättynyt, ilmoita kunnossapidon tarpeesta rakennuksen omistajalle. Säilytä mallin ja merkinnän tiedot ilmoitusta varten.</li></ol>'),
                 ('Piippaus, paristo vai koko laite?', '<p>Tukesin mukaan vaihdettavan pariston vaihtotarve ilmoitetaan lyhyellä piippauksella. Käyttöiän kestävää virtalähdettä ei voi vaihtaa. Selvitä oman mallisi ilmoitukset käyttöohjeesta sen sijaan, että tulkitsisit kaikki äänet samaksi viaksi. Vikaantunut tai käyttöikänsä päähän tullut varoitin on uusittava.</p>'),
                 ('Mitä ilmoitukseen kannattaa kirjoittaa?', '<p>Tee kunnossapitoilmoituksesta konkreettinen: kerro, mikä varoitin on kyseessä, missä se sijaitsee, mitä testinapista tapahtui ja mitä uusimismerkintä sanoo. Erota oma havainto päätelmästä. Esimerkiksi äänen puuttuminen testissä on havainto; savun havaitsemiskykyä et ole tällä kokeella mitannut. Tietojen kokoaminen auttaa välttämään tilanteen, jossa pelkkä pariston vaihto kuitataan koko laitteen käyttöiän tarkistukseksi.</p>'),
                 ('Vastuu ja tarkistuksen rajat', '<p>Vuoden 2026 alusta hankinta- ja kunnossapitovastuu on rakennuksen omistajalla. Tarkistuslista auttaa havaitsemaan ja ilmoittamaan tarpeen, ei siirrä vastuuta asukkaalle. Tämä ei ole savutestiohje, asennussuunnitelma eikä arvio asunnon kaikkien varoittimien riittävyydestä. Sijoitusvaatimukset ja laitekohtaiset ohjeet tarkistat Tukesin sivulta ja valmistajalta.</p>')),
             related=(('/oppaat/#oppaat-sahkokatko-title', 'Kodin varautuminen sähkökatkoon'), ('/categories/kotimaa/', 'Kotimaan uutiset'))),
    )


def discovery_html(now):
    return ('<nav class="empty-recovery" aria-label="Käytännön oppaat"><h2>Käytännön oppaat</h2><ul>' +
            ''.join(f'<li><a href="{g["path"]}">{html.escape(g["title"])}</a></li>' for g in guides(now)) + '</ul></nav>')


def render_guide(g, page, public, snapshot=None):
    e = html.escape
    body = ('<article class="story single-article"><header><p>Arjen opas</p>'
            f'<h1>{e(g["title"])}</h1><p class="lead">{e(g["answer"])}</p></header>'
            f'<div class="article-reading-grid"><div class="article-reading-main"><div class="content article-body"><p><a href="{e(g["source"])}" rel="noopener noreferrer">{e(g["source_label"])}</a></p>' +
            ''.join(f'<section><h2>{e(title)}</h2>{text}</section>' for title, text in g['sections']) +
            '<nav aria-label="Aiheeseen liittyvät ohjeet"><h2>Jatka lukemista</h2><ul>' +
            ''.join(f'<li><a href="{e(path)}">{e(label)}</a></li>' for path, label in g['related']) +
            '</ul><p><a href="/oppaat/">Kaikki oppaat</a></p></nav></div></div></div></article>')
    structured = {'@context': 'https://schema.org', '@type': 'WebPage', 'name': g['title'],
                  'url': ORIGIN + g['path'], 'description': g['description'], 'inLanguage': 'fi',
                  'isPartOf': {'@type': 'WebSite', 'url': ORIGIN + '/'},
                  'breadcrumb': {'@type': 'BreadcrumbList', 'itemListElement': [
                      {'@type': 'ListItem', 'position': n, 'name': name, 'item': ORIGIN + path}
                      for n, (name, path) in enumerate((('Etusivu', '/'), ('Oppaat', '/oppaat/'), (g['title'], g['path'])), 1)]}}
    meta = f'<meta name="description" content="{e(g["description"])}"><script type="application/ld+json">' + json.dumps(structured, ensure_ascii=False).replace('<', '\\u003c') + '</script>'
    return page(g['title'], body, g['path'] if public else None, head_meta=meta,
                snapshot=snapshot, active_section='/oppaat/', article_page=True)

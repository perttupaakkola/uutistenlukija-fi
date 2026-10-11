"""One dated original holiday comparison, separate from the /oppaat/ cohort."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from .utility_guides import render_guide

PATH = '/syysloma-2026/'
EXPIRES = datetime(2026, 10, 22, 15, 0, tzinfo=ZoneInfo('Europe/Helsinki'))
SOURCES = (
    'https://www.vantaa.fi/fi/ajankohtaista/uutinen/syyslomalla-vantaalla-taiteillaan-temppuillaan-ja-nautitaan-kulttuurista',
    'https://www.hel.fi/fi/uutiset/syysloma-helsingissa-on-taynna-toimintaa',
    'https://www.kuopio.fi/2026/10/07/syyslomalla-tutustutaan-kuopion-kaupunginorkesterin-soittimiin/',
    'https://www.vantaa.fi/fi/ajankohtaista/uutinen/syyslomalla-hakansboleen-valoja-hamaraa-seikkailuja-ja-kekrin-mystiikkaa-museon-pihapiirissa',
    'https://www.ouka.fi/fiilis',
    'https://www.espoo.fi/fi/lomatekemista',
    'https://www.espoo.fi/fi/tapahtumat/espooevents:agqljabk5m',
    'https://www.tampere.fi/ajankohtaista/syyslomalla-tapahtuu-2026',
    'https://www.turku.fi/ajankohtaista/syyslomalla-vietetaan-farikasta-kurpitsakekria',
)
# First six activities checked against primary sources on 9 October 2026.
# Oulu offer independently checked on the city Fiilis page on 10 October 2026.
# Espoo, Tampere and Turku offers checked against city pages on 11 October 2026.
ACTIVITIES = (
    ('Vantaa: taidepaja Artsissa', '13.–15.10.2026 klo 13–15',
     'Taidepajaan vapaa pääsy.', 'Kaikenikäisille; alle kouluikäiset aikuisen seurassa.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (0,)),
    ('Vantaa: Kartanon kekri Håkansbölessä',
     '17.10.2026: myyjäiset klo 11–15, konsertit klo 15.30 ja 17, lyhtyopastus klo 18',
     'Maksuton kekriohjelma ja konsertit. Myyjäisostokset eivät sisälly.',
     'Koko perheelle; aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (0, 3)),
    ('Helsinki: Lasten kaupunki kaupunginmuseossa', '12.–18.10.2026 joka päivä; tarkista päivän aukioloaika järjestäjältä',
     'Sisäänpääsy on maksuton.', 'Lapsiperheille; tarkkaa ikärajaa tai aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (1,)),
    ('Helsinki: Ratikkamuseo Töölössä', '12.–18.10.2026 joka päivä; tarkista päivän aukioloaika järjestäjältä',
     'Sisäänpääsy on maksuton.', 'Lapsiperheille; tarkkaa ikärajaa tai aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (1,)),
    ('Helsinki: Vuotalon sarjakuva- ja mangatyöpajat', '12.–16.10.2026 maanantaista perjantaihin; kellonajat eivät käy ilmi koosteesta',
     'Työpajoihin osallistuminen on maksutonta.', 'Tarkkaa ikäryhmää tai aikuisen mukanaoloehtoa ei ilmoiteta koosteessa.',
     'Ei ennakkoilmoittautumista; osallistujarajasta ei tietoa.', (1,)),
    ('Kuopio: orkesterin soitinesittelyt Musiikkikeskuksessa', '12.10.2026 klo 10–12.40',
     'Soitinesittelyt ovat maksuttomia; lyömäsoittimia voi myös kokeilla.',
     'Kaikille, erityisesti kouluikäisille; aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Ei ennakkoilmoittautumista; enintään 25 henkilöä yhteen esittelyyn.', (2,)),
    ('Oulu: Biitsiareena', '19.–22.10.2026 klo 9–15 (ma–to)',
     'Oulun kaupungin tarjoama sisäänpääsy on maksuton oululaisille lapsiperheille.',
     'Oululaisille lapsiperheille; tarkkaa ikärajaa ei ilmoiteta lähteessä. Osoite: Äimäkuja 6.',
     'Ei ennakkoilmoittautumista; osallistujarajasta ei tietoa tarkistetussa lähteessä.', (4,)),
    ('Espoo: kaupungin uimahallit 7–17-vuotiaille', '12.–16.10.2026 arkipäivisin; tarkista hallin aukiolo',
     'Sisäänpääsy Espoon kaupungin uimahalleihin on maksuton 7–17-vuotiaille.',
     '7–17-vuotiaille. Uimataidottomalla tai alle 10-vuotiaalla pitää olla mukana täysi-ikäinen, uimataitoinen huoltaja.',
     'Ilmoittautumisesta ei tietoa tarkistetussa lähteessä; aikuisen oma maksu ei sisälly.', (6, 5)),
    ('Espoo: asukaspuistojen syyslomaohjelma', '12.–16.10.2026; ohjelma vaihtelee puistoittain',
     'Asukaspuistojen toiminta on avointa ja maksutonta.',
     'Lapsille ja perheille; alle kouluikäiset osallistuvat oman aikuisen kanssa.',
     'Ei ennakkoilmoittautumista. Tarkista oman puiston ohjelma kaupungin sivulta.', (5,)),
    ('Tampere: Tallin Taideperjantai Haiharan kartanolla', '16.10.2026 klo 14–17',
     'Taidetyöpajaan osallistuminen on maksutonta.', 'Kaikille avoin; aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (7,)),
    ('Tampere: lasten ja nuorten elokuvat kirjastoissa',
     '14.10.2026 klo 10–18 Koilliskeskuksen ja Tesoman kirjastoissa; 14.–16.10. klo 13 pääkirjasto Metsossa',
     'Kaikkiin kirjaston tapahtumiin on vapaa pääsy.', 'Elokuvat ovat ikärajaltaan K7.',
     'Ilmoittautumisesta ja osallistujarajasta ei tietoa tarkistetussa lähteessä.', (7,)),
    ('Turku: jättikasvisnäyttely Lastenkulttuurikeskus Färissä', '13.–16.10.2026 (ti–pe) klo 12–18',
     'Näyttelyyn on vapaa pääsy. Färin taidepaja (3,50 €) ja Pikkukekri-esitys (5 €) ovat maksullisia.',
     'Lapsille ja perheille; aikuisen mukanaoloehtoa ei ilmoiteta.',
     'Näyttelyyn ei ilmoiteta ennakkovarausta; maksullisiin pajoihin ja esitykseen varataan paikat ennakkoon.', (8,)),
)
SOURCE_LABELS = ('Vantaan syyslomaohjelma', 'Helsingin syyslomaohjelma',
                 'Kuopion soitinesittelyt, tiedote 7.10.2026', 'Håkansbölen ohjelma ja erilliset museo-opastukset', 'Oulun kaupungin Fiilis: syysloma 2026',
                 'Espoon lomatekemistä', 'Espoon uimahallien maksuton sisäänpääsy', 'Tampereen syyslomaohjelma 2026', 'Turun Färin syysloma')


def archived(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware current time required')
    return now >= EXPIRES


def discovery_html(now):
    label = ('Syysloma 2026: maksuttoman tekemisen arkisto' if archived(now) else
             'Syysloma 2026: vertaile 12 maksutonta tekemistä')
    return f'<nav class="empty-recovery" aria-label="Syysloman vertailu"><h2>Syysloman tekeminen</h2><p><a href="{PATH}">{label}</a> Helsingissä, Espoossa, Vantaalla, Tampereella, Turussa, Kuopiossa ja Oulussa.</p></nav>'


def render(now, page, public, snapshot=None):
    expired = archived(now)
    sections = [
        ('Valitse päivän ja perheen tilanteen mukaan',
         '<p><strong>Päivämäärät ratkaisevat:</strong> vertailussa säilyvät myös jo päättyneet tapahtumat. Valitse oman lomaviikon päivälle sopiva kohde; mennyt tapahtuma ei ole enää varattavissa.</p>'
         '<ul><li><strong>Pienen lapsen kanssa:</strong> Artsissa alle kouluikäinen tarvitsee aikuisen mukaan. Muiden kohteiden puuttuva ehto ei tarkoita lastenhoitopalvelua.</li>'
         '<li><strong>Ilman ennakkovarausta:</strong> Vuotalo, Espoon asukaspuistot ja Kuopion soitinesittelyt eivät vaadi ennakkoilmoittautumista. Kuopiossa paikkaa ei silti taata: raja on 25 henkilöä esittelyä kohti.</li>'
         '<li><strong>Koululaisille ja nuorille:</strong> Espoon kaupungin uimahalleihin pääsee 12.–16.10. arkipäivisin maksutta 7–17-vuotiaana; alle 10-vuotias tarvitsee uimataitoisen aikuisen mukaan.</li><li><strong>Tietylle päivälle:</strong> Kuopio on vain 12.10., Artsi 13.–15.10., Tampereen Haihara 16.10. ja kekri 17.10. Helsingin kahteen museoon voi tutustua 12.–18.10.; tarkista päivän aukiolo ennen lähtöä.</li></ul>'
         '<p>Helsingin, Espoon, Vantaan, Tampereen ja Turun ohjelmat koskevat lomaviikkoa 12.–18.10.2026. Kuopion tapahtumapäivä ei kerro kaikkien koulujen lomapäiviä. Oulun Fiilis-ohjelma koskee koulujen syyslomaa 19.–23.10.2026; Biitsiareenan maksuton sisäänpääsy on tarjolla vain 19.–22.10. klo 9–15 ja vain oululaisille lapsiperheille. Lomaviikot vaihtelevat Suomessa.</p>'),
    ]
    for title, when, cost, age, booking, source_ids in ACTIVITIES:
        details = ''.join(f'<dt><strong>{label}</strong></dt><dd>{html.escape(value)}</dd>'
                          for label, value in (('Päivä ja aika', when), ('Mikä on maksutonta?', cost),
                                               ('Kenelle?', age), ('Varaus ja paikat', booking)))
        links = ' · '.join(f'<a href="{SOURCES[i]}" rel="noopener noreferrer">{SOURCE_LABELS[i]}</a>' for i in source_ids)
        sections.append((title, f'<dl>{details}</dl><p>{links}</p>'))
    sections.extend((
        ('Kuopion aloitusajat', '<p>Vaskien esittelyt alkavat klo 10, 11 ja 12; lyömäsoittimien klo 10.20 ja 11.20; jousien klo 10.40, 11.40 ja 12.20. Sisään kuljetaan Kuopionlahdenkadun pääovista. Valitse esittely ja saavu sen aloitukseen: koko aamupäivän aikaväli ei tarkoita yhtä jatkuvaa työpajaa.</p>'),
        ('Maksuton ohjelma ei kata kaikkia kuluja', '<p>Vertailun maksuttomuus koskee vain mainittua sisäänpääsyä tai ohjelmaa, ei matkoja, ruokaa tai ostoksia. Håkansbölen tavalliset museo-opastukset ovat erillinen maksullinen palvelu: tiedotteessa liput ovat 16/8 euroa ja ennakkovarausta suositellaan. Niitä ei lasketa maksuttomaan kekriohjelmaan.</p><p>Kun varaustieto tai ikäraja puuttuu, sitä ei ole vahvistettu tässä käytetyssä lähteessä. Tarkista järjestäjältä oman käynnin ehdot.</p>'),
        ('Tarkistus ja voimassaolo', '<p>Tiedot tarkistettu 9.10.2026 (Helsinki, Vantaa ja Kuopio). Oulun tiedot tarkistettu 10.10.2026. Espoon, Tampereen ja Turun tiedot tarkistettu 11.10.2026. Vertailu ei näytä vapaita paikkoja reaaliajassa. Tarkista järjestäjän linkistä aukiolo ja mahdolliset muutokset ennen lähtöä. Aktiivinen vertailu päättyy 22.10.2026 klo 15.00 Suomen aikaa; sen jälkeen tämä on päivätty vuoden 2026 arkisto, ei seuraavan syysloman ohjelma.</p>'),
    ))
    title = 'Syysloma 2026: vertaile maksutonta tekemistä'
    answer = ('12 maksutonta vaihtoehtoa Helsingissä, Espoossa, Vantaalla, Tampereella, Turussa, Kuopiossa ja Oulussa: vertaile päivää, ikää ja ilmoittautumista ennen lähtöä. Löydä perheelle uimahalli, taidepaja, museo, elokuva tai liikuntaa ja erota maksuton ohjelma muista kuluista.')
    if expired:
        title = 'Syysloma 2026: maksuttoman tekemisen arkisto'
        answer = 'Vuoden 2026 ohjelma on päättynyt. Tämä päivätty arkisto säilyttää 12 toiminnan vertailun Helsingistä, Espoosta, Vantaalta, Tampereelta, Turusta, Kuopiosta ja Oulusta; se ei ole tulevan loman ohjelma.'
    guide = dict(path=PATH, title=title, answer=answer, description=answer,
                 source=SOURCES[0], source_label=SOURCE_LABELS[0], sections=sections,
                 related=(('/oppaat/talvirenkaat-2026/', 'Autolla syyslomalle: tarkista talvirengassäännöt'),
                          ('/oppaat/#oppaat-ajokeli-title', 'Tarkista ajokeli ja tiesää ennen lähtöä'),
                          ('/oppaat/kellojen-siirto-2026/', 'Loman lopussa kellot siirtyvät 25. lokakuuta')))
    return render_guide(guide, page, public, snapshot)

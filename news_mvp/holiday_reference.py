"""One dated original holiday comparison, separate from the /oppaat/ cohort."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from .utility_guides import render_guide

PATH = '/syysloma-2026/'
EXPIRES = datetime(2026, 10, 18, 23, 59, tzinfo=ZoneInfo('Europe/Helsinki'))
SOURCES = (
    'https://www.vantaa.fi/fi/ajankohtaista/uutinen/syyslomalla-vantaalla-taiteillaan-temppuillaan-ja-nautitaan-kulttuurista',
    'https://www.hel.fi/fi/uutiset/syysloma-helsingissa-on-taynna-toimintaa',
    'https://www.kuopio.fi/2026/10/07/syyslomalla-tutustutaan-kuopion-kaupunginorkesterin-soittimiin/',
    'https://www.vantaa.fi/fi/ajankohtaista/uutinen/syyslomalla-hakansboleen-valoja-hamaraa-seikkailuja-ja-kekrin-mystiikkaa-museon-pihapiirissa',
)
# Facts independently checked against these four primary sources on 9 October 2026.
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
)
SOURCE_LABELS = ('Vantaan syyslomaohjelma', 'Helsingin syyslomaohjelma',
                 'Kuopion soitinesittelyt, tiedote 7.10.2026', 'Håkansbölen ohjelma ja erilliset museo-opastukset')


def archived(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Aware current time required')
    return now >= EXPIRES


def discovery_html(now):
    label = ('Syysloma 2026: maksuttoman tekemisen arkisto' if archived(now) else
             'Syysloma 2026: vertaile kuutta maksutonta tekemistä')
    return f'<nav class="empty-recovery" aria-label="Syysloman vertailu"><h2>Syysloman tekeminen</h2><p><a href="{PATH}">{label}</a> Helsingissä, Vantaalla ja Kuopiossa.</p></nav>'


def render(now, page, public, snapshot=None):
    expired = archived(now)
    sections = [
        ('Valitse päivän ja perheen tilanteen mukaan',
         '<ul><li><strong>Pienen lapsen kanssa:</strong> Artsissa alle kouluikäinen tarvitsee aikuisen mukaan. Muiden kohteiden puuttuva ehto ei tarkoita lastenhoitopalvelua.</li>'
         '<li><strong>Ilman ennakkovarausta:</strong> Vuotalo ja Kuopion soitinesittelyt eivät vaadi ennakkoilmoittautumista. Kuopiossa paikkaa ei silti taata: raja on 25 henkilöä esittelyä kohti.</li>'
         '<li><strong>Tietylle päivälle:</strong> Kuopio on vain 12.10., Artsi 13.–15.10. ja kekri 17.10. Helsingin kahteen museoon voi tutustua 12.–18.10.; tarkista päivän aukiolo ennen lähtöä.</li></ul>'
         '<p>Helsingin ja Vantaan ohjelmakoosteet koskevat lomaviikkoa 12.–18.10.2026. Kuopion tapahtumapäivä ei kerro kaikkien koulujen lomapäiviä. Lomaviikot vaihtelevat Suomessa.</p>'),
    ]
    for title, when, cost, age, booking, source_ids in ACTIVITIES:
        details = ''.join(f'<dt><strong>{label}</strong></dt><dd>{html.escape(value)}</dd>'
                          for label, value in (('Päivä ja aika', when), ('Mikä on maksutonta?', cost),
                                               ('Kenelle?', age), ('Varaus ja paikat', booking)))
        links = ' · '.join(f'<a href="{SOURCES[i]}" rel="noopener noreferrer">{SOURCE_LABELS[i]}</a>' for i in source_ids)
        sections.append((title, f'<dl>{details}</dl><p>{links}</p>'))
    sections.extend((
        ('Kuopion aloitusajat', '<p>Vaskien esittelyt alkavat klo 10, 11 ja 12; lyömäsoittimien klo 10.20 ja 11.20; jousien klo 10.40, 11.40 ja 12.20. Sisään kuljetaan Kuopionlahdenkadun pääovista. Valitse esittely ja saavu sen aloitukseen: koko aamupäivän aikaväli ei tarkoita yhtä jatkuvaa työpajaa.</p>'),
        ('Maksuton ohjelma ei kata kaikkia kuluja', '<p>Vertailun maksuttomuus koskee vain mainittua sisäänpääsyä tai ohjelmaa, ei matkoja, ruokaa tai ostoksia. Håkansbölen tavalliset museo-opastukset ovat erillinen maksullinen palvelu: tiedotteessa liput ovat 16/8 euroa ja ennakkovarausta suositellaan. Niitä ei lasketa maksuttomaan kekriohjelmaan.</p><p>Kun varaustieto tai ikäraja puuttuu, sitä ei ole vahvistettu tässä käytetyssä lähteessä. Puuttuva tieto ei ole lupaus rajattomasta sisäänpääsystä. Tarkista järjestäjältä oman käynnin ehdot.</p>'),
        ('Tarkistus ja voimassaolo', '<p>Tiedot tarkistettu 9.10.2026. Vertailu ei näytä vapaita paikkoja reaaliajassa. Tarkista järjestäjän linkistä aukiolo ja mahdolliset muutokset ennen lähtöä. Aktiivinen vertailu päättyy 18.10.2026 klo 23.59 Suomen aikaa; sen jälkeen tämä on päivätty vuoden 2026 arkisto, ei seuraavan syysloman ohjelma.</p>'),
    ))
    title = 'Syysloma 2026: vertaile maksutonta tekemistä'
    answer = ('Kuusi vaihtoehtoa Helsingissä, Vantaalla ja Kuopiossa: vertaile päivää, ikää ja ilmoittautumista ennen lähtöä. Löydä perheelle taidepaja, museokäynti tai soitinesittely ja erota maksuton ohjelma muista kuluista.')
    if expired:
        title = 'Syysloma 2026: maksuttoman tekemisen arkisto'
        answer = 'Vuoden 2026 ohjelma on päättynyt. Tämä päivätty arkisto säilyttää kuuden toiminnan vertailun Helsingistä, Vantaalta ja Kuopiosta; se ei ole tulevan loman ohjelma.'
    guide = dict(path=PATH, title=title, answer=answer, description=answer,
                 source=SOURCES[0], source_label=SOURCE_LABELS[0], sections=sections,
                 related=(('/oppaat/', 'Syyslomaohjelmat ja muut käytännön oppaat'),))
    return render_guide(guide, page, public, snapshot)

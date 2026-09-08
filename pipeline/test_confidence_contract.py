"""Offline E4 regressions. No writer/config/provider imports or live state.

Run: python -m unittest discover -s pipeline -p test_confidence_contract.py -v
The real score_article caller is used with an empty duplicate fixture. This
suite tests bounded cue rules, not general Finnish proposition understanding.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quality_gate
import source_confidence_guard as guard

ISSUE = 'source_confidence_denial_context_missing'


def supported():
    return {
        'category': 'Ulkomaat',
        'source_text': 'Vance said Iran agreed to admit nuclear inspectors. Iran denied making new commitments.',
        'title': 'BBC: Iran kiistää Vancen väitteen uusista ydinsitoumuksista',
        'summary': 'BBC:n mukaan Iran kiistää Vancen väitteen uusista ydinsitoumuksista.',
        'content': 'BBC:n mukaan Iran kiistää Vancen väitteen uusista ydinsitoumuksista.',
    }


class ConfidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='confidence-contract-')
        self.addCleanup(self.scratch.cleanup)
        for name, value in (
            ('_RECENT_PUBLISHED_CACHE', []),
            ('_CONTENT_POSTS_DIR', self.scratch.name),
            ('REJECTED_DIR', self.scratch.name),
            ('REJECTS_LOG', os.path.join(self.scratch.name, 'rejects.log')),
        ):
            p = patch.object(quality_gate, name, value)
            p.start()
            self.addCleanup(p.stop)

    def score(self, article):
        return quality_gate.score_article(article)

    def test_present_and_past_attribution(self):
        for text in ('kertoo Yle', 'kertoi Yle'):
            with self.subTest(text=text):
                self.assertTrue(guard._contains_any(text, guard.PUBLIC_ATTRIBUTION_MARKERS))

    def test_supported_denial_passes_confidence_caller(self):
        self.assertNotIn(ISSUE, self.score(supported()).hard_fails)

    def test_each_surface_requires_denial(self):
        for key in ('title', 'summary', 'content'):
            a = supported()
            a[key] = 'BBC:n mukaan Iran suostui uusiin ydinsitoumuksiin.'
            with self.subTest(surface=key):
                result = self.score(a)
                self.assertIn(ISSUE, result.hard_fails)
                self.assertFalse(result.passes)

    def test_each_surface_requires_attribution(self):
        for key in ('title', 'summary', 'content'):
            a = supported()
            a[key] = 'Iran kiistää uudet sitoumukset.'
            with self.subTest(surface=key):
                self.assertIn(ISSUE, self.score(a).hard_fails)

    def test_missing_headline_rejects(self):
        a = supported()
        del a['title']
        self.assertIn(ISSUE, self.score(a).hard_fails)

    def test_negated_denial_rejects_on_each_surface(self):
        for key in ('title', 'summary', 'content'):
            for phrase in ('ei kiistä', 'ei ole kiistänyt', 'ei enää kiistä', 'eivät kiistä', 'ei voi kiistää'):
                a = supported()
                a[key] = 'BBC:n mukaan Iran ' + phrase + ' uusia sitoumuksia.'
                with self.subTest(surface=key, phrase=phrase):
                    self.assertIn(ISSUE, self.score(a).hard_fails)

    def test_helper_polarity(self):
        for text in ('Iran kiistää väitteen.', 'Syytetyt kiistävät syytteet.',
                     'Hän kiisti väitteen.', 'Hän ei kommentoi, mutta kiistää syytteet.'):
            with self.subTest(text=text):
                self.assertTrue(guard._contains_denial(text))
        for text in ('Iran ei kiistä väitettä.', 'Syytetyt eivät kiistä syytteitä.',
                     'Hän ei ole kiistänyt väitettä.', 'En kiistä väitettä.',
                     'Asia on kiistaton.', 'Syyttäjä ei ole tehnyt syyteratkaisuja.'):
            with self.subTest(text=text):
                self.assertFalse(guard._contains_denial(text))

    def test_negated_source_denial_does_not_activate(self):
        a = supported()
        a['source_text'] = 'Ylen mukaan Iran ei kiistä väitettä.'
        a['title'] = 'Iranin lausunto julkaistiin'
        self.assertNotIn(ISSUE, self.score(a).hard_fails)

    def test_pending_charging_decision_is_not_denial(self):
        a = {'category': 'Kotimaa', 'title': 'Fitburgin tutkinta jatkuu',
             'summary': 'Osa ratkaisuista tehdään myöhemmin.', 'content': 'Tutkinta on kesken.'}
        for phrase in ('ei ole tehnyt', 'ei ole vielä tehnyt'):
            a['source_text'] = 'Venäjän kansalaisia oli miehistössä. Syyttäjän mukaan hän ' + phrase + ' syyteratkaisuja.'
            with self.subTest(phrase=phrase):
                self.assertNotIn(ISSUE, self.score(a).hard_fails)
                a['source_text'] += ' Syytetyt kiistävät syytteet.'
                self.assertIn(ISSUE, self.score(a).hard_fails)

    def test_commitment_negation_remains_denial(self):
        for phrase in ('ei ole tehnyt uusia sitoumuksia', 'ei ole antanut uusia lupauksia', 'ei ole tehnyt rikosta'):
            a = supported()
            a['source_text'] = 'Ylen mukaan Iran ' + phrase + '.'
            a['title'] = 'Iran teki uusia sitoumuksia'
            with self.subTest(phrase=phrase):
                self.assertIn(ISSUE, self.score(a).hard_fails)
                for key in ('title', 'summary', 'content'):
                    a[key] = 'Ylen mukaan Iran ' + phrase + '.'
                self.assertNotIn(ISSUE, self.score(a).hard_fails)

    def test_no_category_exemption(self):
        for category in ('Kotimaa', 'Talous', 'Ulkomaat'):
            a = supported()
            a['category'] = category
            a['title'] = 'Iran teki uusia sitoumuksia'
            with self.subTest(category=category):
                self.assertIn(ISSUE, self.score(a).hard_fails)

    def test_election_uncertainty_still_required(self):
        a = {'category': 'Ulkomaat', 'title': 'Vaalit päättyivät',
             'summary': 'Vaalien voittaja julistettiin.', 'content': 'Tulos on selvä.',
             'source_text': 'The election results are preliminary and not legally binding.'}
        issue = 'source_confidence_election_uncertainty_missing'
        self.assertIn(issue, self.score(a).hard_fails)
        a['summary'] = 'Vaalien tulos on alustava.'
        self.assertNotIn(issue, self.score(a).hard_fails)

    def test_non_sensitive_boundary_unchanged(self):
        for title in ('Kokous pidetään syyskuun alussa', 'Viranomainen tiedotti asiasta'):
            self.assertFalse(guard.is_high_stakes_geopolitics({'category': 'Kotimaa', 'title': title}))

    def test_supported_headline_yle_exact_public_fixture(self):
        # Public article fields only, preserved failed packet 20260908T032655Z_cd3faec841.
        # Fixture is embedded below so tests never read a live queue or home path.
        a = copy.deepcopy(YLE_ARTICLE)
        result = self.score(a)
        self.assertIn(ISSUE, result.hard_fails)
        self.assertFalse(result.passes)
        a['title'] = 'Ylen mukaan Fitburgin kapteeni ja pursimies kiistävät syytteet'
        for verb in ('kertoo', 'kertoi'):
            b = copy.deepcopy(a)
            b['content'] = b['content'].replace('kertoo Yle.', verb + ' Yle.', 1)
            result = self.score(b)
            with self.subTest(verb=verb):
                self.assertNotIn(ISSUE, result.hard_fails)
                self.assertTrue(result.passes, result)


YLE_ARTICLE = json.loads('{"title": "Fitburgin kapteeni ja pursimies vastaavat syytteisiin Suomenlahden kaapelirikoista", "description": "Helsingin käräjäoikeudessa luetaan tiistaina Fitburgin kapteenin ja pursimiehen syytteet törkeästä tuhotyöstä ja törkeästä tietoliikenteen häirinnästä. Molemmat kiistävät syytteet.", "summary": "Helsingin käräjäoikeudessa luetaan tiistaina Fitburgin kapteenin ja pursimiehen syytteet törkeästä tuhotyöstä ja törkeästä tietoliikenteen häirinnästä. Molemmat kiistävät syytteet.", "content": "Fitburg-rahtialuksen kapteenille ja pursimiehelle luetaan tiistaina Helsingin käräjäoikeudessa syytteet, jotka koskevat viime uudenvuodenaaton kaapelirikkoja Suomenlahdella. Syyttäjä vaatii heille rangaistusta törkeästä tuhotyöstä ja törkeästä tietoliikenteen häirinnästä. Molemmat syytetyt kiistävät syytteet, kertoo Yle.\\n\\nAluksen epäillään vaurioittaneen kahta tietoliikennekaapelia Helsingin ja Tallinnan välillä Viron talousvyöhykkeellä. Ylen mukaan osa vaurioista tapahtui myös Suomen aluevesillä. Pursimies toimii aluksen kansihenkilökunnan esimiehenä.\\n\\n## Esitutkinnan mukaan ankkuri raahautui ainakin 130 kilometriä\\n\\nEsitutkinnan mukaan Fitburg raahasi rikkoutunutta ankkuria merenpohjassa Suomenlahdella ainakin 130 kilometrin matkan. Ankkurin raahaaminen jatkui siihen asti, kunnes suomalaiset viranomaiset pysäyttivät aluksen.\\n\\nKaapelivaurioiden lisäksi syytteet koskevat kahdeksan muun merenalaisen yhteyden vahingoittamisen yritystä. Syyttäjän mukaan alus aiheutti vakavaa vaaraa Suomessa tietoliikenneverkkojen sekä sähkö- ja kaasuverkkojen toiminnalle. Kyse on syyttäjän arviosta aluksen aiheuttamasta vaarasta.\\n\\nKeskusrikospoliisin tutkinta valmistui kesäkuun alussa. Esitutkinnassa epäiltyinä oli kaikkiaan neljä merimiestä, mutta nyt syytteet on nostettu kahta vastaan. Kahden muun, aluksen päällystöön kuuluneen epäillyn osalta syyteharkintaratkaisut tehdään myöhemmin. Heidän osaltaan syytteiden nostamisesta ei siis ole vielä ratkaisua.\\n\\n## Toimivaltakysymys nousi esiin myös Eagle S:n tapauksessa\\n\\nYlen mukaan Fitburgin oikeudenkäynnissä käsitellään myös sitä, onko Helsingin käräjäoikeudella toimivalta tutkia syytteet. Vastaava kysymys on ollut esillä toisessa Suomenlahden kaapelirikkoja koskevassa oikeusjutussa, jossa epäilyt liittyivät Eagle S -alukseen.\\n\\nVenäjältä öljytuotelastissa lähteneen Eagle S:n epäiltiin katkaisseen viisi merikaapelia joulunpyhinä vuonna 2024. Epäilyn mukaan alus raahasi ankkuriaan merenpohjassa noin 90 kilometrin matkan. Tätä tapausta käsiteltiin Helsingin käräjäoikeudessa vuosi sitten.\\n\\nKäräjäoikeus katsoi viime lokakuussa, ettei se voinut tutkia Eagle S -tapauksen syytteitä, koska kaapelirikot eivät tapahtuneet Suomen alueella. Hovioikeus puolestaan katsoi Suomella olevan asiassa toimivalta ja palautti jutun elokuussa käräjäoikeuteen. Ratkaisu koski Eagle S:n tapausta; Fitburgin osalta toimivaltaa käsitellään sen omassa oikeudenkäynnissä.", "category": "Kotimaa", "tags": ["fitburg", "kaapelirikot", "suomenlahti", "helsingin käräjäoikeus"], "summary_bullets": ["Fitburgin kapteeni ja pursimies kiistävät kaapelirikkoihin liittyvät syytteet.", "Esitutkinnan mukaan alus raahasi rikkoutunutta ankkuria ainakin 130 kilometriä.", "Kahden muun epäillyn syyteharkintaratkaisut tehdään myöhemmin."], "key_points": ["Fitburgin kapteeni ja pursimies kiistävät kaapelirikkoihin liittyvät syytteet.", "Esitutkinnan mukaan alus raahasi rikkoutunutta ankkuria ainakin 130 kilometriä.", "Kahden muun epäillyn syyteharkintaratkaisut tehdään myöhemmin."], "source_text": "Syyttäjä vaatii rangaistusta venäläiselle kapteenille ja azerbaidžanilaiselle pursimiehelle viime uudenvuodenaaton Suomenlahden kaapelirikoista. Syytetyt kiistävät rikokset. Helsingin käräjäoikeudessa luetaan tänään tiistaina poikkeukselliset syytteet kahdelle merimiehelle viime uudenvuodenaaton Suomenlahden kaapelirikoista. Syytteessä ovat Fitburg-rahtialuksen venäläinen kapteeni ja azerbaidžanilainen pursimies, joka on laivan kansihenkilökunnan esimies. Heitä syytetään törkeästä tuhotyöstä ja törkeästä tietoliikenteeen häirinnästä. Molemmat kiistävät syytteet. Fitburg-rahtialuksen epäillään vaurioittaneen kahta tietoliikennekaapelia Viron talousvyöhykkeellä Helsingin ja Tallinnan välillä. Esitutkinnan mukaan Fitburg raahasi Suomenlahdella rikkoontunutta ankkuria meren pohjassa ainakin 130 kilometriä, kunnes suomalaiset viranomaiset pysäyttivät aluksen. Osa vaurioista tapahtui myös Suomen aluevesillä. Merimiehiä syytetään lisäksi kahdeksan muun merenalaisen yhteyden vahingoittamisen yrityksestä. Syyttäjän mukaan alus aiheutti vakavaa vaaraa Suomessa tietoliikenne-, sähkö ja kaasuverkkojen toiminnalle. Aluksen miehistöön kuuluu yhteensä 14 jäsentä. Koko miehistö koostuu Venäjän, Georgian ja Kazakstanin kansalaisista. Fitburgin lippuvaltio on Saint Vincent ja Grenadiinit -niminen saarivaltio Karibianmerellä. Keskusrikospoliisi (KRP) tutkinta valmistui kesäkuun alussa.\\n\\nSyyttäjä vaatii rangaistusta venäläiselle kapteenille ja azerbaidžanilaiselle pursimiehelle viime uudenvuodenaaton Suomenlahden kaapelirikoista. Syytetyt kiistävät rikokset.\\n\\nTutkinnassa oli yhteensä neljä merimiestä epäiltynä. Syytteet on nyt nostettu kuitenkin vain kahta merimiestä vastaan. Aluksen päällystöön kuuluneiden kahden muun rikoksesta epäillyn henkilön osalta tehdään syyteharkintaratkaisut myöhemmin. Oikeudenkäynnistä mielenkiintoisen tekee se, että vastaavanlaista tapausta istuttiin niin ikään Helsingin käräjäoikeudessa vuosi sitten. Venäjältä öljytuotelastissa lähteneen Eagle S:n epäiltiin katkaisseen Suomenlahdella viisi merikaapelia raahaamalla ankkuriaan meren pohjassa noin 90 kilometrin matkan joulun pyhinä vuonna 2024. Käräjäoikeus teki viime lokakuussa yllätyspäätöksen ja ilmoitti, ettei se voi tutkia syyttäjän esittämiä syytteitä. Käräjäoikeus katsoi, ettei se voinut käsitellä syytteitä, koska kaapelirikot eivät tapahtuneet Suomen alueella. Hovioikeus palautti elokuussa jutun käräjäoikeuteen. Hovioikeus katsoi, että Suomella on toimivalta asiassa. Myös Fitburg-tapauksessa tullaan käymään keskustelua siitä, onko Helsingin käräjäoikeudella toimivaltaa käsitellä syyttäjän syytteitä. Puolustus tulee esittämään, ettei käräjäoike"}')

if __name__ == '__main__':
    unittest.main()

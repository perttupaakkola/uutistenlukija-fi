"""Offline captured-scene regression and adversarial safety examples."""
import unittest
from news_mvp.imagery import _depicts_people, classify_draft


FOREST_DRAFT = {
    "title": "Metsänhoidon tuen hakuaika pitenee rajoitustilanteissa",
    "summary": (
        "Maa- ja metsätalousministeriön mukaan viranomaisen toimintakiellon "
        "viivästyttämään taimikon ja nuoren metsän hoitoon voi hakea tukea yhdeksän "
        "kuukauden kuluessa rajoitusten päättymisestä. Muutos tulee voimaan 7. "
        "lokakuuta, eikä se muuta tavanomaisia hakuaikoja."
    ),
    "category": "Talous",
    "paragraphs": [
        {"source_ids": ["A"], "text": (
            "Maa- ja metsätalousministeriön mukaan pidennetty hakuaika koskee "
            "tilanteita, joissa viranomaisen määräämä alueellinen toimintakielto "
            "estää taimikon tai nuoren metsän hoitotyön valmistumisen määräajassa. "
            "Tällainen kielto voi liittyä esimerkiksi afrikkalaisen sikaruton torjuntaan."
        )},
        {"source_ids": ["A"], "text": (
            "Ministeriön tiedotteen mukaan asetusmuutos tulee voimaan 7. lokakuuta "
            "2026. Uusia määräaikoja sovelletaan hakemuksiin, jotka saapuvat Suomen "
            "metsäkeskukseen asetuksen voimaantulon jälkeen."
        )},
        {"source_ids": ["A"], "text": (
            "Tavanomaisissa tilanteissa määräajat pysyvät ministeriön mukaan "
            "ennallaan: tukea on haettava viimeistään kuuden kuukauden kuluessa "
            "töiden aloittamisesta ja kahden kuukauden kuluessa niiden valmistumisesta."
        )},
        {"source_ids": ["A"], "text": (
            "Ministeriö kertoo, että poikkeustilanteiden hakuaika pidennettiin "
            "yhdeksään kuukauteen syyskuussa järjestetyn lausuntokierroksen palautteen "
            "perusteella. Muutoksen tavoitteena on turvata tuen hakumahdollisuus myös "
            "metsänomistajille, joiden työt viivästyvät viranomaispäätöksen vuoksi."
        )},
    ],
}

FOREST_CLASSIFIER = {
    "version": "article-first-v1",
    "category": "Talous",
    "concepts": [
        {
            "rank": 1,
            "safe_to_generate": True,
            "subject": "taimikon ja nuoren metsän hoito",
            "depictable_scene": (
                "Nuori havumetsikkö, jossa kasvamaan jätettyjen puiden välissä näkyy "
                "matalia katkaistuja vesakon kantoja ja maahan jääneitä ohuita "
                "raivausrunkoja. Kuvassa ei ole ihmisiä."
            ),
            "must_show": [
                "Young conifer trees", "Cut sapling stumps between standing trees",
            ],
            "must_avoid": [
                "People or body parts", "Mature forest clear-cutting",
                "Signs implying an actual official restriction",
            ],
            "search_queries": [
                "taimikon hoito raivaus", "nuoren metsän hoito",
                "young forest thinning", "conifer sapling clearing",
            ],
        },
        {
            "rank": 2,
            "safe_to_generate": True,
            "subject": "taimikon hoitotyön raivaussaha",
            "depictable_scene": (
                "Raivaussaha lepää sammaleisella maalla tiheän nuoren taimikon "
                "reunassa. Sahan varsi ja metallinen raivausterä näkyvät selvästi, "
                "eikä kuvassa ole käyttäjää tai luettavia tuotemerkintöjä."
            ),
            "must_show": ["Brush cutter with metal blade", "Dense young saplings"],
            "must_avoid": [
                "People or body parts", "Readable branding or invented text",
                "Heavy logging machinery",
            ],
            "search_queries": [
                "raivaussaha taimikonhoito", "raivaussaha metsässä",
                "forestry brush cutter", "brush cutter saplings",
            ],
        },
    ],
}

CAR_DRAFT = {
    "title": "Täyssähköautojen ensirekisteröinnit kasvoivat syyskuussa",
    "summary": (
        "Tilastokeskuksen mukaan täyssähköautojen ensirekisteröinnit lisääntyivät "
        "syyskuussa 2026 vuotta aiemmasta 67 prosenttia. Niiden osuus uusista "
        "henkilöautoista oli 62 prosenttia, kun bensiini- ja dieselautojen "
        "rekisteröinnit vähenivät."
    ),
    "category": "Talous",
    "paragraphs": [
        {"source_ids": ["A"], "text": (
            "Syyskuussa ensirekisteröitiin Tilastokeskuksen mukaan 4 338 "
            "täyssähköistä henkilöautoa. Kun mukaan lasketaan ladattavat hybridit, "
            "ladattavia autoja rekisteröitiin 5 103 eli lähes kolme neljäsosaa "
            "kaikista uusista henkilöautoista. Ladattavien autojen määrä kasvoi 38 "
            "prosenttia vuoden takaisesta."
        )},
        {"source_ids": ["A"], "text": (
            "Uusia henkilöautoja ensirekisteröitiin kaikkiaan 6 984, mikä oli "
            "Tilastokeskuksen mukaan 16 prosenttia enemmän kuin syyskuussa 2025. "
            "Bensiiniautojen rekisteröinnit vähenivät 17 prosenttia ja dieselautojen "
            "30 prosenttia. Bensiiniautoja rekisteröitiin 1 737 ja dieselautoja 144."
        )},
        {"source_ids": ["A"], "text": (
            "Tilastokeskuksen tilastossa yritysten ja yhteisöjen käyttöön "
            "rekisteröitiin 3 007 henkilöautoa eli 43 prosenttia syyskuun "
            "henkilöautojen ensirekisteröinneistä. Täyssähköautoista 52 prosenttia "
            "rekisteröitiin Uudellemaalle."
        )},
        {"source_ids": ["A"], "text": (
            "Tammi–syyskuussa 2026 uusien henkilöautojen ensirekisteröintejä kertyi "
            "Tilastokeskuksen mukaan 56 932, kuusi prosenttia enemmän kuin vuotta "
            "aiemmin. Kaikkien ajoneuvojen ensirekisteröinnit kasvoivat samalla "
            "ajanjaksolla kolme prosenttia ja olivat yhteensä 97 669."
        )},
    ],
}

CAR_CLASSIFIER = {
    "version": "article-first-v1",
    "category": "Talous",
    "concepts": [
        {
            "rank": 1,
            "safe_to_generate": True,
            "subject": "Uusia henkilöautoja: täyssähköautoja autoliikkeen pihalla",
            "depictable_scene": (
                "Nimeämättömän autoliikkeen pihalla on rivi uusia, puhtaita "
                "henkilöautoja. Etualan auton avoimeen latausporttiin on kytketty "
                "latausjohto. Kuvassa ei ole ihmisiä eikä tunnistettavia automerkkejä."
            ),
            "must_show": [
                "New passenger cars in a dealership lot",
                "Visible charging connection on the foreground car",
            ],
            "must_avoid": [
                "People or body parts", "Invented logos or readable text",
                "Identifiable real dealership recreated synthetically",
            ],
            "search_queries": [
                "uudet sähköautot autoliike", "täyssähköautot myyntipiha",
                "new electric cars dealership", "electric cars dealership charging",
            ],
        },
        {
            "rank": 2,
            "safe_to_generate": True,
            "subject": "Ladattavia autoja: henkilöauton latausliitäntä",
            "depictable_scene": (
                "Lähikuva pysäköidyn henkilöauton kyljestä ja avoimesta "
                "latausportista, johon latauspistoke on kytketty. Johto jatkuu kuvan "
                "ulkopuolelle; kuvassa ei ole ihmisiä, käsiä eikä merkkitunnuksia."
            ),
            "must_show": ["Charging plug connected to a passenger car"],
            "must_avoid": [
                "People or body parts", "Invented logos or readable text",
                "Fuel nozzle instead of charging plug",
            ],
            "search_queries": [
                "henkilöauton latausliitäntä", "sähköauton latauspistoke lähikuva",
                "electric car charging port", "connected EV charging plug",
            ],
        },
    ],
}


class CapturedClassifier:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, role, packet, draft):
        self.calls.append((role, packet, draft))
        return self.response

class GrowthImageBlocker(unittest.TestCase):
    def test_exact_rejected_outputs_pass_the_installed_classifier_caller(self):
        cases = (
            (FOREST_DRAFT, FOREST_CLASSIFIER,
             "https://valtioneuvosto.fi/-/1410837/taimikon-ja-nuoren-metsan-"
             "hoidon-tuen-hakuaikoihin-muutos-asf-rajoitusten-alueella"),
            (CAR_DRAFT, CAR_CLASSIFIER,
             "https://stat.fi/fi/julkaisu/cmfl6i4lip5sp07ulyfh8f2ny"),
        )
        for draft, response, source_url in cases:
            with self.subTest(title=draft["title"]):
                model = CapturedClassifier(response)
                packet = {"sources": [{"id": "A", "url": source_url}]}
                self.assertEqual(classify_draft(draft, model=model, packet=packet), response)
                self.assertEqual(model.calls, [("image_classifier", packet, draft)])

    def test_exact_captured_safe_scene(self):
        scene = "Nimeämätön suuri öljytankkeri kiinnitettynä öljysataman laituriin. Aluksen pitkä kansi putkistoineen ja laiturin lastausvarret näkyvät sivuviistosta veden yli kuvattuina, eikä kuvassa ole ihmisiä."
        self.assertFalse(_depicts_people(scene))
    def test_cargo_is_not_children(self):
        for s in ("Lastausvarret öljysatamassa", "Lastauksen putkisto", "Lastausalue vedestä kuvattuna"):
            with self.subTest(s=s):self.assertFalse(_depicts_people(s))
    def test_negative_existence(self):
        for s in ("Öljysäiliöt, eikä kuvassa ole ihmisiä.", "Säiliöt. Ei kuvassa näy henkilöitä.", "Laituri ilman ihmisiä.", "Oil tanks without people."):
            with self.subTest(s=s):self.assertFalse(_depicts_people(s))
    def test_people_and_body_parts_still_refused(self):
        for s in ("Lapsia laiturilla", "Lasten ryhmä", "Aikuinen satamassa", "Henkilö säiliön vieressä", "Käsi venttiilillä", "People beside an oil tanker", "Faces near loading arms"):
            with self.subTest(s=s):self.assertTrue(_depicts_people(s))
    def test_captured_location_before_negation(self):
        self.assertFalse(_depicts_people("Nimeämätön öljytankkeri kiinnitettynä öljysataman laituriin. Aluksen kannella näkyy putkistoa ja laiturilla lastausvarsi; kuvassa ei ole ihmisiä eikä tunnistettavaa todellista satamaa."))
        self.assertFalse(_depicts_people("Säiliöt; ei ole ihmisiä."))
        self.assertTrue(_depicts_people("Kuvassa ei ole vain ihmisiä vaan myös putkia."))
    def test_positive_clause_not_hidden_by_negation(self):
        for s in ("Ei kuvassa ole vain ihmisiä, vaan myös säiliöitä", "Ei kuvassa ole ihmisiä mutta käsi näkyy", "Laituri ilman ihmisiä ja lapset taustalla", "Eikä kuvassa ole ihmisiä, mutta henkilö näkyy laiturilla"):
            with self.subTest(s=s):self.assertTrue(_depicts_people(s))

    def test_nearby_nonhuman_words_and_negated_body_part_list(self):
        for scene in (
            "Nuori havumetsikkö ilman ihmisiä.",
            "Raivaussaha lepää nuoren taimikon reunassa.",
            "Rivi uusia henkilöautoja ilman ihmisiä.",
            "Lähikuva henkilöauton latausportista; kuvassa ei ole ihmisiä, käsiä.",
        ):
            with self.subTest(scene=scene):
                self.assertFalse(_depicts_people(scene))

    def test_nearby_positive_people_and_body_parts_remain_blocked(self):
        for scene in (
            "Nuorukainen havumetsikön reunassa.",
            "Nuorisoryhmä taimikon vieressä.",
            "Henkilöautonkuljettaja katsoo kameraan.",
            "Nuori seisoo taimikon reunassa.",
            "Nuori henkilö seisoo havumetsikössä.",
            "Nuori taimikonhoitaja seisoo metsässä.",
            "Nuoria ihmisiä henkilöautojen vieressä.",
            "Henkilö auton vieressä.",
            "Henkilöauto ja käsi ovenkahvalla.",
            "Kuvassa ei ole ihmisiä, mutta käsi on latauspistokkeella.",
            "Kuvassa ei ole ihmisiä, käsi on latauspistokkeella.",
        ):
            with self.subTest(scene=scene):
                self.assertTrue(_depicts_people(scene))

if __name__ == '__main__':unittest.main()

"""
Writer Profiles — fictional journalist personas for bylines.
"""

import random
from typing import Dict

WRITERS = [
    {
        "id": "matti-virtanen",
        "name": "Matti Virtanen",
        "title": "Päätoimittaja",
        "bio": "Kokenut uutistoimittaja ja päätoimittaja. Erikoistunut kotimaan politiikkaan ja yhteiskunta-asioihin. Työskennellyt aiemmin Helsingin Sanomissa ja Yle Uutisissa.",
        "specialties": ["Kotimaa", "Ulkomaat"],
        "image": "/images/writers/matti-virtanen.jpg",
    },
    {
        "id": "anna-korhonen",
        "name": "Anna Korhonen",
        "title": "Taloustoimittaja",
        "bio": "Talouden ja markkinoiden asiantuntija. Kirjoittanut laajasti Suomen ja EU:n talouspolitiikasta sekä teknologiainvestoinneista.",
        "specialties": ["Talous", "Teknologia"],
        "image": "/images/writers/anna-korhonen.jpg",
    },
    {
        "id": "jukka-nieminen",
        "name": "Jukka Nieminen",
        "title": "Urheilutoimittaja",
        "bio": "Intohimoinen urheilutoimittaja, joka seuraa erityisesti jääkiekkoa, jalkapalloa ja formula ykkösiä. Aiemmin ESPN Nordicilla.",
        "specialties": ["Urheilu"],
        "image": "/images/writers/jukka-nieminen.jpg",
    },
    {
        "id": "laura-makela",
        "name": "Laura Mäkelä",
        "title": "Tiedetoimittaja",
        "bio": "Tiedetoimittaja ja tietokirjailija. Erikoistunut ilmastotutkimukseen, avaruuteen ja terveysteknologiaan.",
        "specialties": ["Tiede", "Teknologia"],
        "image": "/images/writers/laura-makela.jpg",
    },
    {
        "id": "mikko-salonen",
        "name": "Mikko Salonen",
        "title": "Kulttuuritoimittaja",
        "bio": "Kulttuurin ja viihteen monitoimittaja. Seuraa musiikkia, elokuvia, kirjallisuutta ja taidemaailmaa.",
        "specialties": ["Kulttuuri"],
        "image": "/images/writers/mikko-salonen.jpg",
    },
    {
        "id": "sanna-heikkinen",
        "name": "Sanna Heikkinen",
        "title": "Ulkomaantoimittaja",
        "bio": "Ulkomaantoimittaja, jolla on laaja kokemus Euroopan ja Lähi-idän raportoinnista. Aiemmin kirjeenvaihtajana Brysselissä.",
        "specialties": ["Ulkomaat", "Kotimaa"],
        "image": "/images/writers/sanna-heikkinen.jpg",
    },
]


def assign_writer(category: str) -> Dict:
    """Pick a writer matching the article's category, with randomization.

    Writers whose specialties include the category are preferred (weighted 3x),
    but any writer can be picked to avoid deterministic patterns.
    """
    weights = []
    for writer in WRITERS:
        if category in writer["specialties"]:
            weights.append(3)
        else:
            weights.append(1)

    chosen = random.choices(WRITERS, weights=weights, k=1)[0]
    return chosen

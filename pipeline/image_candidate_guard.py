"""Image Flow v2 guardrails for article hero images.

Keep this provider-neutral. Unsplash, Pexels, generated fallback, and publish
gates all use the same intent and scoring vocabulary so a weak stock candidate
does not become a published frontmatter value by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any
from urllib.parse import unquote, urlsplit


ACCEPT_THRESHOLD = 55
VISUAL_JUDGE_ACCEPT_THRESHOLD = 45
MISMATCH_SCORE = 0
PROMPT_VERSION = "image-flow-v3-grounded-2026-09-02"

WINTER_TERMS = {
    "snow", "snowy", "snowfall", "snowstorm", "winter", "ice", "icy",
    "frozen", "frost", "frosty", "blizzard", "sleet",
    "lumi", "luminen", "talvi", "jaassa", "jäässä", "jäinen", "jäätä",
    "jäälle", "jäällä", "jääpeite", "pakkanen",
}

RAIN_TERMS = {
    "rain", "rainy", "rainfall", "shower", "showers", "downpour",
    "wet", "storm", "stormy", "thunder", "thunderstorm",
    "sade", "sateinen", "sadekuuro", "ukkonen", "myrsky",
}

SUN_TERMS = {
    "sun", "sunny", "sunshine", "clear sky", "bright", "summer",
    "aurinko", "aurinkoa", "aurinkoinen", "aurinkoisena", "pouta", "poutainen",
    "poutaisena", "kesä",
}

HEAT_TERMS = {
    "heat", "hot", "heatwave", "helte", "helteinen", "kuuma",
}

COLD_TERMS = {
    "cold", "cool", "chilly", "viileä", "viilenee", "kylmä",
}

WEATHER_TERMS = WINTER_TERMS | RAIN_TERMS | SUN_TERMS | HEAT_TERMS | COLD_TERMS | {
    "weather", "forecast", "cloud", "cloudy", "sää", "ennuste", "pilvi",
}

PERSON_IMAGE_TERMS = {
    "portrait", "headshot", "person", "people", "man", "woman", "boy", "girl",
    "businessman", "businesswoman", "politician", "leader", "face", "actor",
    "athlete", "customer", "employee", "crowd", "speaker", "podium", "henkilö",
    "ihminen",
}

SENSITIVE_TERMS = {
    "rikos", "murha", "kuolema", "kuoli", "surma", "ampuminen", "oikeus",
    "sota", "isku", "hyökkäys", "uhri", "rauniot", "onnettomuus", "terror",
    "crime", "murder", "death", "shooting", "court", "war", "attack",
    "victim", "disaster", "accident",
}

SENSITIVE_PREFIXES = (
    "ampum", "hyökkä", "isku", "konflikt", "kuol", "murh", "ohju",
    "diabe", "loukkaantu", "pahoinpit", "rikos", "räjäh", "sair", "sot",
    "surm", "syöp", "syöv", "tauti", "terror", "tervey", "tulipal", "uhr",
    "väkivalt", "accident", "attack", "cancer", "conflict", "crime", "death",
    "disease", "health", "missile", "murder", "shoot", "terror", "victim", "war",
)

# Finnish compounds keep the incident noun inside one token (for example
# ``junaonnettomuus``), so prefix matching alone cannot recognize them.
SENSITIVE_COMPOUND_STEMS = (
    "kavall", "onnettomu", "pahoinpit", "petos", "puukot", "raisk", "rikos",
    "ryöst", "siepp",
)

PERSON_ROLE_TERMS = {
    "presidentti", "pääministeri", "ministeri", "kansanedustaja", "senaattori",
    "kuvernööri", "pormestari", "puheenjohtaja", "johtaja", "toimitusjohtaja",
    "professori", "tutkija", "lääkäri", "valmentaja", "näyttelijä", "laulaja",
    "kirjailija", "yrittäjä", "president", "prime", "minister", "senator",
    "governor", "mayor", "chairperson", "director", "professor", "coach",
    "actor", "singer", "author",
}

# A single capitalized surname is person-like only when the headline gives it
# person/action context. This covers Finnish headline forms such as "Trump
# vaatii" and "Trumpin kerrotaan" without treating every capitalized subject as
# a person.
PERSON_HEADLINE_ACTION_TERMS = {
    "aikoo", "arvioi", "asetti", "ehdottaa", "erotti", "haluaa", "hyväksyi",
    "hylkäsi", "ilmoittaa", "ilmoitti", "kertoi", "kerrotaan", "kiistää",
    "kommentoi", "lupaa", "määräsi", "mukaan", "nimitti", "sanoi", "sanoo",
    "tapasi", "uhkaa", "vaati", "vaatii", "varoittaa", "vetoaa", "voitti",
    "says", "said", "tells", "told", "demands", "warns", "threatens",
    "announced", "appointed", "approved", "rejected",
}

NON_PERSON_CAPITALIZED_TERMS = {
    "hallitus", "eduskunta", "poliisi", "puolue", "ministeriö", "komissio",
    "neuvosto", "oikeus", "kunta", "kaupunki", "yhtiö", "yritys", "järjestö",
    "suomi", "ruotsi", "norja", "tanska", "saksa", "ranska", "venäjä", "kiina",
    "iran", "israel", "ukraina", "eurooppa", "euroopan", "yhdysvallat",
    "helsinki", "tampere", "turku", "oulu", "jyväskylä", "paris", "pariisi",
    "france", "nato", "eu", "yk", "kela", "google", "apple", "microsoft",
    "government", "parliament", "police", "court", "company", "city", "country",
}

# Tokens that may occur in article prose and candidate URL boilerplate but do
# not describe a visual subject. One such token must never carry a candidate
# across the acceptance threshold.
NON_VISUAL_TOKENS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "with",
    "ja", "joka", "jonka", "jos", "kun", "kuin", "myös", "mutta", "niin",
    "on", "oli", "ovat", "se", "sekä", "sen", "sillä", "tai", "että",
    "uutinen", "uutiset", "kuva", "photo", "photos", "image", "images",
    "unsplash", "pexels", "com", "www", "http", "https", "utm", "source",
    "medium", "referral", "crop", "entropy", "fit", "max", "jpg", "webp",
}

KNOWN_LOCATION_TERMS = {
    "finland", "suomi", "suomen", "suomessa",
    "helsinki", "helsingissä", "kouvola", "nurmes", "joensuu", "imatra",
    "karjala", "karjalan", "iran", "iranin", "jordania", "jordaniaan",
    "larak", "larakin", "hormuz", "hormuzinsalmi", "yhdysvallat",
    "yhdysvaltain", "germany", "saksa", "saksan", "russia", "venäjä",
    "venäjän", "europe", "eurooppa", "euroopan",
}

# Location matching is deliberately explicit. Capitalization alone is not safe
# evidence of a place in Finnish headlines, where organizations and people are
# capitalized in the same way. Canonical aliases let Finnish inflections and
# English stock metadata agree without weakening the mismatch gate.
LOCATION_ALIASES = {
    "finland": {
        "finland", "suomi", "suomen", "suomessa", "suomesta", "suomeen",
    },
    "helsinki": {
        "helsinki", "helsingin", "helsingissä", "helsingistä", "helsinkiin",
    },
    "tampere": {
        "tampere", "tampereen", "tampereella", "tampereelta", "tampereelle",
    },
    "turku": {"turku", "turun", "turussa", "turusta", "turkuun"},
    "oulu": {"oulu", "oulun", "oulussa", "oulusta", "ouluun"},
    "jyväskylä": {
        "jyväskylä", "jyväskylän", "jyväskylässä", "jyväskylästä", "jyväskylään",
    },
    "paris": {
        "paris", "parisin", "pariisi", "pariisin", "pariisissa",
        "pariisista", "pariisiin",
    },
    "france": {
        "france", "ranska", "ranskan", "ranskassa", "ranskasta", "ranskaan",
    },
    "spain": {
        "spain", "espanja", "espanjan", "espanjassa", "espanjasta",
        "espanjaan",
    },
    "italy": {
        "italy", "italia", "italiassa", "italiasta", "italiaan",
    },
    "rome": {"rome", "rooma", "rooman", "roomassa", "roomasta", "roomaan"},
    "england": {
        "england", "englanti", "englannin", "englannissa", "englannista",
    },
    "london": {
        "london", "lontoo", "lontoon", "lontoossa", "lontoosta", "lontooseen",
    },
    "united_kingdom": {
        "united kingdom", "britain", "uk", "britannia",
    },
    "united_states": {
        "united states", "usa", "yhdysvallat", "yhdysvaltain",
    },
    "new_york": {"new york", "new york city", "nyc"},
}

LOCATION_PARENTS = {
    "helsinki": "finland",
    "tampere": "finland",
    "turku": "finland",
    "oulu": "finland",
    "jyväskylä": "finland",
    "paris": "france",
    "rome": "italy",
    "london": "england",
    "england": "united_kingdom",
    "new_york": "united_states",
}

# Demonyms can support article-side geography, but they are not candidate-side
# proof of capture location (for example, "Japanese style" or "French doors").
ARTICLE_LOCATION_DEMONYMS = {
    "finland": {"finnish", "suomalainen", "suomalaisen"},
    "paris": {"parisian"},
    "france": {"french", "ranskalainen", "ranskalaisen"},
    "spain": {"spanish", "espanjalainen", "espanjalaisen"},
    "italy": {"italian", "italialainen", "italialaisen"},
    "rome": {"roman"},
    "england": {"english"},
    "london": {"londoner"},
    "united_kingdom": {"british"},
    "united_states": {"american"},
    "japan": {"japanese"},
    "slovakia": {"slovak", "slovakian"},
}

KNOWN_LOCATION_TERMS |= set().union(*LOCATION_ALIASES.values())

WINTER_NEGATION_TERMS = {"ei", "eivät", "ettei", "eikä", "ilman", "no", "not", "without"}
WINTER_NEGATION_BEFORE_STEMS = ("aihe", "kosk", "kuulu", "käsittel", "liity", "ole", "relev")
WINTER_IRRELEVANCE_STEMS = ("aihe", "kosk", "kuulu", "käsittel", "liity", "maini", "relev")
WINTER_META_MENTION_STEMS = ("esimerk", "maini", "metafor", "nimi", "sana", "vertail")
WINTER_VISUAL_CONTEXT_TERMS = {
    "ennuste", "forecast", "frost", "ice", "jää", "keli", "lumi", "pakkanen",
    "sade", "snow", "snowfall", "sää", "temperature", "weather",
}
LUMI_PERSON_ACTION_TERMS = {
    "aikoo", "asuu", "etsii", "haluaa", "ihastuu", "kertoi", "kertoo", "kommentoi",
    "näyttelee", "opiskelee", "osallistui", "osallistuu", "sanoi", "sanoo", "syntyi",
    "tapaa", "työskentelee", "voitti",
}

CATEGORY_SETTINGS = {
    "Kotimaa": "Finnish public life or neutral Finnish landscape",
    "Ulkomaat": "international context without implying a specific event scene",
    "Talous": "business, finance, offices, documents, charts, or economy",
    "Teknologia": "technology, devices, software, data, or abstract digital work",
    "Urheilu": "sports venue, equipment, training, or competition atmosphere",
    "Kulttuuri": "arts, media, stage, books, music, or cinema",
    "Tiede": "research, laboratory, nature, space, or scientific instruments",
}

BOAT_REPAIR_TERMS = {
    "vene", "veneet", "veneen", "veneiden", "veneenkorjaus", "veneenkorjaustaidot",
    "soutuvene", "soutuveneen", "moottorivene", "moottoriveneen", "pulpettivene",
    "hyttivene", "taifunx", "boat", "boats", "rowboat", "motorboat", "boat repair",
}

REPAIR_WORK_TERMS = {
    "korjaus", "korjaa", "korjattavaksi", "korjattavia", "korjattujen", "korjaamaansa",
    "kunnostaa", "kunnostamisesta", "kunnostettu", "kunnostettuja", "romukuntoisia",
    "repair", "repairs", "repairing", "restoration", "restoring",
}

YOUTH_ENTREPRENEUR_TERMS = {
    "4h-yrittäjyys", "4h", "kesätyö", "kesätöitä", "nuoret", "nuorukainen",
    "16-vuotias", "yrittäjä", "yrittäjyys", "youth", "teen", "entrepreneur",
}

URBAN_BUSINESS_IMAGE_TERMS = {
    "skyscraper", "skyscrapers", "high-rise", "highrise", "city", "cityscape",
    "skyline", "downtown", "office", "offices", "business district", "building",
    "buildings", "architecture", "urban", "corporate", "tower", "towers",
}

# Article-derived bilingual concepts. These are deliberately keyed only from
# editorial fields, never from the generated provider query. They let Finnish
# stories retrieve and verify English stock metadata without reviving the
# query-as-truth defect fixed by OPE-585.
ARTICLE_VISUAL_CONCEPT_RULES: tuple[
    tuple[set[str], str, tuple[str, ...]], ...
] = (
    (
        {
            "kuljetusyrittäjä", "kuljetusyrittäjälle", "kuljetusyritys",
            "kuljetusliike", "kuorma-auto", "kuorma-autoa", "rekka",
            "logistiikka", "freight", "truck", "logistics",
        },
        "freight truck or logistics",
        (
            "freight truck logistics",
            "commercial truck on road",
            "transport and logistics",
        ),
    ),
    (
        {
            "puuseppä", "puuseppäyrittäjä", "puusepän", "kaluste",
            "kalusteet", "kalusteita", "keittiö", "keittiön",
            "keittiökaluste", "keittiökalusteita", "verstas", "carpentry",
            "woodworking", "furniture",
        },
        "carpentry, woodworking, kitchen cabinets, or furniture workshop",
        (
            "carpentry workshop",
            "woodworking kitchen cabinets",
            "furniture workshop tools",
        ),
    ),
    (
        {
            "korkeakoulu", "korkeakoulujen", "yhteishaku", "opiskelupaikka",
            "opiskelupaikkaa", "opiskelijat", "university", "college",
            "admissions", "students",
        },
        "university, study, or student admissions",
        ("university campus", "students studying", "university admissions"),
    ),
    (
        {
            "hotelli", "hotellit", "hotellimajoitus", "majoitus", "spahotel",
            "hotel", "hospitality", "accommodation",
        },
        "hotel or hospitality",
        ("hotel exterior", "hotel room hospitality", "hotel reception"),
    ),
    (
        {
            "sikarutto", "villisika", "villisikoja", "swine", "boar",
        },
        "wild boar or animal disease monitoring",
        ("wild boar in forest", "wildlife monitoring", "forest field research"),
    ),
    (
        {
            "budjetti", "vaalibudjetti", "talousarvio", "julkistalous",
            "budget", "fiscal",
        },
        "budget documents or public finance",
        ("budget documents", "public finance papers", "financial planning desk"),
    ),
    (
        {
            "dekkari", "kirja", "romaani", "tv-sarja", "televisiosarja",
            "hollywood", "book", "novel",
        },
        "book, television, or screen production",
        ("book and television production", "film studio equipment", "open book cinema"),
    ),
    (
        {
            "ralli", "mm-ralli", "rallissa", "ralliauto", "motorsport",
        },
        "rally car or motorsport",
        ("rally car on gravel road", "motorsport service area", "rally racing"),
    ),
    (
        {
            "kaasupallo", "kuumailmapallo", "balloon",
        },
        "competitive gas balloon flight",
        ("gas balloon in sky", "balloon aviation competition", "balloon landing field"),
    ),
    (
        {
            "sisäpiirirekisteri", "sisäpiirirekisterin",
            "sisäpiirirekisterivelvoite", "sisäpiirirekisterivelvoitteen",
            "rahastoyhtiö", "rahastoyhtiöt", "rahastoyhtiöiden", "rahastoyhtiöiltä",
            "finanssisääntely", "compliance", "regulation",
        },
        "financial regulation, investment funds, or compliance documents",
        (
            "financial regulation documents",
            "investment fund compliance paperwork",
            "finance administration documents",
        ),
    ),
    (
        {
            "rautatie", "rautatien", "rautatiehanke", "raide", "raideleveys",
            "radan", "rataverkko", "rataverkon", "rail", "railway",
        },
        "railway tracks, rail infrastructure, or railway construction",
        (
            "railway tracks infrastructure",
            "rail construction work",
            "passenger and freight railway",
        ),
    ),
    (
        {
            "turvealue", "turvealueiden", "turvemaa", "turvemaita",
            "turpeennostoalue", "turpeennostoalueiden", "metsitys",
            "metsitykseen", "vettäminen", "vettämistä", "kosteikko",
            "kosteikoiksi", "peatland", "wetland",
        },
        "peatland, wetland restoration, or forestry land",
        (
            "peatland wetland landscape",
            "wetland restoration",
            "forestry on former peatland",
        ),
    ),
    (
        {"kysely", "mielipidekysely", "gallup", "poll", "survey", "ballot"},
        "public opinion survey or ballot",
        ("public opinion survey ballot", "survey questionnaire", "ballot box"),
    ),
)

CONCEPT_RULE_PRIORITY = {
    "financial regulation, investment funds, or compliance documents": 100,
    "railway tracks, rail infrastructure, or railway construction": 100,
    "peatland, wetland restoration, or forestry land": 100,
    "carpentry, woodworking, kitchen cabinets, or furniture workshop": 90,
    "freight truck or logistics": 90,
    "university, study, or student admissions": 90,
    "wild boar or animal disease monitoring": 90,
    "book, television, or screen production": 90,
    "rally car or motorsport": 90,
    "competitive gas balloon flight": 90,
    "hotel or hospitality": 80,
    "public opinion survey or ballot": 80,
    "budget documents or public finance": 40,
}

CONCEPT_SPECIFIC_ANCHORS = {
    "railway tracks, rail infrastructure, or railway construction": {
        "railway", "railways", "railroad", "railroads", "rail", "rails",
        "train", "trains", "rautatie", "rautatien", "rautatiehanke", "raide",
        "raiteet", "radan", "rataverkko", "rataverkon",
    },
}


@dataclass(frozen=True)
class ImageIntent:
    subject: str
    setting: str
    season_time: str
    must_have: list[str]
    must_not: list[str]
    stock_ok: bool
    generated_ok: bool
    safety_mode: str
    named_person: bool
    sensitive_story: bool
    locations: list[str]
    evidence_terms: list[str]
    style_preference: str
    location_pairs: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualBrief:
    acceptable_concepts: list[str]
    hard_forbidden_implications: list[str]
    intent: ImageIntent
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["intent"] = self.intent.to_dict()
        return data


@dataclass(frozen=True)
class CandidateDecision:
    provider: str
    candidate_id: str
    source_url: str
    score: int
    accepted: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualJudgeDecision:
    score: int
    accepted: bool
    reasons: list[str]
    hard_fail: bool = False
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stock_policy_reason(intent: ImageIntent) -> str:
    if intent.named_person and intent.sensitive_story:
        return (
            "named-person sensitive story is stock-ineligible and requires a safe "
            "generated illustration or category fallback"
        )
    if intent.named_person:
        return (
            "named-person story is stock-ineligible; use a safe generated illustration "
            "or category fallback, never generic person/lookalike stock"
        )
    if intent.sensitive_story:
        return "sensitive story requires a safe non-stock fallback"
    return "article truth is stock-ineligible"


def _tokens(*parts: str) -> set[str]:
    text = " ".join(part or "" for part in parts).lower()
    normalized_text = text.replace("-", " ")
    words = set(re.findall(r"[\wäöå+-]+", text, flags=re.IGNORECASE))
    words |= set(re.findall(r"[\wäöå+]+", normalized_text, flags=re.IGNORECASE))
    location_phrases = {
        alias
        for aliases in LOCATION_ALIASES.values()
        for alias in aliases
        if " " in alias
    }
    phrases = {
        phrase
        for phrase in {
            "clear sky", "boat repair", "business district", *location_phrases,
        }
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_text)
    }
    return words | phrases


def _meaningful_tokens(*parts: str) -> set[str]:
    return {
        token
        for token in _tokens(*parts)
        if token not in NON_VISUAL_TOKENS
        and not token.isdigit()
        and (len(token) >= 3 or token in {"ai", "tv", "eu"})
    }


def _locations_from_tokens(
    tokens: set[str],
    *,
    include_article_demonyms: bool = False,
) -> set[str]:
    locations = set(tokens & KNOWN_LOCATION_TERMS)
    for canonical, aliases in LOCATION_ALIASES.items():
        if tokens & aliases:
            locations.difference_update(aliases)
            locations.add(canonical)
    if include_article_demonyms:
        for canonical, demonyms in ARTICLE_LOCATION_DEMONYMS.items():
            if tokens & demonyms:
                locations.add(canonical)
    pending = list(locations)
    while pending:
        parent = LOCATION_PARENTS.get(pending.pop())
        if parent and parent not in locations:
            locations.add(parent)
            pending.append(parent)
    return locations


def _ordered_meaningful_tokens(text: str) -> list[str]:
    ordered: list[str] = []
    for token in re.findall(r"[\wäöå+-]+", (text or "").lower(), flags=re.IGNORECASE):
        if token in _meaningful_tokens(token) and token not in ordered:
            ordered.append(token)
    return ordered


def _url_semantic_text(value: str) -> str:
    """Return only a provider page's descriptive path, never query metadata."""
    try:
        path = unquote(urlsplit(value).path)
    except ValueError:
        return ""
    return path.replace("-", " ").replace("_", " ").replace("/", " ")


def _candidate_text(candidate: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("alt", "alt_description", "description"):
        value = candidate.get(key)
        if value:
            values.append(str(value))
    for key in ("photo_page", "pexels_url", "source_url"):
        value = candidate.get(key)
        if value:
            values.append(_url_semantic_text(str(value)))
    return " ".join(values)


_NON_GEOGRAPHIC_PROPER_PHRASE_TOKENS = {
    "background", "black", "blue", "bright", "building", "cloud", "clouds",
    "construction", "dark", "day", "field", "forest", "foreground", "green",
    "interior", "landscape", "modern", "night", "office", "opinion", "public",
    "red", "road", "sky", "snow", "style", "sunset", "survey", "track",
    "tracks", "train", "water", "white", "winter",
}

# Provider captions and descriptive page slugs are predominantly English. Keep
# country recognition bounded to an explicit list: this lets lowercase metadata
# carry geographic meaning without guessing that arbitrary nouns are places.
_ENGLISH_COUNTRY_NAMES = frozenset(
    name.strip()
    for name in """
afghanistan
albania
algeria
andorra
angola
antigua and barbuda
argentina
armenia
australia
austria
azerbaijan
bahamas
bahrain
bangladesh
barbados
belarus
belgium
belize
benin
bhutan
bolivia
bosnia and herzegovina
botswana
brazil
brunei
bulgaria
burkina faso
burundi
cabo verde
cambodia
cameroon
canada
central african republic
chad
chile
china
colombia
comoros
costa rica
croatia
cuba
cyprus
czechia
democratic republic of the congo
denmark
djibouti
dominica
dominican republic
ecuador
egypt
el salvador
equatorial guinea
eritrea
estonia
eswatini
ethiopia
fiji
finland
france
gabon
gambia
georgia
germany
ghana
greece
grenada
guatemala
guinea
guinea bissau
guyana
haiti
honduras
hungary
iceland
india
indonesia
iran
iraq
ireland
israel
italy
ivory coast
jamaica
japan
jordan
kazakhstan
kenya
kiribati
kosovo
kuwait
kyrgyzstan
laos
latvia
lebanon
lesotho
liberia
libya
liechtenstein
lithuania
luxembourg
madagascar
malawi
malaysia
maldives
mali
malta
marshall islands
mauritania
mauritius
mexico
micronesia
moldova
monaco
mongolia
montenegro
morocco
mozambique
myanmar
namibia
nauru
nepal
netherlands
new zealand
nicaragua
niger
nigeria
north korea
north macedonia
norway
oman
pakistan
palau
palestine
panama
papua new guinea
paraguay
peru
philippines
poland
portugal
qatar
republic of the congo
romania
russia
rwanda
saint kitts and nevis
saint lucia
saint vincent and the grenadines
samoa
san marino
sao tome and principe
saudi arabia
senegal
serbia
seychelles
sierra leone
singapore
slovakia
slovenia
solomon islands
somalia
south africa
south korea
south sudan
spain
sri lanka
sudan
suriname
sweden
switzerland
syria
taiwan
tajikistan
tanzania
thailand
timor leste
togo
tonga
trinidad and tobago
tunisia
turkey
turkmenistan
tuvalu
uganda
ukraine
united arab emirates
united kingdom
united states
uruguay
uzbekistan
vanuatu
vatican city
venezuela
vietnam
yemen
zambia
zimbabwe
""".splitlines()
    if name.strip()
)

_ENGLISH_COUNTRY_ALIAS_TO_CANONICAL = {
    country: country for country in _ENGLISH_COUNTRY_NAMES
}
_ENGLISH_COUNTRY_ALIAS_TO_CANONICAL.update(
    {
        "bosnia": "bosnia and herzegovina",
        "britain": "united kingdom",
        "burma": "myanmar",
        "cape verde": "cabo verde",
        "congo brazzaville": "republic of the congo",
        "congo kinshasa": "democratic republic of the congo",
        "cote d ivoire": "ivory coast",
        "côte d ivoire": "ivory coast",
        "czech republic": "czechia",
        "dr congo": "democratic republic of the congo",
        "drc": "democratic republic of the congo",
        "east timor": "timor leste",
        "federated states of micronesia": "micronesia",
        "great britain": "united kingdom",
        "holy see": "vatican city",
        "holland": "netherlands",
        "lao pdr": "laos",
        "macedonia": "north macedonia",
        "republic of korea": "south korea",
        "russian federation": "russia",
        "slovak republic": "slovakia",
        "swaziland": "eswatini",
        "the bahamas": "bahamas",
        "the gambia": "gambia",
        "turkiye": "turkey",
        "türkiye": "turkey",
        "uae": "united arab emirates",
        "uk": "united kingdom",
        "united states of america": "united states",
        "usa": "united states",
        "vatican": "vatican city",
        "viet nam": "vietnam",
    }
)

_ENGLISH_COUNTRY_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        re.escape(alias)
        for alias in sorted(
            _ENGLISH_COUNTRY_ALIAS_TO_CANONICAL,
            key=lambda alias: (len(alias), alias),
            reverse=True,
        )
    )
    + r")(?!\w)",
    flags=re.IGNORECASE,
)
_STRUCTURED_COUNTRY_PERSON_PATTERN = re.compile(
    r"(?<!\w)(?:at|from|in|near)\s+"
    r"(?:[A-ZÅÄÖ][A-Za-zÅÄÖåäö'-]{2,}\s+){0,2}(?:"
    + "|".join(
        re.escape(alias).replace(r"\ ", r"\s+")
        for alias in sorted(
            _ENGLISH_COUNTRY_ALIAS_TO_CANONICAL,
            key=lambda alias: (len(alias), alias),
            reverse=True,
        )
    )
    + r")(?!\w)",
    flags=re.IGNORECASE,
)

_LOCATION_CONTEXT_PREPOSITIONS = {"at", "from", "in", "near"}
_AMBIGUOUS_COUNTRY_NOUNS = {
    "chad", "china", "dominica", "georgia", "guinea", "india", "jordan",
    "mali", "oman", "turkey",
}
_GENERIC_LOCATION_MODIFIERS = {
    "beautiful", "busy", "central", "coastal", "cold", "downtown", "east",
    "eastern", "forested", "greater", "industrial", "local", "lower", "modern",
    "mountainous", "national", "new", "north", "northern", "remote", "rural", "scenic",
    "snowy", "south", "southern", "suburban", "sunny", "tropical", "upper",
    "urban", "west", "western",
}
_NON_CITY_BEFORE_COUNTRY = (
    _NON_GEOGRAPHIC_PROPER_PHRASE_TOKENS
    | NON_VISUAL_TOKENS
    | _GENERIC_LOCATION_MODIFIERS
    | {
        "advertisement", "air", "airport", "architecture", "area", "bridge",
        "capital", "city", "coast",
        "country", "countryside", "district", "harbor", "harbour", "highway",
        "historic", "historical", "infrastructure", "lake", "metro", "modern",
        "mountain", "mountains", "national", "nature", "rail", "railroad",
        "railway", "region", "river", "scene", "scenery", "station", "street",
        "mural", "roast", "roasted", "travel", "valley", "view", "village",
        "weather",
    }
)


def _normalized_location_text(value: str) -> str:
    """Case-fold prose or decoded slugs into letter-only location words."""
    return " ".join(re.findall(r"[^\W\d_]+", (value or "").casefold()))


def _country_mentions(value: str) -> list[tuple[str, int, int, str]]:
    normalized = _normalized_location_text(value)
    return [
        (
            _ENGLISH_COUNTRY_ALIAS_TO_CANONICAL[match.group(0)],
            match.start(),
            match.end(),
            normalized,
        )
        for match in _ENGLISH_COUNTRY_PATTERN.finditer(normalized)
    ]


def _candidate_location_sources(candidate: dict[str, Any]) -> list[str]:
    sources = [
        str(candidate.get(key) or "")
        for key in ("alt", "alt_description", "description")
        if candidate.get(key)
    ]
    sources.extend(
        _url_semantic_text(str(candidate.get(key) or ""))
        for key in ("photo_page", "pexels_url", "source_url")
        if candidate.get(key)
    )
    return sources


def _structured_city_before_country(
    normalized: str,
    country_start: int,
    country: str,
) -> tuple[bool, str]:
    """Return whether a country mention is geographic and its inferred city.

    A lowercase word is only treated as a city when it directly precedes a
    recognized country. Generic descriptors stay descriptors. This bounded
    structure covers provider prose and semantic slugs without universal place
    guessing.
    """
    prefix = normalized[:country_start].split()
    if not prefix:
        return country not in _AMBIGUOUS_COUNTRY_NOUNS, ""

    while prefix and prefix[-1] in _GENERIC_LOCATION_MODIFIERS:
        prefix.pop()
    if not prefix:
        return country not in _AMBIGUOUS_COUNTRY_NOUNS, ""

    previous = prefix[-1]
    if previous in _LOCATION_CONTEXT_PREPOSITIONS:
        return True, ""
    if previous in _NON_CITY_BEFORE_COUNTRY:
        trailing = prefix[-4:]
        for index in range(len(trailing) - 1, -1, -1):
            if trailing[index] not in _LOCATION_CONTEXT_PREPOSITIONS:
                continue
            intervening = trailing[index + 1 :]
            if all(token in _NON_CITY_BEFORE_COUNTRY for token in intervening):
                return True, ""
            break
        return country not in _AMBIGUOUS_COUNTRY_NOUNS, ""
    if len(previous) < 3:
        return country not in _AMBIGUOUS_COUNTRY_NOUNS, ""

    city_words = [previous]
    city_has_locative_prefix = (
        len(prefix) >= 2 and prefix[-2] in _LOCATION_CONTEXT_PREPOSITIONS
    )
    if (
        len(prefix) >= 3
        and prefix[-3] in _LOCATION_CONTEXT_PREPOSITIONS
        and prefix[-2] not in _NON_CITY_BEFORE_COUNTRY
        and len(prefix[-2]) >= 3
    ):
        city_words.insert(0, prefix[-2])
        city_has_locative_prefix = True
    if country in _AMBIGUOUS_COUNTRY_NOUNS and not city_has_locative_prefix:
        return False, ""
    return True, " ".join(city_words)


def _canonical_location_phrase(value: str) -> str:
    normalized = _normalized_location_text(value)
    for canonical, aliases in LOCATION_ALIASES.items():
        if normalized in {
            _normalized_location_text(alias)
            for alias in aliases | {canonical}
        }:
            return canonical
    return normalized


def _article_location_evidence(
    article_text: str,
) -> tuple[set[str], set[tuple[str, str]]]:
    countries: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for country, start, _, normalized in _country_mentions(article_text):
        structured, city = _structured_city_before_country(
            normalized,
            start,
            country,
        )
        if structured or country not in _AMBIGUOUS_COUNTRY_NOUNS:
            countries.add(country)
        if structured and city:
            pairs.add((_canonical_location_phrase(city), country))
    return countries, pairs


def _unsupported_proper_location_phrases(
    candidate: dict[str, Any],
    intent: ImageIntent,
) -> set[str]:
    """Find explicit provider-side places outside the article's location truth.

    Country-anchored parsing handles lowercase prose and decoded provider slugs;
    capitalization remains a fallback for an otherwise unknown proper place.
    A place named in the article title remains supported through
    ``intent.subject`` even before it is added to a canonical alias table.
    """

    supported_tokens = _meaningful_tokens(
        intent.subject,
        " ".join(intent.locations),
        " ".join(intent.evidence_terms),
    )
    for location in intent.locations:
        supported_tokens.update(
            _meaningful_tokens(" ".join(LOCATION_ALIASES.get(location, {location})))
        )
    supported_country_sources = [
        intent.subject,
        " ".join(intent.locations),
        " ".join(intent.evidence_terms),
    ]
    supported_countries = {
        country
        for source in supported_country_sources
        for country, _, _, _ in _country_mentions(source)
    }
    supported_countries.update(
        country for _, country in getattr(intent, "location_pairs", [])
    )

    unsupported: set[str] = set()
    for source in _candidate_location_sources(candidate):
        for country, start, _, normalized in _country_mentions(source):
            has_location_structure, city = _structured_city_before_country(
                normalized,
                start,
                country,
            )
            if not has_location_structure:
                continue
            city_tokens = _meaningful_tokens(city)
            city_supported = not city or bool(
                city_tokens and city_tokens <= supported_tokens
            )
            canonical_city = _canonical_location_phrase(city) if city else ""
            expected_parent = LOCATION_PARENTS.get(canonical_city)
            if expected_parent and _normalized_location_text(expected_parent) != country:
                city_supported = False
            claimed_countries = {
                claimed_country
                for claimed_city, claimed_country in getattr(intent, "location_pairs", [])
                if claimed_city == canonical_city
            }
            if claimed_countries and country not in claimed_countries:
                city_supported = False
            if country not in supported_countries or not city_supported:
                unsupported.add(" ".join(part for part in (city, country) if part))

    pattern = re.compile(
        r"\b(?:in|at|near|from)\s+"
        r"((?:[A-ZÅÄÖ][A-Za-zÅÄÖåäö'-]{2,})"
        r"(?:\s+[A-ZÅÄÖ][A-Za-zÅÄÖåäö'-]{2,}){0,2})\b"
    )
    for key in ("alt", "alt_description", "description"):
        value = str(candidate.get(key) or "")
        for match in pattern.finditer(value):
            phrase = match.group(1).strip()
            phrase_tokens = _meaningful_tokens(phrase)
            if (
                not phrase_tokens
                or phrase_tokens & _NON_CITY_BEFORE_COUNTRY
                or phrase_tokens & supported_tokens
            ):
                continue
            unsupported.add(phrase.lower())
    return unsupported


def _sensitive_tokens(tokens: set[str]) -> set[str]:
    return {
        token
        for token in tokens
        if token in SENSITIVE_TERMS
        or any(token.startswith(prefix) for prefix in SENSITIVE_PREFIXES)
        or any(stem in token for stem in SENSITIVE_COMPOUND_STEMS)
    }


def _has_stem(tokens: list[str], stems: tuple[str, ...]) -> bool:
    return any(token.startswith(stem) for token in tokens for stem in stems)


def _winter_occurrence_is_negated(words: list[str], index: int) -> bool:
    before = words[max(0, index - 4):index]
    after = words[index + 1:index + 7]

    for position, token in enumerate(before):
        if token not in WINTER_NEGATION_TERMS:
            continue
        between = before[position + 1:]
        if token in {"ilman", "no", "not", "without"}:
            return True
        if len(between) <= 1 or _has_stem(between, WINTER_NEGATION_BEFORE_STEMS):
            return True

    for position, token in enumerate(after[:4]):
        if token not in WINTER_NEGATION_TERMS:
            continue
        context = [*after[:position], *after[position + 1:position + 5]]
        if token in {"ilman", "no", "without"} or _has_stem(
            context, WINTER_IRRELEVANCE_STEMS
        ):
            return True
    return False


def _winter_occurrence_is_meta_mention(words: list[str], index: int, term: str) -> bool:
    window = words[max(0, index - 5):index + 6]
    if not _has_stem(window, WINTER_META_MENTION_STEMS):
        return False
    other_visual_context = (
        set(window) & (WINTER_VISUAL_CONTEXT_TERMS - {term})
    )
    return not other_visual_context


def _lumi_occurrence_is_person_name(
    original_words: list[str], lowered_words: list[str], index: int
) -> bool:
    if original_words[index] != "Lumi":
        return False
    if index + 1 >= len(original_words):
        return False
    following_original = original_words[index + 1]
    following = lowered_words[index + 1]
    return (
        following in LUMI_PERSON_ACTION_TERMS
        or bool(re.fullmatch(r"[A-ZÅÄÖ][a-zåäö-]+", following_original))
    )


def _winter_tokens(article_text: str, tokens: set[str]) -> set[str]:
    hits = tokens & WINTER_TERMS
    # Bare Finnish "jää" is usually the verb "remains" in news prose. Accept
    # it as ice only with a concrete natural-surface context.
    if re.search(r"\b(?:järven|meren|joen|lammen|heikko|paksu|ohut)\s+jää\b", article_text.lower()):
        hits = {*hits, "jää"}

    original_words = re.findall(r"[A-ZÅÄÖa-zåäö]+", article_text or "")
    lowered_words = [word.lower() for word in original_words]
    supported: set[str] = set()
    for term in hits:
        occurrences = [
            index for index, word in enumerate(lowered_words) if word == term
        ]
        if not occurrences:
            supported.add(term)
            continue
        if any(
            not _winter_occurrence_is_negated(lowered_words, index)
            and not _winter_occurrence_is_meta_mention(lowered_words, index, term)
            and not (
                term == "lumi"
                and _lumi_occurrence_is_person_name(original_words, lowered_words, index)
            )
            for index in occurrences
        ):
            supported.add(term)
    return supported


def _rule_matches(article_tokens: set[str], cues: set[str]) -> bool:
    hits = article_tokens & cues
    return bool(hits)


def _matching_concept_rules(
    article_tokens: set[str],
) -> list[tuple[set[str], str, tuple[str, ...]]]:
    matches = [
        rule for rule in ARTICLE_VISUAL_CONCEPT_RULES if _rule_matches(article_tokens, rule[0])
    ]
    if not matches:
        return []
    top_priority = max(CONCEPT_RULE_PRIORITY.get(rule[1], 50) for rule in matches)
    return [
        rule for rule in matches if CONCEPT_RULE_PRIORITY.get(rule[1], 50) == top_priority
    ]


def _intent_support_issues(supplied: ImageIntent, grounded: ImageIntent) -> list[str]:
    issues: list[str] = []
    if supplied.season_time not in {"", "neutral", grounded.season_time}:
        issues.append(f"unsupported supplied intent season_time={supplied.season_time}")
    grounded_must = set(grounded.must_have)
    for constraint in supplied.must_have:
        if constraint not in grounded_must:
            issues.append(f"unsupported supplied intent must_have={constraint}")
    if supplied.stock_ok and not grounded.stock_ok:
        issues.append(
            "unsupported supplied intent stock_ok=true: " + _stock_policy_reason(grounded)
        )
    grounded_locations = set(grounded.locations)
    for location in supplied.locations:
        if location not in grounded_locations:
            issues.append(f"unsupported supplied intent location={location}")
    return issues


def stored_intent_support_issues(
    stored: dict[str, Any] | None,
    grounded: ImageIntent,
) -> list[str]:
    """Explain constraints in persisted intent that article truth does not support."""
    stored = stored or {}
    issues: list[str] = []
    season = str(stored.get("season_time") or "neutral")
    if season not in {"", "neutral", grounded.season_time}:
        issues.append(f"unsupported stored intent season_time={season}")
    grounded_must = set(grounded.must_have)
    raw_must = stored.get("must_have") or []
    if isinstance(raw_must, str):
        raw_must = [raw_must]
    for constraint in raw_must:
        value = str(constraint).strip()
        if value and value not in grounded_must:
            issues.append(f"unsupported stored intent must_have={value}")
    raw_locations = stored.get("locations") or stored.get("location") or []
    if isinstance(raw_locations, str):
        raw_locations = [raw_locations]
    for location in raw_locations:
        value = str(location).strip().lower()
        normalized = _locations_from_tokens(_tokens(value)) if value else set()
        if value and not normalized:
            normalized = {value}
        if normalized - set(grounded.locations):
            issues.append(f"unsupported stored intent location={value}")
    if bool(stored.get("stock_ok", True)) and not grounded.stock_ok:
        issues.append(
            "unsupported stored intent stock_ok=true: " + _stock_policy_reason(grounded)
        )
    return issues


def _named_person_like(text: str) -> bool:
    # Finnish article titles often capitalize only proper names. Two adjacent
    # capitalized words is a conservative enough proxy for stock-person safety.
    person_text = _STRUCTURED_COUNTRY_PERSON_PATTERN.sub("", text or "")
    location_phrases = sorted(
        {
            alias
            for aliases in LOCATION_ALIASES.values()
            for alias in aliases
            if " " in alias
        },
        key=len,
        reverse=True,
    )
    for phrase in location_phrases:
        person_text = re.sub(
            rf"(?<!\w){re.escape(phrase)}(?!\w)", "", person_text, flags=re.IGNORECASE
        )
    if re.search(r"\b[A-ZÅÄÖ][a-zåäö]+(?:\s+[A-ZÅÄÖ][a-zåäö]+)+\b", person_text):
        return True

    words = re.findall(r"[A-ZÅÄÖa-zåäö][A-ZÅÄÖa-zåäö'-]*", text or "")
    lowered = [word.lower() for word in words]
    if set(lowered) & PERSON_ROLE_TERMS and set(lowered) & PERSON_HEADLINE_ACTION_TERMS:
        return True

    for index, word in enumerate(words):
        is_capitalized = bool(re.fullmatch(r"[A-ZÅÄÖ][a-zåäö][A-ZÅÄÖa-zåäö'-]*", word))
        is_all_caps = len(word) > 2 and word.isupper()
        normalized = word.lower()
        if (
            not (is_capitalized or is_all_caps)
            or normalized in NON_PERSON_CAPITALIZED_TERMS
            or normalized in KNOWN_LOCATION_TERMS
            or normalized in PERSON_ROLE_TERMS
        ):
            continue
        previous = lowered[index - 1] if index else ""
        following = lowered[index + 1] if index + 1 < len(lowered) else ""
        if previous in PERSON_ROLE_TERMS or following in PERSON_HEADLINE_ACTION_TERMS:
            return True
    return False


def _missing_concept_anchors(intent: ImageIntent, candidate_tokens: set[str]) -> list[str]:
    return [
        concept
        for concept, anchors in CONCEPT_SPECIFIC_ANCHORS.items()
        if concept in intent.must_have and not candidate_tokens & anchors
    ]


def build_image_intent(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    query: str = "",
) -> ImageIntent:
    """Derive conservative visual truth without using any image-side fields."""
    key_points = key_points or []
    article_text = " ".join(
        [title or "", summary or "", " ".join(key_points), content or "", source_evidence or ""]
    )
    article_tokens = _tokens(article_text)
    meaningful_article_tokens = _meaningful_tokens(article_text)
    winter_hits = _winter_tokens(article_text, article_tokens)

    must_have: list[str] = []
    must_not: list[str] = []
    season_time = "neutral"
    safety_mode = "normal"
    stock_ok = True

    if (article_tokens & (WEATHER_TERMS - WINTER_TERMS)) or winter_hits:
        must_have.append("weather")
    if article_tokens & BOAT_REPAIR_TERMS and article_tokens & (REPAIR_WORK_TERMS | YOUTH_ENTREPRENEUR_TERMS):
        must_have.append("boat repair or small craft restoration")
        must_not.extend(["skyscraper", "office tower", "generic business district"])
    if article_tokens & SUN_TERMS:
        must_have.append("sunny or bright outdoor weather")
        must_not.extend(["snow", "winter", "rainstorm"])
        season_time = "summer or non-winter"
    if article_tokens & RAIN_TERMS:
        must_have.append("rain or clouds")
        must_not.append("snow")
    if article_tokens & HEAT_TERMS:
        must_have.append("warm weather")
        must_not.extend(["snow", "ice", "cold"])
        season_time = "summer or hot"
    if winter_hits:
        must_have.append("winter conditions")
        season_time = "winter"
    for _, required_concept, _ in _matching_concept_rules(article_tokens):
        must_have.append(required_concept)

    named_person = any(
        _named_person_like(part)
        for part in [title, summary, *(key_points or []), content, source_evidence]
        if part
    )
    sensitive_hits = _sensitive_tokens(article_tokens)
    sensitive = bool(sensitive_hits)
    if named_person or sensitive:
        safety_mode = "illustration_only"
        if named_person:
            must_not.append("generic person portrait or lookalike")
        if sensitive:
            must_not.append("realistic victim, crime, attack, or disaster scene")

    subject_terms = _ordered_meaningful_tokens(title)[:5]
    subject = " ".join(subject_terms) or (category or "news")
    setting = CATEGORY_SETTINGS.get(category, CATEGORY_SETTINGS.get(category.title(), "neutral news context"))
    article_countries, location_pairs = _article_location_evidence(article_text)
    location_set = _locations_from_tokens(
        meaningful_article_tokens,
        include_article_demonyms=True,
    )
    location_set.update(
        _canonical_location_phrase(country) for country in article_countries
    )
    location_set.update(city for city, _ in location_pairs)
    locations = sorted(location_set)
    stock_ok = not sensitive and not named_person
    generated_ok = not sensitive and bool(must_have)

    return ImageIntent(
        subject=subject,
        setting=setting,
        season_time=season_time,
        must_have=list(dict.fromkeys(must_have)),
        must_not=list(dict.fromkeys(must_not)),
        stock_ok=stock_ok,
        generated_ok=generated_ok,
        safety_mode=safety_mode,
        named_person=named_person,
        sensitive_story=sensitive,
        locations=locations,
        evidence_terms=sorted(
            meaningful_article_tokens
            & (
                (WEATHER_TERMS - WINTER_TERMS)
                | winter_hits
                | BOAT_REPAIR_TERMS
                | REPAIR_WORK_TERMS
                | set().union(*(cues for cues, _, _ in ARTICLE_VISUAL_CONCEPT_RULES))
                | sensitive_hits
            )
        ),
        style_preference="editorial illustration preferred for unsafe specifics",
        location_pairs=sorted(location_pairs),
    )


def build_visual_brief(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    query: str = "",
) -> VisualBrief:
    """Build the Image Flow v2 structured brief from article text."""
    intent = build_image_intent(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        query=query,
    )
    article_text = " ".join(
        [title, summary, " ".join(key_points or []), content, source_evidence]
    )
    article_tokens = _tokens(article_text)
    winter_hits = _winter_tokens(article_text, article_tokens)
    concepts: list[str] = []
    forbidden = list(intent.must_not)

    if "boat repair or small craft restoration" in intent.must_have:
        concepts.extend([
            "boat repair workshop",
            "small craft restoration",
            "rowboat maintenance",
        ])
        forbidden.extend([
            "skyscrapers or glass office towers",
            "generic finance skyline",
            "corporate city district",
        ])
    if (article_tokens & (WEATHER_TERMS - WINTER_TERMS)) or winter_hits:
        if article_tokens & SUN_TERMS:
            concepts.append("sunny Finnish weather")
        elif article_tokens & RAIN_TERMS:
            concepts.append("rainy Finnish weather")
        elif winter_hits:
            concepts.append("winter weather")
        else:
            concepts.append("weather forecast")
    for _, _, article_concepts in _matching_concept_rules(article_tokens):
        concepts.extend(article_concepts)

    return VisualBrief(
        acceptable_concepts=[c for c in dict.fromkeys(concepts) if c],
        hard_forbidden_implications=[f for f in dict.fromkeys(forbidden) if f],
        intent=intent,
    )


def build_stock_queries(
    title: str,
    category: str = "",
    *,
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    primary_query: str = "",
) -> list[tuple[str, str, VisualBrief]]:
    """Return bounded stock search concepts for Image Flow v2."""
    brief = build_visual_brief(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        query=primary_query,
    )
    if not brief.intent.stock_ok or not brief.acceptable_concepts:
        return []
    queries: list[tuple[str, str, VisualBrief]] = []
    for concept in brief.acceptable_concepts[:3]:
        queries.append((concept, concept, brief))
    grounded_query_tokens = _meaningful_tokens(" ".join(brief.acceptable_concepts))
    if (
        primary_query
        and _meaningful_tokens(primary_query) & grounded_query_tokens
        and primary_query not in {q for q, _, _ in queries}
    ):
        queries.append((primary_query, "primary_query", brief))
    return queries[:4]


def _source_id(candidate: dict[str, Any]) -> tuple[str, str]:
    candidate_id = str(candidate.get("id") or "unknown")
    source_url = str(candidate.get("photo_page") or candidate.get("pexels_url") or candidate.get("url") or "")
    return candidate_id, source_url


def score_image_candidate(
    candidate: dict[str, Any],
    *,
    intent: ImageIntent,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    category: str = "",
    provider: str = "image",
) -> CandidateDecision:
    """Score stock metadata against independently re-derived article truth."""
    grounded_brief = build_visual_brief(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
    )
    grounded_intent = grounded_brief.intent
    intent_issues = _intent_support_issues(intent, grounded_intent)
    if intent_issues:
        if not grounded_intent.stock_ok:
            intent_issues.append(_stock_policy_reason(grounded_intent))
        candidate_id, source_url = _source_id(candidate)
        return CandidateDecision(
            provider, candidate_id, source_url, MISMATCH_SCORE, False, intent_issues
        )

    article_text = " ".join(
        [title, summary, " ".join(key_points or []), content, source_evidence]
    )
    article_tokens = _tokens(article_text)
    query_tokens = _meaningful_tokens(query)
    grounded_tokens = _meaningful_tokens(
        " ".join(grounded_brief.acceptable_concepts),
        " ".join(grounded_intent.must_have),
    )
    candidate_text = _candidate_text(candidate)
    candidate_tokens = _meaningful_tokens(candidate_text)
    candidate_id, source_url = _source_id(candidate)

    score = 50
    reasons: list[str] = []

    if not candidate_text.strip() or not candidate_tokens:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            ["candidate has no semantic metadata"],
        )
    if not grounded_intent.stock_ok:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            [_stock_policy_reason(grounded_intent)],
        )
    if grounded_intent.safety_mode == "illustration_only" and candidate_tokens & PERSON_IMAGE_TERMS:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            ["generic person/lookalike metadata is unsafe for named-person or sensitive story"],
        )
    if not grounded_tokens:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            [
                "candidate metadata has no article-grounded concept overlap: "
                "article has no independently grounded concrete visual concept"
            ],
        )

    grounded_overlap = grounded_tokens & candidate_tokens
    if grounded_overlap:
        score += min(25, 5 * len(grounded_overlap))
        reasons.append(f"metadata matches {', '.join(sorted(grounded_overlap)[:5])}")
        query_overlap = _meaningful_tokens(query) & candidate_tokens
        if query_overlap:
            score += min(5, len(query_overlap))
            reasons.append(f"retrieval hint matches {', '.join(sorted(query_overlap)[:5])}")

    article_winter = _winter_tokens(article_text, article_tokens)
    article_weather = bool(article_tokens & (WEATHER_TERMS - WINTER_TERMS) or article_winter)
    candidate_winter = candidate_tokens & WINTER_TERMS
    weather_cues = candidate_tokens & WEATHER_TERMS
    if weather_cues and article_weather:
        score += 10
        reasons.append("weather metadata matches visual intent")
    if candidate_tokens & SUN_TERMS and (article_tokens & SUN_TERMS):
        score += 10
        reasons.append("sunny metadata matches visual intent")
    if candidate_tokens & RAIN_TERMS and (article_tokens & RAIN_TERMS):
        score += 10
        reasons.append("rain metadata matches visual intent")

    article_is_weather = article_weather
    article_allows_winter = bool(article_winter)
    article_allows_rain = bool(article_tokens & RAIN_TERMS)
    article_requests_sun = bool(article_tokens & SUN_TERMS)
    article_requests_heat = bool(article_tokens & HEAT_TERMS)

    hard_rejects: list[str] = []
    for missing_concept in _missing_concept_anchors(grounded_intent, candidate_tokens):
        hard_rejects.append(
            f"candidate lacks concept-specific anchor for {missing_concept}"
        )
    if weather_cues and not article_is_weather:
        hard_rejects.append("weather metadata lacks article-grounded support")
    if candidate_winter and not article_allows_winter:
        hard_rejects.append("winter metadata lacks article-grounded support")
    if article_is_weather and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts non-winter weather story")
    if article_requests_sun and not article_allows_rain and candidate_tokens & RAIN_TERMS:
        hard_rejects.append("rain/storm metadata contradicts sunny weather story")
    if article_requests_sun and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts sunny weather story")
    if article_requests_heat and candidate_tokens & (WINTER_TERMS | COLD_TERMS):
        hard_rejects.append("cold/winter metadata contradicts heat weather story")
    if article_allows_rain and not article_allows_winter and candidate_tokens & WINTER_TERMS:
        hard_rejects.append("winter metadata contradicts rain-only weather story")
    if grounded_intent.safety_mode == "illustration_only" and candidate_tokens & PERSON_IMAGE_TERMS:
        hard_rejects.append("generic person/lookalike metadata is unsafe for named-person or sensitive story")
    candidate_locations = _locations_from_tokens(candidate_tokens)
    unsupported_locations = candidate_locations - set(grounded_intent.locations)
    if unsupported_locations:
        hard_rejects.append(
            f"candidate location lacks article support: {', '.join(sorted(unsupported_locations))}"
        )
    unsupported_location_phrases = _unsupported_proper_location_phrases(
        candidate,
        grounded_intent,
    )
    if unsupported_location_phrases:
        hard_rejects.append(
            "candidate location lacks article support: "
            + ", ".join(sorted(unsupported_location_phrases))
        )
    concrete_boat_repair_story = bool(
        article_tokens & BOAT_REPAIR_TERMS
        and article_tokens & (REPAIR_WORK_TERMS | YOUTH_ENTREPRENEUR_TERMS)
    )
    if concrete_boat_repair_story and not candidate_tokens & BOAT_REPAIR_TERMS:
        if candidate_tokens & URBAN_BUSINESS_IMAGE_TERMS:
            hard_rejects.append("urban business/skyscraper metadata contradicts concrete boat-repair story")
        elif query_tokens & URBAN_BUSINESS_IMAGE_TERMS:
            hard_rejects.append("broad business query lacks required boat-repair subject")

    if hard_rejects:
        return CandidateDecision(provider, candidate_id, source_url, MISMATCH_SCORE, False, hard_rejects)

    if not grounded_overlap:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            ["candidate metadata has no article-grounded concept overlap"],
        )

    specific_weather_match = bool(
        article_is_weather
        and (
            (candidate_tokens & SUN_TERMS and article_tokens & SUN_TERMS)
            or (candidate_tokens & RAIN_TERMS and article_tokens & RAIN_TERMS)
            or (candidate_winter and article_winter)
        )
    )
    if len(grounded_overlap) < 2 and not specific_weather_match:
        return CandidateDecision(
            provider,
            candidate_id,
            source_url,
            MISMATCH_SCORE,
            False,
            [
                "candidate metadata has insufficient article-grounded concept overlap: "
                + ", ".join(sorted(grounded_overlap))
            ],
        )

    if any(term in candidate_tokens for term in {"generic", "abstract", "background"}):
        score -= 8
        reasons.append("generic stock metadata")

    accepted = grounded_intent.stock_ok and score >= ACCEPT_THRESHOLD
    if not accepted:
        reasons.append(f"score below threshold {ACCEPT_THRESHOLD}")
    elif not reasons:
        reasons.append("accepted")

    return CandidateDecision(provider, candidate_id, source_url, score, accepted, reasons)


def judge_visual_candidate(
    candidate: dict[str, Any],
    *,
    brief: VisualBrief,
    provider: str = "image",
) -> VisualJudgeDecision:
    """Deterministic local visual judge over available image metadata.

    Production can replace this with an actual vision-model call, but the gate is
    already fail-closed: hard forbidden implications and uncertainty override the
    keyword/category score.
    """
    candidate_tokens = _meaningful_tokens(_candidate_text(candidate))
    text = _candidate_text(candidate).lower()
    reasons: list[str] = []
    hard_fails: list[str] = []

    if brief.intent.safety_mode == "illustration_only" and candidate_tokens & PERSON_IMAGE_TERMS:
        hard_fails.append(
            "generic person/lookalike metadata is unsafe for named-person or sensitive story"
        )
    for missing_concept in _missing_concept_anchors(brief.intent, candidate_tokens):
        hard_fails.append(
            f"candidate lacks concept-specific anchor for {missing_concept}"
        )
    candidate_locations = _locations_from_tokens(candidate_tokens)
    unsupported_locations = candidate_locations - set(brief.intent.locations)
    if unsupported_locations:
        hard_fails.append(
            f"candidate location lacks article support: {', '.join(sorted(unsupported_locations))}"
        )
    unsupported_location_phrases = _unsupported_proper_location_phrases(
        candidate,
        brief.intent,
    )
    if unsupported_location_phrases:
        hard_fails.append(
            "candidate location lacks article support: "
            + ", ".join(sorted(unsupported_location_phrases))
        )

    for forbidden in brief.hard_forbidden_implications:
        forbidden_tokens = _meaningful_tokens(forbidden)
        if forbidden_tokens and candidate_tokens & forbidden_tokens:
            hard_fails.append(f"forbidden visual implication: {forbidden}")

    if hard_fails:
        return VisualJudgeDecision(MISMATCH_SCORE, False, hard_fails, hard_fail=True)
    if provider == "generated" and not brief.intent.generated_ok:
        return VisualJudgeDecision(
            MISMATCH_SCORE,
            False,
            ["article truth is generated-image-ineligible"],
            hard_fail=True,
        )
    if provider != "generated" and not brief.intent.stock_ok:
        return VisualJudgeDecision(
            MISMATCH_SCORE,
            False,
            [_stock_policy_reason(brief.intent)],
            hard_fail=True,
        )

    score = 25
    supported_tokens: set[str] = set()
    for concept in brief.acceptable_concepts:
        concept_tokens = _meaningful_tokens(concept)
        overlap = concept_tokens & candidate_tokens
        if overlap:
            supported_tokens.update(overlap)
            score += min(35, 12 * len(overlap))
            reasons.append(f"visual metadata supports concept '{concept}'")

    for required in brief.intent.must_have:
        required_tokens = _meaningful_tokens(required)
        overlap = required_tokens & candidate_tokens
        if overlap:
            supported_tokens.update(overlap)
            score += min(25, 10 * len(overlap))
            reasons.append(f"visual metadata supports required cue '{required}'")

    if not text.strip():
        score = min(score, 45)
        reasons.append("visual judge uncertain: no image metadata")
    if not reasons:
        reasons.append("visual judge uncertain: no acceptable concept evidence")

    weather_specific = bool(
        supported_tokens
        and candidate_tokens & WEATHER_TERMS
        and "weather" in brief.intent.must_have
    )
    if len(supported_tokens) < 2 and not weather_specific:
        score = min(score, VISUAL_JUDGE_ACCEPT_THRESHOLD - 1)
        reasons.append("visual judge has fewer than two concrete grounded evidence tokens")

    accepted = score >= VISUAL_JUDGE_ACCEPT_THRESHOLD
    if not accepted:
        reasons.append(f"visual judge score below threshold {VISUAL_JUDGE_ACCEPT_THRESHOLD}")
    return VisualJudgeDecision(min(score, 100), accepted, reasons, hard_fail=False)


def vet_image_candidate(
    candidate: dict[str, Any],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    category: str = "",
) -> tuple[bool, str]:
    """Backward-compatible boolean vetting API."""
    intent = build_image_intent(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        query=query,
    )
    decision = score_image_candidate(
        candidate,
        intent=intent,
        query=query,
        title=title,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        category=category,
    )
    return decision.accepted, "; ".join(decision.reasons)


def filter_image_candidates(
    candidates: list[dict[str, Any]],
    *,
    query: str,
    title: str = "",
    summary: str = "",
    key_points: list[str] | None = None,
    content: str = "",
    source_evidence: str = "",
    category: str = "",
    provider: str = "image",
    intent: ImageIntent | None = None,
    brief: VisualBrief | None = None,
    concept: str = "",
    return_decisions: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[CandidateDecision]]:
    """Filter stock candidates, preserving scored decision evidence."""
    grounded_brief = build_visual_brief(
        title,
        category,
        summary=summary,
        key_points=key_points,
        content=content,
        source_evidence=source_evidence,
        query=query,
    )
    supplied_intent = intent or (brief.intent if brief is not None else grounded_brief.intent)
    accepted: list[dict[str, Any]] = []
    decisions: list[CandidateDecision] = []
    for candidate in candidates:
        decision = score_image_candidate(
            candidate,
            intent=supplied_intent,
            query=query,
            title=title,
            summary=summary,
            key_points=key_points,
            content=content,
            source_evidence=source_evidence,
            category=category,
            provider=provider,
        )
        judge = judge_visual_candidate(candidate, brief=grounded_brief, provider=provider)
        if decision.accepted and not judge.accepted:
            decision = CandidateDecision(
                provider,
                decision.candidate_id,
                decision.source_url,
                decision.score,
                False,
                [*decision.reasons, *judge.reasons],
            )
        decisions.append(decision)
        if decision.accepted:
            enriched = dict(candidate)
            enriched["_image_decision"] = decision.to_dict()
            enriched["_image_visual_intent"] = grounded_brief.intent.to_dict()
            enriched["_image_visual_brief"] = grounded_brief.to_dict()
            enriched["_image_visual_judge"] = judge.to_dict()
            enriched["_image_concept"] = concept or query
            accepted.append(enriched)
        else:
            print(f"[{provider}] Rejected image candidate {decision.candidate_id}: {'; '.join(decision.reasons)}")

    if return_decisions:
        return accepted, decisions
    return accepted


def category_fallback_fields(category: str, *, reason: str) -> dict[str, Any]:
    """Neutral fallback frontmatter fields for a category placeholder."""
    category = category or "Kotimaa"
    cat_slug = category.lower()
    return {
        "image": f"/images/categories/{cat_slug}.jpg",
        "image_thumb": f"/images/categories/{cat_slug}.jpg",
        "image_alt": f"{category}-uutiset",
        "image_credit": "",
        "image_source_url": "",
        "image_caption": "",
        "image_hotlink": False,
        "image_category_fallback": True,
        "image_source": "category_fallback",
        "image_source_type": "category_fallback",
        "image_asset_identity": "",
        "image_decision_reason": reason,
        "image_prompt_version": PROMPT_VERSION,
        "image_visual_judge_score": 0,
        "image_decision": {
            "source": "category_fallback",
            "accepted": True,
            "reason": reason,
            "prompt_version": PROMPT_VERSION,
        },
    }


def stock_decision_fields(provider: str, result: dict[str, Any], query: str) -> dict[str, Any]:
    """Frontmatter-safe stock decision evidence."""
    decision = result.get("decision") or result.get("_image_decision") or {}
    intent = result.get("intent") or result.get("_image_visual_intent") or {}
    brief = result.get("brief") or result.get("_image_visual_brief") or {}
    judge = result.get("visual_judge") or result.get("_image_visual_judge") or {}
    concept = result.get("concept") or result.get("_image_concept") or query
    reasons = [str(reason) for reason in decision.get("reasons", []) if str(reason).strip()]
    try:
        try:
            from image_state import canonical_image_identity
        except ImportError:  # pragma: no cover - package import path
            from .image_state import canonical_image_identity

        identity_candidate = dict(result)
        identity_candidate["candidate_id"] = decision.get("candidate_id")
        identity_candidate["source_url"] = decision.get("source_url")
        asset_identity = canonical_image_identity(provider, identity_candidate)
    except (ImportError, TypeError, ValueError):
        asset_identity = ""
    return {
        "image_source": provider,
        "image_source_type": "stock",
        "image_decision_reason": "; ".join(reasons) or f"{provider} accepted",
        "image_visual_intent": intent,
        "image_visual_brief": brief,
        "image_concept": concept,
        "image_query": query,
        "image_candidate_id": decision.get("candidate_id"),
        "image_candidate_url": decision.get("source_url"),
        "image_asset_identity": asset_identity,
        "image_visual_judge_score": judge.get("score"),
        "image_accepted_reasons": reasons,
        "image_rejected_reasons": [],
        "image_prompt_version": PROMPT_VERSION,
        "image_decision": {
            "source": provider,
            "query": query,
            "concept": concept,
            "accepted": True,
            "score": decision.get("score"),
            "candidate_id": decision.get("candidate_id"),
            "asset_identity": asset_identity,
            "source_url": decision.get("source_url"),
            "visual_judge_score": judge.get("score"),
            "visual_judge_reasons": judge.get("reasons", []),
            "reasons": reasons,
            "prompt_version": PROMPT_VERSION,
        },
        "image_quality_score": decision.get("score"),
        "image_category_fallback": False,
    }


def generated_decision_fields(
    *,
    provider: str,
    model: str,
    prompt: str,
    image_path: str,
    brief: VisualBrief | dict[str, Any],
    judge: VisualJudgeDecision | dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    brief_dict = brief.to_dict() if hasattr(brief, "to_dict") else dict(brief or {})
    judge_dict = judge.to_dict() if hasattr(judge, "to_dict") else dict(judge or {})
    accepted = bool(judge_dict.get("accepted"))
    return {
        "image_source": "generated",
        "image_source_type": "generated_editorial",
        "image_decision_reason": reason,
        "image_generated_fallback": True,
        "image_visual_brief": brief_dict,
        "image_visual_intent": brief_dict.get("intent", {}),
        "image_concept": (brief_dict.get("acceptable_concepts") or ["generated editorial"])[0],
        "image_query": "",
        "image_candidate_id": image_path,
        "image_candidate_url": image_path,
        "image_visual_judge_score": judge_dict.get("score"),
        "image_accepted_reasons": judge_dict.get("reasons", []) if accepted else [],
        "image_rejected_reasons": [] if accepted else judge_dict.get("reasons", []),
        "image_provider": provider,
        "image_model": model,
        "image_prompt_version": PROMPT_VERSION,
        "image_generation_prompt": prompt,
        "image_decision": {
            "source": "generated",
            "accepted": accepted,
            "reason": reason,
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "visual_judge_score": judge_dict.get("score"),
            "visual_judge_reasons": judge_dict.get("reasons", []),
        },
    }

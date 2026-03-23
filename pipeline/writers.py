"""
Writer assignment — returns the editorial staff identity.
Fictional journalist personas removed (launch blocker, Monica's audit).
All articles are attributed to "Toimitus" (editorial staff).
"""

from typing import Dict

EDITORIAL_STAFF: Dict = {
    "id": "toimitus",
    "name": "Toimitus",
    "title": "Uutistenlukija-toimitus",
    "bio": "Uutistenlukija kokoaa ja tiivistää päivän tärkeimmät uutiset suomeksi.",
    "specialties": [],
    "image": "",
}


def assign_writer(category: str) -> Dict:
    """All articles are attributed to the editorial staff."""
    return EDITORIAL_STAFF

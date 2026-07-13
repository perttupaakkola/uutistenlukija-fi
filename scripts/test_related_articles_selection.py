#!/usr/bin/env python3
"""Regression checks for category-aware related article rendering."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path


CASES = {
    "2026-07-12-sahkon-futuurihinnat-nousivat-jyrkasti-loppuvuodelle-2026": (
        "talous",
        ("mariano-rajoyta", "sonya-luopumasta-fyysisist"),
        (
            "/posts/2026-07-10-pankinjohtajat-40-vuoden-asuntolainat-kiinnostavat-etenkin-e/",
            "/posts/2026-05-26-selvitys-suomi-on-muuttunut-sijoittajakansaksi/",
            "/posts/2026-05-07-porssisahko-kallistuu-torstai-illaksi-perjantaina-hinnat-las/",
        ),
    ),
    "2026-07-12-etela-afrikka-kasittelee-yli-53-000-ulkomaalaisen-palauttami": (
        "ulkomaat",
        (),
        (
            "/posts/2026-07-11-etela-afrikan-maajoukkuepelaaja-jayden-adams-on-kuollut-25-v/",
            "/posts/2026-07-05-floridalainen-republikaani-varoittaa-haitilaisten-suojeluase/",
            "/posts/2026-07-01-yhdysvaltain-korkein-oikeus-piti-syntymapaikkaan-perustuvan/",
        ),
    ),
}

TARGET_HREF = (
    "/posts/2026-04-30-mm-kisoissa-voidaan-antaa-punainen-kortti-"
    "myos-suun-peittami/"
)

OPT_IN_CASES = (
    "2026-07-12-argentiina-eteni-valieriin-dramaattisten-vaiheiden-jalkeen-e",
    "2026-07-12-haaland-uupui-mm-puolivalierassa-norjassa-raivostuttiin-tuom",
)


class RelatedCardsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_related = False
        self.depth = 0
        self.categories: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "section" and "related-articles" in classes:
            self.in_related = True
            self.depth = 1
            return
        if not self.in_related:
            return
        if tag == "section":
            self.depth += 1
        if tag == "span" and "related-card__cat" in classes:
            category_class = next(
                value.removeprefix("related-card__cat--")
                for value in classes
                if value.startswith("related-card__cat--")
            )
            self.categories.append(category_class)
        if tag == "a" and "href" in values and len(self.hrefs) < len(self.categories):
            self.hrefs.append(values["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if self.in_related and tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.in_related = False


def check_page(
    public_dir: Path,
    slug: str,
    expected_category: str,
    forbidden_href_fragments: tuple[str, ...],
    expected_hrefs: tuple[str, ...] | None = None,
) -> None:
    page = public_dir / "posts" / slug / "index.html"
    parser = RelatedCardsParser()
    parser.feed(page.read_text(encoding="utf-8"))

    assert parser.categories == [expected_category] * 3, (
        f"{slug}: expected three {expected_category} cards, got {parser.categories}"
    )
    assert len(parser.hrefs) == 3, f"{slug}: expected three related links"
    assert len(set(parser.hrefs)) == 3, f"{slug}: duplicate related links: {parser.hrefs}"
    assert all(slug not in href for href in parser.hrefs), (
        f"{slug}: current article appeared in related links: {parser.hrefs}"
    )
    assert not any(
        fragment in href
        for fragment in forbidden_href_fragments
        for href in parser.hrefs
    ), f"{slug}: prohibited semantic mismatch remained: {parser.hrefs}"
    if expected_hrefs is not None:
        assert tuple(parser.hrefs) == expected_hrefs, (
            f"{slug}: default ranking changed: {parser.hrefs}"
        )


def check_opt_in_page(public_dir: Path, slug: str) -> None:
    page = public_dir / "posts" / slug / "index.html"
    parser = RelatedCardsParser()
    parser.feed(page.read_text(encoding="utf-8"))

    assert parser.categories == ["urheilu"] * 3, (
        f"{slug}: expected three urheilu cards, got {parser.categories}"
    )
    assert len(parser.hrefs) == 3, f"{slug}: expected three related links"
    assert len(set(parser.hrefs)) == 3, f"{slug}: duplicate related links: {parser.hrefs}"
    assert all(slug not in href for href in parser.hrefs), (
        f"{slug}: current article appeared in related links: {parser.hrefs}"
    )
    assert parser.hrefs.count(TARGET_HREF) == 1, (
        f"{slug}: expected target exactly once: {parser.hrefs}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-dir", type=Path, required=True)
    args = parser.parse_args()
    for slug, (expected_category, forbidden_href_fragments, expected_hrefs) in CASES.items():
        check_page(
            args.public_dir,
            slug,
            expected_category,
            forbidden_href_fragments,
            expected_hrefs,
        )
    for slug in OPT_IN_CASES:
        check_opt_in_page(args.public_dir, slug)
    print(
        "related article selection: default ranking unchanged; "
        "2 opt-in pages have one unique target among 3 same-category cards — PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
